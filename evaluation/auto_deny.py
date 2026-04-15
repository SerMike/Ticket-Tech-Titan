"""auto_deny.py — Post-evaluation enforcement of the auto-deny rule.

The system prompt already instructs the model to assign `Auto-Deny` when
the ban record shows a confirmed, high-confidence detection. This module
is a safety net: if the model wavers and returns some other bucket for a
ticket whose ban has a confirmed detection_method, we override to
`Auto-Deny` and note the override in `ai_reasoning`.

Exception: if the model returned `Admitted to Cheating`, we leave it
alone. An explicit admission is tracked separately for analytics and is
already an effective denial of the appeal (see SYSTEM_PROMPT's auto-deny
rule).
"""

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Confirmed detection methods
# ---------------------------------------------------------------------------
# These are the hard-signal detection methods used in the ban database.
# A ban carrying any of these is considered high-confidence technical
# evidence and must trigger Auto-Deny regardless of what the player claims.
#
# Softer signals intentionally excluded:
#   - stat_anomaly          (statistical, not deterministic)
#   - manual_review         (human judgment call, not a catch)
#   - new_detection_method  (unvetted — route to human review)

CONFIRMED_DETECTION_METHODS = frozenset({
    "cheat_engine_detection",
    "aim_lock_detection",
    "speed_hack",
    "connection_manipulation",
})


# Buckets we will NOT override. `Admitted to Cheating` wins because the
# player's own admission is a stronger signal than the detection method
# and is tracked separately for the data-science team.
_PROTECTED_CATEGORIES = frozenset({"Auto-Deny", "Admitted to Cheating"})


# ---------------------------------------------------------------------------
# Override logic
# ---------------------------------------------------------------------------

def enforce_auto_deny(eval_result: dict, ban_record: dict | None) -> dict:
    """Apply the auto-deny safety net to a model evaluation.

    If the ban record's `detection_method` is in CONFIRMED_DETECTION_METHODS
    and the model's `ai_category` is not already `Auto-Deny` or
    `Admitted to Cheating`, override the category to `Auto-Deny` and append
    a note to `ai_reasoning` explaining the override.

    Mutates and returns the same dict for convenience.

    Args:
        eval_result: The dict returned by `evaluator.evaluate_ticket()`.
        ban_record: The ban record dict (or None if no ban exists).

    Returns:
        The (possibly modified) eval_result dict.
    """
    if ban_record is None:
        return eval_result

    detection_method = ban_record.get("detection_method")
    if detection_method not in CONFIRMED_DETECTION_METHODS:
        return eval_result

    original_category = eval_result.get("ai_category")
    if original_category in _PROTECTED_CATEGORIES:
        return eval_result

    # Override.
    ticket_id = eval_result.get("ticket_id", "UNKNOWN")
    logger.warning(
        "Auto-deny override for ticket %s: model returned %r but "
        "detection_method=%r is a confirmed high-signal catch. "
        "Overriding to Auto-Deny.",
        ticket_id, original_category, detection_method,
    )

    override_note = (
        f" [AUTO-DENY OVERRIDE: original model category was "
        f"{original_category!r}, but detection_method={detection_method!r} "
        f"is a confirmed high-signal catch per the auto-deny rule.]"
    )

    eval_result["ai_category"] = "Auto-Deny"
    eval_result["ai_reasoning"] = eval_result.get("ai_reasoning", "") + override_note
    return eval_result
