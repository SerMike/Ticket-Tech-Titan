"""settings.py — Centralized configuration loaded from .env."""

import os
from pathlib import Path

import psycopg2
from dotenv import dotenv_values, load_dotenv

# Load .env from the project root. Real environment variables win, so
# `DATABASE_URL=... python database/init_db.py` points the whole project at
# that database — see "Pointing at a non-default database" in the README.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

# One exception: a variable exported as an empty string (classically an
# ANTHROPIC_API_KEY left over from a prior shell session) still shadows .env
# above, because python-dotenv only tests for presence. An empty value is
# never a deliberate choice, so let .env fill it in.
for _key, _value in dotenv_values(_ENV_PATH).items():
    if _value and not os.environ.get(_key):
        os.environ[_key] = _value

# Database
DATABASE_URL = os.getenv("DATABASE_URL")


def _llm_choice(provider: str | None, model: str | None) -> tuple[str, str | None]:
    """Resolve LLM_PROVIDER and MODEL_NAME from their raw environment values.

    Unset means Anthropic with its default model, so an existing .env keeps
    working unchanged. Other providers get no default model: the right name
    depends on whose endpoint it is, so evaluation/client.py asks for one.
    """
    provider = (provider or "anthropic").strip().lower()
    if not model and provider == "anthropic":
        model = "claude-sonnet-4-6"
    return provider, model or None


# LLM provider: "anthropic" (default) or "openai". The latter speaks the OpenAI
# chat-completions API, which OpenAI serves and Gemini, Groq and local Ollama
# models imitate; LLM_BASE_URL points it at them. See "Using other models" in
# the README.
LLM_PROVIDER, MODEL_NAME = _llm_choice(os.getenv("LLM_PROVIDER"), os.getenv("MODEL_NAME"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# Whatever key the OpenAI-compatible endpoint expects: an OpenAI, Gemini or
# Groq key. Ollama ignores it, but the SDK still wants a non-empty value.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None


def _token_budget(raw: str | None) -> int:
    """Parse LLM_MAX_TOKENS: a positive whole number, 1024 when unset.

    A bad value fails here, naming the variable, rather than as a provider
    error on every ticket.
    """
    if not raw:
        return 1024
    try:
        budget = int(raw)
    except ValueError:
        budget = 0
    if budget < 1:
        raise RuntimeError(
            f"LLM_MAX_TOKENS must be a positive whole number of tokens, got {raw!r}."
        )
    return budget


# Token budget for each model reply. 1024 is ample for the evaluation JSON,
# but reasoning models spend part of the budget on hidden reasoning before
# they answer, so they need more; see "Using other models" in the README.
LLM_MAX_TOKENS = _token_budget(os.getenv("LLM_MAX_TOKENS"))

# LLM pricing — USD per million tokens, as (input, output), keyed by model.
#
# Cost is computed from these at query time rather than stored, so correcting a
# price re-prices every historical evaluation without re-running the pipeline.
# A model missing from this table renders as "price unknown" in the cost view,
# never as $0.00.
#
# Verified against Anthropic's published pricing 2026-10-10. Re-check when
# adding a model; nothing in the test suite can catch a stale number here.
# Models reached through LLM_PROVIDER=openai aren't listed until someone
# verifies their prices the same way; until then, price yours with the
# PRICE_PER_MTOK_* override below.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # Haiku 5.5 bills prompts over 100K tokens at 5x these rates. A ticket
    # evaluation sends about 3K, so this rate is the one that applies.
    "claude-haiku-5-5": (0.10, 0.50),
}

# Price MODEL_NAME from .env so a model absent from the table above can be
# costed without a code change. Both must be set for the override to apply.
_price_in = os.getenv("PRICE_PER_MTOK_INPUT")
_price_out = os.getenv("PRICE_PER_MTOK_OUTPUT")
if _price_in and _price_out and MODEL_NAME:
    MODEL_PRICES[MODEL_NAME] = (float(_price_in), float(_price_out))

# Allowed values for support_tickets.status. Mirrors the CHECK constraint
# in database/schema.sql so Python-side dropdowns can't drift from the DB.
ALLOWED_STATUSES = ("open", "pending", "closed")


def get_connection(autocommit: bool = False):
    """Open a psycopg2 connection using DATABASE_URL.

    Raises RuntimeError if DATABASE_URL is unset or the connection fails,
    so callers (CLI, API) can decide how to surface the error
    instead of sys.exiting the process.

    Args:
        autocommit: If True, set conn.autocommit = True. Used by the
            ingestion CLI, which treats each insert as its own unit of
            work. Transactional callers (evaluation writer, dashboard
            status updates) should leave this False and manage commits.

    Returns:
        An open psycopg2 connection. Caller owns cursor + close().
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env file."
        )
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as e:
        raise RuntimeError(f"Could not connect to database: {e}") from e
    if autocommit:
        conn.autocommit = True
    return conn
