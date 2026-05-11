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

# Allowed values for support_tickets.status. Mirrors the CHECK constraint
# in database/schema.sql so Python-side dropdowns can't drift from the DB.
ALLOWED_STATUSES = ("open", "pending", "closed")


def get_connection(autocommit: bool = False):
    """Open a psycopg2 connection using DATABASE_URL.

    Raises RuntimeError if DATABASE_URL is unset or the connection fails,
    so callers (CLI, Streamlit) can decide how to surface the error
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
