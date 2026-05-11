"""db.py — Database access layer for the Streamlit dashboard.

All dashboard SQL queries live here so pages stay UI-only. The
connection itself is NOT duplicated — this module re-exports the
shared ``get_connection`` from ``config.settings`` so the dashboard
and the ingestion pipeline share one source of truth for DB config.

Read queries open an autocommit connection, return plain Python
dicts, and close the connection before returning. ``update_ticket_status``
is the only write path and runs in a single transaction so the
support_tickets row and the ticket_status_history insert can't fall
out of sync.
"""

import sys
from datetime import date as _date
from pathlib import Path
from typing import Any

# When launched via `streamlit run dashboard/app.py`, sys.path includes
# the ``dashboard/`` folder but not the project root. Insert the project
# root so ``from config.settings import ...`` resolves for every page.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from psycopg2.extras import RealDictCursor  # noqa: E402

from config.settings import ALLOWED_STATUSES, get_connection  # noqa: E402

__all__ = [
    "ALLOWED_STATUSES",
    "get_connection",
    "get_all_tickets",
    "get_ticket_detail",
    "get_ai_evaluation",
    "update_ticket_status",
    "get_analytics_data",
    "get_summary_stats",
    "get_ticket_date_bounds",
]


# ---------------------------------------------------------------------------
# Shared SELECT for the queue/detail views
# ---------------------------------------------------------------------------

# Left-joined because (a) tickets may not have an AI evaluation yet and
# (b) ~1% of tickets legitimately have no matching ban record (potential
# wrongful ban). Inner joins would hide both cases from the queue.
_QUEUE_SELECT = """
    SELECT
        st.ticket_id,
        st.user_name,
        st.user_id,
        st.ticket_issue_category,
        st.ticket_title,
        st.ticket_body,
        st.status,
        st.created_at,
        ai.ai_category,
        ai.confidence_score,
        ai.admitted_cheating,
        ai.admitted_exploit,
        ai.processed_at,
        bd.ban_reason,
        bd.detection_method,
        bd.ban_duration,
        bd.ban_date
    FROM support_tickets st
    LEFT JOIN support_tickets_with_ai ai ON ai.ticket_id = st.ticket_id
    LEFT JOIN ban_database bd            ON bd.user_id   = st.user_id
"""


# ---------------------------------------------------------------------------
# Read queries
# ---------------------------------------------------------------------------

