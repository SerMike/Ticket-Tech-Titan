"""writer.py — Persists evaluation results to support_tickets_with_ai.

Thin DB layer. Takes the dict returned by `evaluator.evaluate_ticket()`
(optionally after `auto_deny.enforce_auto_deny()`) and UPSERTs it into
`support_tickets_with_ai`, keying on `ticket_id` so re-evaluations
replace the prior row instead of duplicating it.

The caller owns the connection lifecycle: pass in a psycopg2 connection
and this module will use it. That keeps `run_pipeline.py` in charge of
batching, transactions, and shutdown.
"""

import logging

import psycopg2

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fields the writer expects in eval_result. Mirrors evaluator.evaluate_ticket()'s
# return contract (post-ticket_id/user_id change in commit 9368649).
REQUIRED_FIELDS = (
    "ticket_id",
    "user_id",
    "ai_summary",
    "ai_category",
    "admitted_cheating",
    "admitted_exploit",
    "confidence_score",
    "ai_reasoning",
)


# UPSERT on ticket_id (unique constraint added in the refactor schema commit).
# processed_at is refreshed to NOW() on every write so analysts can tell when
# an evaluation was last (re)generated.
_UPSERT_SQL = """
    INSERT INTO support_tickets_with_ai (
        ticket_id, user_id, ai_summary, ai_category,
        admitted_cheating, admitted_exploit, confidence_score, ai_reasoning,
        processed_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (ticket_id) DO UPDATE SET
        user_id           = EXCLUDED.user_id,
        ai_summary        = EXCLUDED.ai_summary,
        ai_category       = EXCLUDED.ai_category,
        admitted_cheating = EXCLUDED.admitted_cheating,
        admitted_exploit  = EXCLUDED.admitted_exploit,
        confidence_score  = EXCLUDED.confidence_score,
        ai_reasoning      = EXCLUDED.ai_reasoning,
        processed_at      = NOW()
    RETURNING (xmax = 0) AS inserted
"""


class WriterError(Exception):
    """Raised when an evaluation cannot be persisted (missing fields,
    database error, etc.). Callers can catch this to mark a ticket as
    needing re-processing without crashing the whole pipeline."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(eval_result: dict) -> None:
    """Check that all fields the writer needs are present. Fail fast
    rather than letting psycopg2 produce an opaque parameter-count error."""
    missing = [f for f in REQUIRED_FIELDS if f not in eval_result]
    if missing:
        raise WriterError(
            f"eval_result is missing required fields: {missing}. "
            f"Got keys: {sorted(eval_result)}"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_evaluation(conn, eval_result: dict) -> bool:
    """Persist a single evaluation to support_tickets_with_ai.

    Upserts on ticket_id: if a row already exists for this ticket_id the
    existing row is updated in place (re-evaluation) and processed_at is
    refreshed; otherwise a new row is inserted.

    Args:
        conn: An open psycopg2 connection. The caller is responsible for
            commit/rollback — this function does not call conn.commit().
            Transactional boundaries belong to the pipeline runner.
        eval_result: Dict from `evaluator.evaluate_ticket()` (optionally
            post-`auto_deny.enforce_auto_deny()`). Must include all
            fields listed in REQUIRED_FIELDS.

    Returns:
        True if a new row was inserted, False if an existing row was
        updated. Useful for pipeline summary stats.

    Raises:
        WriterError: eval_result is missing fields, or the DB write
            failed. The underlying psycopg2 exception is chained.
    """
    _validate(eval_result)
    ticket_id = eval_result["ticket_id"]

    params = (
        eval_result["ticket_id"],
        eval_result["user_id"],
        eval_result["ai_summary"],
        eval_result["ai_category"],
        eval_result["admitted_cheating"],
        eval_result["admitted_exploit"],
        eval_result["confidence_score"],
        eval_result["ai_reasoning"],
    )

    try:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, params)
            inserted = cur.fetchone()[0]
    except psycopg2.Error as e:
        logger.error(
            "Database write failed for ticket %s: %s", ticket_id, e,
        )
        raise WriterError(
            f"Failed to persist evaluation for ticket {ticket_id}: {e}"
        ) from e

    action = "inserted" if inserted else "updated"
    logger.info(
        "Evaluation %s for ticket %s (category=%s)",
        action, ticket_id, eval_result["ai_category"],
    )
    return bool(inserted)
