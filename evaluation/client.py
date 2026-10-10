"""client.py — One entry point for model calls, whichever provider serves them.

call_model() is the only function the rest of the project uses, so retries,
error handling, and model configuration live in one place. It hands each call
to the adapter LLM_PROVIDER selects. Calls return a ModelResponse rather than a
bare string so the token counts the API billed for reach the caller and can be
persisted.

Providers
---------
``anthropic`` (the default) is Claude through the Anthropic SDK, the model the
prompts were tuned against. ``openai`` speaks the OpenAI chat-completions API,
which OpenAI serves and Gemini, Groq and local Ollama models imitate;
LLM_BASE_URL points it at them. An adapter only translates: (system, user,
max_tokens) in, ModelResponse out. The JSON contract and its validation in
evaluator.py are the same whichever model answers.

Retry policy
------------
We disable the SDKs' built-in retries (max_retries=0) and implement our own
loop so that every retry attempt is visibly logged and the backoff schedule
is explicit. Transient failures retry up to MAX_ATTEMPTS times with
exponential backoff + jitter. Permanent failures (auth, bad request) bubble
up immediately — retrying a 400 just wastes quota. Each adapter names which
of its SDK's exceptions count as transient; the loop is shared.
"""

import logging
import random
import time
from dataclasses import dataclass

import anthropic
import openai

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelResponse:
    """Provider-agnostic result of one model call.

    Deliberately carries no SDK types: every adapter normalizes into this same
    shape, so callers never learn which API produced the text.

    Token counts are Optional because not every provider reports usage.
    Downstream, a missing count means "untracked" — never zero.

    Note: input tokens are priced at the full rate downstream. Anthropic's
    usage object also carries cache_creation_input_tokens and
    cache_read_input_tokens, billed at different rates; we don't enable prompt
    caching there, so they're ignored. Some OpenAI-compatible providers
    (OpenAI among them) cache repeated prompt prefixes automatically and bill
    those tokens at a discount, which makes their cost figures an upper bound.
    """

    text: str
    model_name: str
    input_tokens: int | None
    output_tokens: int | None


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


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------

# Both SDKs raise RateLimitError for a 429 and InternalServerError for any 5xx,
# and both time out as APITimeoutError, a subclass of APIConnectionError. Those
# are the transient cases. We intentionally do NOT retry AuthenticationError,
# PermissionDeniedError, BadRequestError, NotFoundError,
# UnprocessableEntityError — those won't get better by waiting.

class AnthropicProvider:
    """Claude through the Anthropic SDK."""

    label = "Anthropic"
    transient_errors = (
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.RateLimitError,
        anthropic.InternalServerError,
    )

    def __init__(self, sdk_client):
        self._client = sdk_client

    @classmethod
    def from_settings(cls):
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file."
            )
        # max_retries=0: we handle retries ourselves so each attempt is logged.
        return cls(anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            max_retries=0,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ))

    def complete(self, system: str, user: str, max_tokens: int) -> ModelResponse:
        response = self._client.messages.create(
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

        # settings.MODEL_NAME, not response.model: the API echoes a resolved
        # snapshot id (claude-sonnet-4-6-20260114) that matches nothing in a
        # price table keyed on the alias we configured.
        return ModelResponse(
            text="".join(text_parts),
            model_name=settings.MODEL_NAME,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class OpenAICompatProvider:
    """Any endpoint that speaks the OpenAI chat-completions API: OpenAI by
    default, or Gemini, Groq or a local Ollama through LLM_BASE_URL."""

    label = "OpenAI-compatible"
    transient_errors = (
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.RateLimitError,
        openai.InternalServerError,
    )

    def __init__(self, sdk_client):
        self._client = sdk_client

    @classmethod
    def from_settings(cls):
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set, and LLM_PROVIDER=openai needs it. "
                "Add your provider's key to your .env file "
                "(for a local Ollama any placeholder value works)."
            )
        if not settings.MODEL_NAME:
            raise RuntimeError(
                "MODEL_NAME is not set. LLM_PROVIDER=openai has no default "
                "model; set it to one your endpoint serves."
            )
        # base_url None means api.openai.com. max_retries=0 as above.
        return cls(openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL,
            max_retries=0,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ))

    def complete(self, system: str, user: str, max_tokens: int) -> ModelResponse:
        response = self._client.chat.completions.create(
            model=settings.MODEL_NAME,
            # No separate system parameter here: it's the first message.
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Not max_tokens, which OpenAI's reasoning models reject. Those
            # models also spend this budget on hidden reasoning, so a reply
            # that runs out comes back empty with finish_reason "length".
            # LLM_MAX_TOKENS sets the budget.
            max_completion_tokens=max_tokens,
        )

        choice = response.choices[0] if response.choices else None
        text = choice.message.content if choice and choice.message else None
        if not text:
            reason = choice.finish_reason if choice else None
            hint = (
                f" — the model used its whole {max_tokens}-token budget, which"
                " reasoning models can spend on hidden reasoning; raise"
                " LLM_MAX_TOKENS or try a non-reasoning model"
                if reason == "length" else ""
            )
            raise RuntimeError(
                f"OpenAI-compatible API returned no text content. Finish reason: {reason}{hint}"
            )

        # Same alias rule as Anthropic: the echoed response.model is often a
        # dated snapshot. usage is optional on some servers; None stays None.
        usage = response.usage
        return ModelResponse(
            text=text,
            model_name=settings.MODEL_NAME,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )


