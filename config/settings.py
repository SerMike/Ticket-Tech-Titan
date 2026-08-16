"""settings.py — Centralized configuration loaded from .env."""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Load .env from the project root. override=True ensures values in .env
# take precedence over any pre-existing OS env vars (e.g. an empty
# ANTHROPIC_API_KEY left over from a prior shell session).
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-6")

# LLM pricing — USD per million tokens, as (input, output), keyed by model.
#
# Cost is computed from these at query time rather than stored, so correcting a
# price re-prices every historical evaluation without re-running the pipeline.
# A model missing from this table renders as "price unknown" in the cost view,
# never as $0.00.
#
# Verified against Anthropic's published pricing 2026-08-16. Re-check when
# adding a model; nothing in the test suite can catch a stale number here.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Price MODEL_NAME from .env so a model absent from the table above can be
# costed without a code change. Both must be set for the override to apply.
_price_in = os.getenv("PRICE_PER_MTOK_INPUT")
_price_out = os.getenv("PRICE_PER_MTOK_OUTPUT")
if _price_in and _price_out:
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
