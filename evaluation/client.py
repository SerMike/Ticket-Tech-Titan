"""client.py — Thin wrapper around the Anthropic SDK.

Provides a single entry point for making Claude API calls so that
retries, error handling, and model configuration live in one place.
"""

import anthropic

from config import settings

# Module-level client cache so we only construct one Anthropic() per process
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
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def call_model(system: str, user: str, max_tokens: int = 1024) -> str:
    """Send a single (system, user) message pair to the model and return text.

    Args:
        system: System prompt defining the model's role and rules.
        user: User-message body — the actual prompt to evaluate.
        max_tokens: Cap on response length. 1024 is plenty for our JSON output.

    Returns:
        The raw text content of the model's response.

    Raises:
        anthropic.APIError (or subclass) if the API call fails. We deliberately
        do NOT swallow the error so callers can decide how to retry/log.
    """
    client = get_client()

    response = client.messages.create(
        model=settings.MODEL_NAME,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
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