_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAICompatProvider,
}

# Module-level cache so we only construct one SDK client per process.
_provider = None


def get_provider():
    """Return the (cached) adapter for LLM_PROVIDER.

    Raises RuntimeError, naming the fix, if the provider is unknown or its key
    or model isn't configured, so callers can fail before doing any work.
    """
    global _provider
    if _provider is None:
        provider_cls = _PROVIDERS.get(settings.LLM_PROVIDER)
        if provider_cls is None:
            raise RuntimeError(
                f"LLM_PROVIDER={settings.LLM_PROVIDER!r} is not supported. "
                f"Use one of: {', '.join(_PROVIDERS)}."
            )
        _provider = provider_cls.from_settings()
    return _provider


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter.

    attempt is 1-indexed. For attempt=1 (the first retry) the delay is
    roughly INITIAL_BACKOFF_SECONDS; each subsequent retry doubles the
    ceiling, capped at MAX_BACKOFF_SECONDS. Jitter prevents synchronized
    retries when multiple workers hit the same rate limit.
    """
    ceiling = min(MAX_BACKOFF_SECONDS, INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    return random.uniform(0.0, ceiling)


def call_model(system: str, user: str, max_tokens: int | None = None) -> ModelResponse:
    """Send a single (system, user) message pair to the configured model.

    Retries transient failures (rate limits, 5xx, network timeouts) with
    exponential backoff + jitter, up to MAX_ATTEMPTS total attempts.
    Permanent failures (auth, bad request) are raised on the first try.

    Args:
        system: System prompt defining the model's role and rules.
        user: User-message body — the actual prompt to evaluate.
        max_tokens: Cap on the reply, hidden reasoning included for models
            that reason. Defaults to LLM_MAX_TOKENS (1024 unless configured),
            plenty for our JSON output from a non-reasoning model.

    Returns:
        A ModelResponse carrying the raw text content plus the token counts
        the API billed for, so callers can cost the call.

    Raises:
        RuntimeError if the provider isn't configured (see get_provider) or
        the model returns an empty response.
        The provider SDK's APIError (anthropic.APIError or openai.APIError,
        or a subclass) if all retries are exhausted or a non-transient error
        occurs. We deliberately do NOT swallow the error; callers can wrap
        this call in their own try/except.
    """
    provider = get_provider()
    if max_tokens is None:
        max_tokens = settings.LLM_MAX_TOKENS

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return provider.complete(system, user, max_tokens)
        except provider.transient_errors as e:
            if attempt == MAX_ATTEMPTS:
                logger.error(
                    "%s API call failed after %d attempts: %s: %s",
                    provider.label, MAX_ATTEMPTS, type(e).__name__, e,
                )
                raise
            delay = _backoff_seconds(attempt)
            logger.warning(
                "%s API transient error on attempt %d/%d (%s: %s). "
                "Retrying in %.2fs...",
                provider.label, attempt, MAX_ATTEMPTS, type(e).__name__, e, delay,
            )
            time.sleep(delay)

    # Unreachable: every pass through the loop returns or raises. Kept so a
    # future edit can't silently turn exhausted retries into a None result.
    raise RuntimeError("call_model exhausted retries without success.")
