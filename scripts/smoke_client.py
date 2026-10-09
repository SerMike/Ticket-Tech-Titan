"""Manual smoke test for the LLM client wrapper.

This script intentionally calls a live model API: Anthropic by default, or
whichever LLM_PROVIDER is configured. It is not part of the default pytest
suite because it requires network access, a valid API key, and may incur
API cost (one call of a few dozen tokens).

Run directly:
    python scripts/smoke_client.py
    python scripts/smoke_client.py --provider openai --model gpt-4.1-mini

--provider and --model override LLM_PROVIDER and MODEL_NAME for this run
only; keys, LLM_BASE_URL and LLM_MAX_TOKENS still come from .env. The reply
budget is the pipeline's own, so a reasoning model that passes here has room
to run there too.
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", help="override LLM_PROVIDER (anthropic or openai)")
    parser.add_argument("--model", help="override MODEL_NAME")
    args = parser.parse_args()

    # config.settings reads the environment once, at import, and a real
    # environment variable beats .env — so set these before importing it.
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["MODEL_NAME"] = args.model

    from config import settings
    from evaluation.client import call_model

    target = settings.LLM_PROVIDER
    if settings.LLM_BASE_URL and target != "anthropic":
        target += f" at {settings.LLM_BASE_URL}"
    print(f"Calling {settings.MODEL_NAME} via {target} "
          f"(reply budget {settings.LLM_MAX_TOKENS} tokens)...")

    try:
        response = call_model(
            system="You are a helpful assistant. Reply with a single short sentence.",
            user="Say hello.",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR - {type(exc).__name__}: {exc}")
        return 1

    if not isinstance(response.text, str) or not response.text.strip():
        print("FAIL - response was empty or whitespace only")
        return 1

    print(f"PASS - model responded: {response.text!r}")
    print(
        f"       {response.model_name}: "
        f"{response.input_tokens} in / {response.output_tokens} out tokens"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
