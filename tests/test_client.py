"""test_client.py — Smoke test for the Anthropic client wrapper.

Sends a tiny "say hello" prompt and asserts a non-empty response. This
verifies the API key, model name, and SDK wiring all work end-to-end.

Run directly:
    python tests/test_client.py
"""

import sys
from pathlib import Path

# Allow running this file directly (python tests/test_client.py) by
# adding the project root to sys.path so `evaluation.client` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.client import call_model


def test_call_model_returns_non_empty_response():
    """Smoke test: send a trivial prompt and assert we get something back."""
    response = call_model(
        system="You are a helpful assistant. Reply with a single short sentence.",
        user="Say hello.",
        max_tokens=64,
    )
    assert isinstance(response, str), f"Expected str, got {type(response)}"
    assert len(response.strip()) > 0, "Response was empty or whitespace only"
    print(f"PASS — model responded: {response!r}")


if __name__ == "__main__":
    try:
        test_call_model_returns_non_empty_response()
    except AssertionError as e:
        print(f"FAIL — {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR — {type(e).__name__}: {e}")
        sys.exit(1)
