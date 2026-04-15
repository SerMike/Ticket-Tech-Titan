"""evaluator.py — Core evaluate_ticket() function.

Glues the prompt builders and the Anthropic client together. Takes a
ticket and (optional) ban record, calls the model, parses the JSON
response, and returns a dict matching the support_tickets_with_ai
schema.
"""

import json
import logging

from .client import call_model
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "Auto-Deny",
    "Likely Legitimate",
    "Admitted to Cheating",
    "Templated/Bot Appeal",
    "Needs Review",
}

REQUIRED_FIELDS = [
    "ai_summary",
    "ai_category",
    "admitted_cheating",
    "admitted_exploit",
    "confidence_score",
    "ai_reasoning",
]


class EvaluationError(Exception):
    """Raised when an evaluation cannot be completed (malformed JSON,
    validation failure, etc.). Callers can catch this to mark a ticket
    as needing manual review without crashing the whole pipeline."""


# ---------------------------------------------------------------------------
# JSON Parsing & Validation
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> dict:
    """Parse the model's raw response as JSON.

    The prompt asks for a bare JSON object (no markdown fences), but we
    defensively strip ```json ... ``` fences if the model adds them anyway.
    """
    # Direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: strip markdown code fences
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop leading ``` or ```json fence
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Drop trailing ``` fence
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        fenced = "\n".join(lines)
        try:
            return json.loads(fenced)
        except json.JSONDecodeError as e:
            raise EvaluationError(
                f"Could not parse model response as JSON even after stripping "
                f"markdown fences: {e}. Raw response:\n{raw!r}"
            )

    raise EvaluationError(
        f"Model response is not valid JSON. Raw response:\n{raw!r}"
    )


def _validate(data: dict) -> None:
    """Check that all required fields are present with correct types/values.
    Raises EvaluationError on any violation."""
    # Presence
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise EvaluationError(f"Missing required fields: {missing}")

    # String fields
    for field in ("ai_summary", "ai_reasoning"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise EvaluationError(f"{field!r} must be a non-empty string")

    # Category — must be one of the five allowed buckets
    if data["ai_category"] not in VALID_CATEGORIES:
        raise EvaluationError(
            f"ai_category {data['ai_category']!r} must be one of "
            f"{sorted(VALID_CATEGORIES)}"
        )

    # Boolean fields — bool is a subclass of int in Python, so isinstance(True, int)
    # is True. Check bool explicitly to avoid letting numbers through.
    for field in ("admitted_cheating", "admitted_exploit"):
        if not isinstance(data[field], bool):
            raise EvaluationError(f"{field!r} must be true or false (got {data[field]!r})")

    # Confidence score — numeric, in [0.0, 1.0]. Exclude bool explicitly.
    score = data["confidence_score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise EvaluationError(f"confidence_score must be a number (got {score!r})")
    if not (0.0 <= float(score) <= 1.0):
        raise EvaluationError(f"confidence_score {score} out of range [0.0, 1.0]")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_ticket(ticket: dict, ban_record: dict | None) -> dict:
    """Evaluate a ticket via the LLM and return a validated result dict.

    Args:
        ticket: Dict matching the support_tickets row shape (must include
            ticket_id, user_name, user_id, ticket_issue_category,
            ticket_title, ticket_body).
        ban_record: Dict matching the ban_database row shape, or None if
            no ban record exists for this user_id (rare — signals a
            potentially wrongful ban; the model is instructed to lean
            toward Likely Legitimate or Needs Review).

    Returns:
        A dict with exactly these six keys, matching the LLM-output fields
        of the support_tickets_with_ai schema:
            ai_summary (str), ai_category (str), admitted_cheating (bool),
            admitted_exploit (bool), confidence_score (float), ai_reasoning (str)
        The caller (writer.py) is responsible for attaching ticket_id/user_id
        before inserting into the database.

    Raises:
        EvaluationError: model returned malformed JSON or failed schema
            validation. The pipeline should log and mark the ticket for
            manual review rather than crash.
        anthropic.APIError (or subclass): the API call itself failed.
    """
    ticket_id = ticket.get("ticket_id", "UNKNOWN")

    # Step 1: Build the user-message body from the ticket + ban record.
    user_prompt = build_user_prompt(ticket, ban_record)

    # Step 2: Call the model. Errors from the API bubble up intentionally.
    raw_response = call_model(
        system=SYSTEM_PROMPT, user=user_prompt, max_tokens=1024
    )

    # Step 3: Parse JSON. Log the raw response on failure for debugging.
    try:
        parsed = _parse_json(raw_response)
    except EvaluationError:
        logger.error(
            "JSON parse failure for ticket %s. Raw response:\n%s",
            ticket_id, raw_response,
        )
        raise

    # Step 4: Validate required fields, types, and value ranges.
    try:
        _validate(parsed)
    except EvaluationError:
        logger.error(
            "Validation failure for ticket %s. Parsed payload:\n%s",
            ticket_id, parsed,
        )
        raise

    # Step 5: Return a clean dict with only the schema fields.
    # Normalize confidence_score to float in case the model returned an int.
    return {
        "ai_summary": parsed["ai_summary"],
        "ai_category": parsed["ai_category"],
        "admitted_cheating": parsed["admitted_cheating"],
        "admitted_exploit": parsed["admitted_exploit"],
        "confidence_score": float(parsed["confidence_score"]),
        "ai_reasoning": parsed["ai_reasoning"],
    }
