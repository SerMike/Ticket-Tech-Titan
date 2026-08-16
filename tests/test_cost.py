import pytest

from config import settings
from dashboard.cost import cost_usd


def test_cost_usd_prices_a_known_model():
    # 1M in at $3 + 1M out at $15.
    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_cost_usd_prices_a_realistic_evaluation():
    # The measured shape of one ticket: ~2.5k prompt, ~230 completion.
    assert cost_usd("claude-sonnet-4-6", 2221, 231) == pytest.approx(0.010128)


def test_cost_usd_is_linear_over_summed_tokens():
    # get_cost_data() prices whole day/model groups in one call, which is only
    # correct because the arithmetic is linear.
    a = cost_usd("claude-sonnet-4-6", 2221, 231)
    b = cost_usd("claude-sonnet-4-6", 1900, 310)
    assert cost_usd("claude-sonnet-4-6", 4121, 541) == pytest.approx(a + b)


def test_cost_usd_returns_none_for_untracked_input_tokens():
    assert cost_usd("claude-sonnet-4-6", None, 231) is None


def test_cost_usd_returns_none_for_untracked_output_tokens():
    assert cost_usd("claude-sonnet-4-6", 2221, None) is None


def test_cost_usd_returns_none_for_unpriced_model():
    # Tokens are known, the price isn't — the "unknown $" case, distinct from
    # untracked.
    assert cost_usd("some-local-llama", 2221, 231) is None


def test_cost_usd_returns_none_for_missing_model_name():
    assert cost_usd(None, 2221, 231) is None


def test_cost_usd_returns_zero_not_none_for_zero_tokens():
    # A priced evaluation that used no tokens genuinely cost $0. The caller
    # distinguishes this from None, so the types must not collapse.
    result = cost_usd("claude-sonnet-4-6", 0, 0)
    assert result == 0.0
    assert result is not None


def test_cost_usd_reads_the_price_table_at_call_time(monkeypatch):
    # Prices are looked up per call, not captured at import — that's what lets
    # a .env override or a corrected constant re-price history.
    monkeypatch.setitem(settings.MODEL_PRICES, "claude-sonnet-4-6", (6.00, 30.00))

    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == pytest.approx(36.0)
