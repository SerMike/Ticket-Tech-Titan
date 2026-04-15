"""smoke_evaluate.py — Manual quality check for the evaluation engine.

Pulls N tickets from the database, joins on their ban records (if any),
runs them through evaluate_ticket() + enforce_auto_deny(), and prints
each result side-by-side so we can eyeball category and reasoning quality
before we commit to the writer and full pipeline.

This script does NOT persist anything. It's read-only against Postgres
and write-only to stdout.

Usage:
    python scripts/smoke_evaluate.py              # default: 5 random tickets
    python scripts/smoke_evaluate.py --count 10
    python scripts/smoke_evaluate.py --ticket-id TKT-10042
"""

import argparse
import sys
from pathlib import Path

# Force UTF-8 on stdout/stderr so non-ASCII characters in ticket bodies
# (smart quotes, ellipses, accented names) print cleanly on Windows
# consoles that otherwise default to cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import psycopg2
import psycopg2.extras

# Allow running as a script from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402  (loads .env as side effect)
from evaluation.auto_deny import enforce_auto_deny  # noqa: E402
from evaluation.evaluator import EvaluationError, evaluate_ticket  # noqa: E402


# ---------------------------------------------------------------------------
# DB fetch
# ---------------------------------------------------------------------------

# LEFT JOIN so we also surface the rare no-ban-record case (~1% wrongful bans).
# ORDER BY RANDOM() keeps successive smoke runs varied — if we always hit the
# same 5 tickets we'd miss prompt drift on the other 45.
FETCH_SQL = """
    SELECT
        t.ticket_id, t.user_name, t.user_id, t.ticket_issue_category,
        t.ticket_title, t.ticket_body,
        b.user_id AS ban_user_id, b.ban_reason, b.detection_method,
        b.ban_duration, b.ban_date
    FROM support_tickets t
    LEFT JOIN ban_database b ON t.user_id = b.user_id
    {where_clause}
    ORDER BY {order_clause}
    LIMIT %s
"""


def fetch_rows(ticket_id: str | None, count: int) -> list[dict]:
    """Return N ticket-plus-optional-ban dicts from Postgres."""
    if not settings.DATABASE_URL:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        sys.exit(1)

    where = "WHERE t.ticket_id = %s" if ticket_id else ""
    order = "t.ticket_id" if ticket_id else "RANDOM()"
    sql = FETCH_SQL.format(where_clause=where, order_clause=order)
    params = (ticket_id, count) if ticket_id else (count,)

    with psycopg2.connect(settings.DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def split_row(row: dict) -> tuple[dict, dict | None]:
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
        "ban_date": str(row["ban_date"]),  # Stringify the date for prompt formatting
    }
    return ticket, ban


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

BAR = "=" * 78
RULE = "-" * 78


def print_case(idx: int, total: int, ticket: dict, ban: dict | None, result: dict | str):
    print(f"\n{BAR}")
    print(f"[{idx}/{total}] {ticket['ticket_id']}  —  user {ticket['user_id']} ({ticket['user_name']})")
    print(BAR)
    print(f"TITLE: {ticket['ticket_title']}")
    body = ticket["ticket_body"].strip()
    preview = body if len(body) <= 300 else body[:300].rstrip() + " ..."
    print(f"BODY:  {preview}")
    print(RULE)
    if ban is None:
        print("BAN:   (no ban record for this user_id)")
    else:
        print(f"BAN:   reason={ban['ban_reason']!r}")
        print(f"       detection_method={ban['detection_method']!r}  "
              f"duration={ban['ban_duration']}  date={ban['ban_date']}")
    print(RULE)
    if isinstance(result, str):  # error string
        print(f"RESULT: ERROR — {result}")
        return
    print(f"CATEGORY:   {result['ai_category']}   (confidence {result['confidence_score']:.2f})")
    print(f"ADMISSIONS: cheating={result['admitted_cheating']}  "
          f"exploit={result['admitted_exploit']}")
    print(f"SUMMARY:    {result['ai_summary']}")
    print(f"REASONING:  {result['ai_reasoning']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5,
                        help="Number of tickets to evaluate (default: 5)")
    parser.add_argument("--ticket-id", default=None,
                        help="Evaluate a specific ticket_id instead of a random sample")
    args = parser.parse_args()

    rows = fetch_rows(args.ticket_id, args.count)
    if not rows:
        print("No tickets returned from the database.", file=sys.stderr)
        return 1

    categories: dict[str, int] = {}
    overrides = 0
    failures = 0

    for idx, row in enumerate(rows, start=1):
        ticket, ban = split_row(row)
        try:
            result = evaluate_ticket(ticket, ban)
        except EvaluationError as e:
            print_case(idx, len(rows), ticket, ban, f"EvaluationError: {e}")
            failures += 1
            continue
        except Exception as e:  # noqa: BLE001
            print_case(idx, len(rows), ticket, ban, f"{type(e).__name__}: {e}")
            failures += 1
            continue

        original_category = result["ai_category"]
        result = enforce_auto_deny(result, ban)
        if result["ai_category"] != original_category:
            overrides += 1

        categories[result["ai_category"]] = categories.get(result["ai_category"], 0) + 1
        print_case(idx, len(rows), ticket, ban, result)

    print(f"\n{BAR}")
    print("SUMMARY")
    print(BAR)
    print(f"Evaluated: {len(rows) - failures}/{len(rows)}  "
          f"(failures: {failures}, auto-deny overrides: {overrides})")
    for cat in sorted(categories):
        print(f"  {cat:28s} {categories[cat]}")
    print()
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
