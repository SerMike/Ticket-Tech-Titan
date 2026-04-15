"""run_pipeline.py — End-to-end evaluation pipeline runner.

Orchestrates Phase 2 from "ticket in DB" to "evaluation in DB":

    1. Open a Postgres connection.
    2. Query unprocessed tickets (LEFT JOIN ban_database, filtering out
       any ticket that already has a row in support_tickets_with_ai —
       unless --force is passed, in which case all tickets are picked
       up).
    3. For each row:
        - build ticket + ban_record dicts
        - evaluate_ticket()   (LLM call, JSON parse, validation)
        - enforce_auto_deny() (post-check safety net)
        - save_evaluation()   (UPSERT into support_tickets_with_ai)
       Each ticket is committed independently so one failure does not
       roll back the whole batch.
    4. Print a summary: totals, per-category counts, auto-deny
       overrides, failures.

Usage:
    python evaluation/run_pipeline.py              # process all unprocessed
    python evaluation/run_pipeline.py --limit 10   # cap batch size
    python evaluation/run_pipeline.py --force      # re-evaluate everything
    python evaluation/run_pipeline.py --ticket-id TKT-2025-00201
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras

# Allow running as a script from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force UTF-8 stdout/stderr for Windows consoles (ticket bodies contain
# smart quotes, em-dashes, etc.).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from config import settings  # noqa: E402
from evaluation.auto_deny import enforce_auto_deny  # noqa: E402
from evaluation.evaluator import EvaluationError, evaluate_ticket  # noqa: E402
from evaluation.writer import WriterError, save_evaluation  # noqa: E402

logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

# LEFT JOIN on ban_database so no-ban-record tickets still surface.
# NOT EXISTS clause makes the pipeline idempotent: already-evaluated
# tickets are skipped unless the caller asks for --force.
_FETCH_SQL_TEMPLATE = """
    SELECT
        t.ticket_id, t.user_name, t.user_id, t.ticket_issue_category,
        t.ticket_title, t.ticket_body,
        b.user_id AS ban_user_id, b.ban_reason, b.detection_method,
        b.ban_duration, b.ban_date
    FROM support_tickets t
    LEFT JOIN ban_database b ON t.user_id = b.user_id
    {where_clause}
    ORDER BY t.ticket_id
    {limit_clause}
