"""Manual smoke test for the Anthropic client wrapper.

This script intentionally calls the live Anthropic API. It is not part
of the default pytest suite because it requires network access, a valid
ANTHROPIC_API_KEY, and may incur API cost.

Run directly:
    python scripts/smoke_client.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.client import call_model


def main() -> int:
    try:
        response = call_model(
            system="You are a helpful assistant. Reply with a single short sentence.",
            user="Say hello.",
            max_tokens=64,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR - {type(exc).__name__}: {exc}")
        return 1

    if not isinstance(response, str) or not response.strip():
        print("FAIL - response was empty or whitespace only")
        return 1

    print(f"PASS - model responded: {response!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