def get_all_tickets() -> list[dict[str, Any]]:
    """Return every ticket joined with its AI evaluation and ban record.

    Ordered newest-first so the default queue view shows the most
    recent submissions at the top. Tickets without an AI evaluation
    or without a ban record still appear; the corresponding columns
    come back as None.
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_QUEUE_SELECT + " ORDER BY st.created_at DESC")
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_ticket_detail(ticket_id: str) -> dict[str, Any] | None:
    """Return the full joined row for one ticket, or None if missing."""
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_QUEUE_SELECT + " WHERE st.ticket_id = %s", (ticket_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_ai_evaluation(ticket_id: str) -> dict[str, Any] | None:
    """Return just the AI evaluation fields for a ticket.

    Returns None if the ticket hasn't been evaluated yet — the detail
    view uses that signal to show a "Not yet evaluated" placeholder
    instead of empty cells.
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ai_summary, ai_reasoning, ai_category,
                       confidence_score, admitted_cheating, admitted_exploit
                FROM support_tickets_with_ai
                WHERE ticket_id = %s
                """,
                (ticket_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Write path — the only mutation the dashboard performs
# ---------------------------------------------------------------------------

def update_ticket_status(ticket_id: str, new_status: str) -> str:
    """Change a ticket's status and log the transition.

    Validates ``new_status`` against ``ALLOWED_STATUSES`` to fail fast
    before hitting the DB's CHECK constraint. The UPDATE on
    ``support_tickets`` and the INSERT into ``ticket_status_history``
    run inside a single transaction (``with conn:``) so a crash
    between the two can't leave the history table out of sync with
    the ticket row.

    Returns the previous status, which the UI uses for a toast like
    "open → pending". Raises ValueError if the status is unknown or
    the ticket doesn't exist.
    """
    if new_status not in ALLOWED_STATUSES:
        raise ValueError(
            f"Invalid status {new_status!r}. Allowed: {ALLOWED_STATUSES}"
        )

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM support_tickets WHERE ticket_id = %s",
                    (ticket_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"Ticket {ticket_id!r} not found")
                old_status = row[0]

                if old_status == new_status:
                    return old_status

                cur.execute(
                    "UPDATE support_tickets SET status = %s WHERE ticket_id = %s",
                    (new_status, ticket_id),
                )
                cur.execute(
                    """
                    INSERT INTO ticket_status_history
                        (ticket_id, old_status, new_status)
                    VALUES (%s, %s, %s)
                    """,
                    (ticket_id, old_status, new_status),
                )
        return old_status
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Landing-page summary
# ---------------------------------------------------------------------------

def get_summary_stats() -> dict[str, int]:
    """Return the three top-of-dashboard counts.

    ``open_count``: tickets currently in the queue (status = 'open').
    ``auto_denied_today``: evaluations processed today that the AI (or
        the auto-deny override) categorized as 'Auto-Deny'. Uses
        processed_at in the server's timezone, matching how analysts
        think about "today's work".
    ``needs_review``: open tickets the AI explicitly flagged as
        'Needs Review' — the bucket the AI can't decide on and
        actively wants a human to look at.
    """
    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE status = 'open'"
            )
            open_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM support_tickets_with_ai
                WHERE ai_category = 'Auto-Deny'
                  AND DATE(processed_at) = CURRENT_DATE
                """
            )
            auto_denied_today = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM support_tickets st
                JOIN support_tickets_with_ai ai ON ai.ticket_id = st.ticket_id
                WHERE st.status = 'open'
                  AND ai.ai_category = 'Needs Review'
                """
            )
            needs_review = cur.fetchone()[0]

        return {
            "open_count": open_count,
            "auto_denied_today": auto_denied_today,
            "needs_review": needs_review,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analytics aggregates
# ---------------------------------------------------------------------------

def get_analytics_data(
    date_from: _date | None = None,
    date_to: _date | None = None,
) -> dict[str, Any]:
    """Return the aggregate counts the analytics page needs.

    All queries filter by ``support_tickets.created_at`` (submission
    date). Pass ``date_from`` / ``date_to`` to scope results to a
    window; omit both to get all-time aggregates (defaults to a very
    wide sentinel range so every query stays parameterized uniformly).

    ``category_breakdown``: list of {ai_category, count}, descending.
    ``admission_rates``: {admitted_cheating, admitted_exploit, total}
        where total is evaluated tickets in the window.
    ``detection_method_counts``: list of {detection_method, count}
        for tickets that have a matching ban record.
    ``volume_over_time``: list of {date, count} per calendar day.
    ``confidence_scores``: list of floats for evaluated tickets.
    """
    if date_from is None:
        date_from = _date(2000, 1, 1)
    if date_to is None:
        date_to = _date(2099, 12, 31)
    dp = (date_from, date_to)

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ai.ai_category, COUNT(*) AS count
                FROM support_tickets_with_ai ai
                JOIN support_tickets st ON st.ticket_id = ai.ticket_id
                WHERE ai.ai_category IS NOT NULL
                  AND st.created_at::date BETWEEN %s AND %s
                GROUP BY ai.ai_category
                ORDER BY count DESC
                """,
                dp,
            )
            category_breakdown = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE ai.admitted_cheating) AS admitted_cheating,
                    COUNT(*) FILTER (WHERE ai.admitted_exploit)  AS admitted_exploit,
                    COUNT(*)                                      AS total
                FROM support_tickets_with_ai ai
                JOIN support_tickets st ON st.ticket_id = ai.ticket_id
                WHERE st.created_at::date BETWEEN %s AND %s
                """,
                dp,
            )
            admission_rates = dict(cur.fetchone())

            cur.execute(
                """
                SELECT bd.detection_method, COUNT(*) AS count
                FROM support_tickets st
                JOIN ban_database bd ON bd.user_id = st.user_id
                WHERE st.created_at::date BETWEEN %s AND %s
                GROUP BY bd.detection_method
                ORDER BY count DESC
                """,
                dp,
            )
            detection_method_counts = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT DATE(created_at) AS date, COUNT(*) AS count
                FROM support_tickets
                WHERE created_at::date BETWEEN %s AND %s
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at)
                """,
                dp,
            )
            volume_over_time = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT ai.confidence_score
                FROM support_tickets_with_ai ai
                JOIN support_tickets st ON st.ticket_id = ai.ticket_id
                WHERE ai.confidence_score IS NOT NULL
                  AND st.created_at::date BETWEEN %s AND %s
                """,
                dp,
            )
            confidence_scores = [float(r["confidence_score"]) for r in cur.fetchall()]

        return {
            "category_breakdown": category_breakdown,
            "admission_rates": admission_rates,
            "detection_method_counts": detection_method_counts,
            "volume_over_time": volume_over_time,
            "confidence_scores": confidence_scores,
        }
    finally:
        conn.close()


def get_ticket_date_bounds() -> tuple[_date, _date]:
    """Return the earliest and latest ticket submission dates.

    Used to initialise the analytics date-range picker. Falls back to
    a 90-day window ending today if the table is empty.
    """
    from datetime import timedelta

    conn = get_connection(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(created_at::date), MAX(created_at::date) FROM support_tickets"
            )
            row = cur.fetchone()
        if row and row[0]:
            return row[0], row[1]
        today = _date.today()
        return today - timedelta(days=90), today
    finally:
        conn.close()