"""


def _build_fetch_query(force: bool, ticket_id: str | None, limit: int | None):
    """Compose the fetch SQL and parameter tuple based on CLI flags."""
    where_parts = []
    params: list = []

    if ticket_id:
        where_parts.append("t.ticket_id = %s")
        params.append(ticket_id)
    elif not force:
        where_parts.append(
            "NOT EXISTS (SELECT 1 FROM support_tickets_with_ai a "
            "WHERE a.ticket_id = t.ticket_id)"
        )

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT %s"
        params.append(limit)

    sql = _FETCH_SQL_TEMPLATE.format(
        where_clause=where_clause, limit_clause=limit_clause
    )
    return sql, tuple(params)


def _split_row(row: dict) -> tuple[dict, dict | None]:
    """Split a joined row into (ticket_dict, ban_record_or_None)."""
    ticket = {
        "ticket_id": row["ticket_id"],
        "user_name": row["user_name"],
        "user_id": row["user_id"],
        "ticket_issue_category": row["ticket_issue_category"],
        "ticket_title": row["ticket_title"],
        "ticket_body": row["ticket_body"],
    }
    if row.get("ban_user_id") is None:
        return ticket, None
    ban = {
        "user_id": row["ban_user_id"],
        "ban_reason": row["ban_reason"],
        "detection_method": row["detection_method"],
        "ban_duration": row["ban_duration"],
        "ban_date": str(row["ban_date"]),
    }
    return ticket, ban


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PipelineStats:
    """Rolling counters for the end-of-run summary."""

    def __init__(self, total: int):
        self.total = total
        self.succeeded = 0
        self.failed = 0
        self.inserted = 0
        self.updated = 0
        self.overrides = 0
        self.admitted_cheating = 0
        self.admitted_exploit = 0
        self.no_ban_record = 0
        self.categories: dict[str, int] = {}
        self.failures: list[tuple[str, str]] = []  # (ticket_id, reason)

    def record_success(
        self,
        category: str,
        inserted: bool,
        overridden: bool,
        admitted_cheat: bool,
        admitted_exp: bool,
        had_ban: bool,
    ):
        self.succeeded += 1
        self.categories[category] = self.categories.get(category, 0) + 1
        if inserted:
            self.inserted += 1
        else:
            self.updated += 1
        if overridden:
            self.overrides += 1
        if admitted_cheat:
            self.admitted_cheating += 1
        if admitted_exp:
            self.admitted_exploit += 1
        if not had_ban:
            self.no_ban_record += 1

    def record_failure(self, ticket_id: str, reason: str):
        self.failed += 1
        self.failures.append((ticket_id, reason))


def process_one(conn, ticket: dict, ban: dict | None) -> tuple[str, bool, bool]:
    """Evaluate + override-check + persist one ticket.

    Returns (final_category, inserted, overridden). Raises
    EvaluationError or WriterError on failure; caller logs and moves on.
    """
    result = evaluate_ticket(ticket, ban)
    original_category = result["ai_category"]
    result = enforce_auto_deny(result, ban)
    overridden = result["ai_category"] != original_category
    inserted = save_evaluation(conn, result)
    conn.commit()  # commit per ticket so one failure doesn't poison the batch
    return result["ai_category"], inserted, overridden


def run_pipeline(force: bool, ticket_id: str | None, limit: int | None) -> PipelineStats:
    """Main entry point. Returns populated PipelineStats for reporting."""
    if not settings.DATABASE_URL:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        sys.exit(1)
    if not settings.ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    sql, params = _build_fetch_query(force, ticket_id, limit)

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        stats = PipelineStats(total=len(rows))
        if not rows:
            return stats

        logger.info("Processing %d ticket(s)...", len(rows))
        for idx, row in enumerate(rows, start=1):
            ticket, ban = _split_row(row)
            tid = ticket["ticket_id"]
            try:
                category, inserted, overridden = process_one(conn, ticket, ban)
            except EvaluationError as e:
                conn.rollback()
                logger.error("[%d/%d] %s EVAL FAILED: %s", idx, len(rows), tid, e)
                stats.record_failure(tid, f"EvaluationError: {e}")
                continue
            except WriterError as e:
                conn.rollback()
                logger.error("[%d/%d] %s WRITE FAILED: %s", idx, len(rows), tid, e)
                stats.record_failure(tid, f"WriterError: {e}")
                continue
            except Exception as e:  # noqa: BLE001 — log loudly, keep going
                conn.rollback()
                logger.exception("[%d/%d] %s UNEXPECTED ERROR", idx, len(rows), tid)
                stats.record_failure(tid, f"{type(e).__name__}: {e}")
                continue

            # Need the full result for admission flags — re-query.
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT admitted_cheating, admitted_exploit "
                    "FROM support_tickets_with_ai WHERE ticket_id = %s",
                    (tid,),
                )
                persisted = cur.fetchone()

            stats.record_success(
                category=category,
                inserted=inserted,
                overridden=overridden,
                admitted_cheat=bool(persisted["admitted_cheating"]),
                admitted_exp=bool(persisted["admitted_exploit"]),
                had_ban=ban is not None,
            )
            action = "inserted" if inserted else "updated"
            flag = " [OVERRIDE]" if overridden else ""
            logger.info(
                "[%d/%d] %s -> %s (%s)%s",
                idx, len(rows), tid, category, action, flag,
            )

        return stats
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

BAR = "=" * 70


def print_summary(stats: PipelineStats, elapsed: float) -> None:
    print(f"\n{BAR}")
    print("PIPELINE SUMMARY")
    print(BAR)
    print(f"Tickets processed:       {stats.total}")
    print(f"  succeeded:             {stats.succeeded}")
    print(f"  failed:                {stats.failed}")
    if stats.succeeded:
        print(f"  inserted (new):        {stats.inserted}")
        print(f"  updated (re-eval):     {stats.updated}")
        print(f"  auto-deny overrides:   {stats.overrides}")
        print(f"  admitted_cheating:     {stats.admitted_cheating}")
        print(f"  admitted_exploit:      {stats.admitted_exploit}")
        print(f"  no-ban-record tickets: {stats.no_ban_record}")
        print()
        print("Category breakdown:")
        for cat in sorted(stats.categories):
            n = stats.categories[cat]
            pct = 100.0 * n / stats.succeeded
            print(f"  {cat:28s} {n:>3d}  ({pct:5.1f}%)")
    if stats.failures:
        print("\nFailures:")
        for tid, reason in stats.failures:
            print(f"  {tid}: {reason}")
    print(f"\nElapsed: {elapsed:.1f}s")
    print(BAR)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of tickets to process this run."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-evaluate all tickets, including ones already in support_tickets_with_ai."
    )
    parser.add_argument(
        "--ticket-id", default=None,
        help="Process only the given ticket_id (overrides --force/--limit filtering)."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging (otherwise INFO)."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    start = time.monotonic()
    stats = run_pipeline(
        force=args.force, ticket_id=args.ticket_id, limit=args.limit,
    )
    elapsed = time.monotonic() - start
    print_summary(stats, elapsed)
    return 0 if stats.failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
