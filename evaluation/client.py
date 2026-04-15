"""client.py — Thin wrapper around the Anthropic SDK.

Provides a single entry point for making Claude API calls so that
retries, error handling, and model configuration live in one place.

Retry policy
------------
We disable the Anthropic SDK's built-in retries (max_retries=0) and
implement our own loop so that every retry attempt is visibly logged
and the backoff schedule is explicit. Transient failures retry up to
MAX_ATTEMPTS times with exponential backoff + jitter. Permanent
failures (auth, bad request) bubble up immediately — retrying a 400
just wastes quota.
"""

import logging
import random
import time

import anthropic

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

# Total attempts = 1 initial + (MAX_ATTEMPTS - 1) retries.
# Default 5 means worst-case delays of 1 + 2 + 4 + 8 = 15s across 4 retries
# (before jitter), which is usually enough to ride out a short rate-limit
# burst without making the pipeline wait forever.
MAX_ATTEMPTS = 5
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0

# Per-request HTTP timeout. Ticket evaluations are small, so anything over
# a couple of minutes almost certainly means a stuck connection.
REQUEST_TIMEOUT_SECONDS = 120.0

# Exceptions that indicate a transient problem worth retrying.
# APIStatusError covers 5xx (server errors). We intentionally do NOT
# retry AuthenticationError, PermissionDeniedError, BadRequestError,
# NotFoundError, UnprocessableEntityError — those won't get better by
# waiting.
_TRANSIENT_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


# Module-level client cache so we only construct one Anthropic() per process.
_client = None


def get_client():
    """Return a (cached) initialized Anthropic client.
    Raises RuntimeError if ANTHROPIC_API_KEY is missing from .env.
    """
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file."
            )
        # max_retries=0: we handle retries ourselves so each attempt is logged.
        _client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            max_retries=0,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    return _client


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter.

    attempt is 1-indexed. For attempt=1 (the first retry) the delay is
    roughly INITIAL_BACKOFF_SECONDS; each subsequent retry doubles the
    ceiling, capped at MAX_BACKOFF_SECONDS. Jitter prevents synchronized
    retries when multiple workers hit the same rate limit.
    """
    ceiling = min(MAX_BACKOFF_SECONDS, INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    return random.uniform(0.0, ceiling)


def call_model(system: str, user: str, max_tokens: int = 1024) -> str:
    """Send a single (system, user) message pair to the model and return text.

    Retries transient failures (rate limits, 5xx, network timeouts) with
    exponential backoff + jitter, up to MAX_ATTEMPTS total attempts.
    Permanent failures (auth, bad request) are raised on the first try.

    Args:
        system: System prompt defining the model's role and rules.
        user: User-message body — the actual prompt to evaluate.
        max_tokens: Cap on response length. 1024 is plenty for our JSON output.

    Returns:
        The raw text content of the model's response.

    Raises:
        anthropic.APIError (or subclass) if all retries are exhausted or a
        non-transient error occurs. We deliberately do NOT swallow the
        error; callers can wrap this call in their own try/except.
        RuntimeError if the model returns an empty response.
    """
    client = get_client()
    last_exc: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model=settings.MODEL_NAME,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            break  # success — drop out of the retry loop
        except _TRANSIENT_EXCEPTIONS as e:
            last_exc = e
            if attempt == MAX_ATTEMPTS:
                logger.error(
                    "Anthropic API call failed after %d attempts: %s: %s",
                    MAX_ATTEMPTS, type(e).__name__, e,
                )
                raise
            delay = _backoff_seconds(attempt)
            logger.warning(
                "Anthropic API transient error on attempt %d/%d (%s: %s). "
                "Retrying in %.2fs...",
                attempt, MAX_ATTEMPTS, type(e).__name__, e, delay,
            )
            time.sleep(delay)
    else:
        # The for/else runs if the loop completed without `break` — should
        # be unreachable because we raise on the final attempt, but guard
        # against future edits silently swallowing failures.
        raise RuntimeError(
            f"call_model exhausted retries without success. Last error: {last_exc}"
        )

    # The SDK returns a list of content blocks; for a plain text response
    # there will be one TextBlock. Concatenate text from all text blocks
    # to be safe in case the model returns multiple.
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise RuntimeError(
            f"Anthropic API returned no text content. Stop reason: {response.stop_reason}"
        )

    return "".join(text_parts)
