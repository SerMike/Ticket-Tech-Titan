"""settings.py — Centralized configuration loaded from .env."""

import os
from pathlib import Path

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
