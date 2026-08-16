"""cost.py — Dollar cost of an evaluation from its persisted token counts.

Why cost isn't a database column
--------------------------------
Token counts are a fact about the API call; prices are a fact about the day
you ask. Storing dollars would freeze one against the other, so a price
correction would mean re-running the pipeline over the whole corpus to fix
historical numbers. Computing here, at query time, means editing the table in
config/settings.py re-prices all history for free.

Pure arithmetic — no database, no network, no API key. That keeps the money
math testable under the project's offline test contract.
"""

import sys
from pathlib import Path

# Same sys.path shim as db.py, so this resolves whether the importer put the
# project root or dashboard/ on the path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import settings  # noqa: E402

__all__ = ["cost_usd"]


_TOKENS_PER_MILLION = 1_000_000


def cost_usd(
    model_name: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Return the USD cost of an evaluation, or None if it can't be priced.

    None means "we can't say" — never "it was free". The UI must render it as
    untracked or unknown rather than folding it into a total as $0.00. Two
    distinct cases produce it:

      * either token count is None — the evaluation predates token capture,
        so there is nothing to price.
      * the model isn't in settings.MODEL_PRICES — the tokens are known but
        the price isn't (a model someone brought their own key for).

    Zero tokens with a known price is a real 0.0, which is why the distinction
    from None matters.

    The arithmetic is linear, so passing summed tokens for a group of
    evaluations on the same model prices the group correctly. get_cost_data()
    relies on that.

    Args:
        model_name: Model that produced the evaluation, as stored.
        input_tokens: Prompt tokens billed, or None if untracked.
        output_tokens: Completion tokens billed, or None if untracked.

    Returns:
        Cost in USD, unrounded — rounding is the caller's presentation
        decision — or None when the evaluation cannot be priced.
    """
    if input_tokens is None or output_tokens is None:
        return None

    price = settings.MODEL_PRICES.get(model_name)
    if price is None:
        return None

    price_in, price_out = price
    return (input_tokens * price_in + output_tokens * price_out) / _TOKENS_PER_MILLION
