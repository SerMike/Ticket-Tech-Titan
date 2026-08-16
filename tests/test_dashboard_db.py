from datetime import date, timedelta
from unittest.mock import MagicMock, Mock

import pytest

from dashboard import db


def _mock_conn(monkeypatch):
    """Patch db.get_connection to return a MagicMock connection and
    return (conn, cursor) where cursor is what `with conn.cursor()` yields."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(db, "get_connection", Mock(return_value=conn))
    return conn, cur


def test_get_all_tickets_returns_list_of_dicts(monkeypatch):
    conn, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = [
        {"ticket_id": "TKT-1", "ai_category": "Auto-Deny", "status": "open"},
        {"ticket_id": "TKT-2", "ai_category": None, "status": "closed"},
    ]

    tickets = db.get_all_tickets()

    assert tickets == [
        {"ticket_id": "TKT-1", "ai_category": "Auto-Deny", "status": "open"},
        {"ticket_id": "TKT-2", "ai_category": None, "status": "closed"},
    ]
    conn.close.assert_called_once()


def test_get_ticket_detail_returns_single_row(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = {"ticket_id": "TKT-1", "status": "open"}

    detail = db.get_ticket_detail("TKT-1")

    assert detail == {"ticket_id": "TKT-1", "status": "open"}
    _, params = cur.execute.call_args.args
    assert params == ("TKT-1",)


def test_get_ticket_detail_returns_none_when_not_found(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = None

    assert db.get_ticket_detail("TKT-MISSING") is None


def test_get_ai_evaluation_returns_ai_fields(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = {
        "ai_summary": "Summary",
        "ai_reasoning": "Reasoning",
        "ai_category": "Needs Review",
        "confidence_score": 0.7,
        "admitted_cheating": False,
        "admitted_exploit": True,
    }

    result = db.get_ai_evaluation("TKT-1")

    for key in ("ai_summary", "ai_reasoning", "confidence_score",
                "admitted_cheating", "admitted_exploit"):
        assert key in result


def test_update_ticket_status_rejects_invalid_status(monkeypatch):
    fake_get_connection = Mock()
    monkeypatch.setattr(db, "get_connection", fake_get_connection)

    with pytest.raises(ValueError, match="Invalid status"):
        db.update_ticket_status("TKT-1", "invalid")

    fake_get_connection.assert_not_called()


def test_update_ticket_status_commits_transaction_on_success(monkeypatch):
    # The UPDATE + history INSERT run inside `with conn:`, which commits on
    # a clean exit — assert the transaction context closed without error.
    conn, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = ("open",)

    old_status = db.update_ticket_status("TKT-1", "pending")

    assert old_status == "open"
    conn.__exit__.assert_called_once_with(None, None, None)
    conn.close.assert_called_once()


def test_update_ticket_status_inserts_history_row(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = ("open",)

    db.update_ticket_status("TKT-1", "closed")

    # SELECT old status, UPDATE ticket, INSERT history.
    assert cur.execute.call_count == 3
    history_sql, history_params = cur.execute.call_args_list[2].args
    assert "INSERT INTO ticket_status_history" in history_sql
    assert history_params == ("TKT-1", "open", "closed")


def test_get_analytics_data_returns_expected_keys(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.side_effect = [
        [{"ai_category": "Auto-Deny", "count": 5}],          # category_breakdown
        [{"detection_method": "cheat_engine", "count": 3}],  # detection_method_counts
        [{"date": date(2026, 5, 1), "count": 4}],            # volume_over_time
        [{"confidence_score": 0.9}, {"confidence_score": 0.4}],  # confidence_scores
    ]
    cur.fetchone.return_value = {
        "admitted_cheating": 2, "admitted_exploit": 1, "total": 10,
    }

    data = db.get_analytics_data()

    assert set(data) == {
        "category_breakdown",
        "admission_rates",
        "detection_method_counts",
        "volume_over_time",
        "confidence_scores",
    }
    assert data["admission_rates"]["total"] == 10
    assert data["confidence_scores"] == [0.9, 0.4]


# ---- Costs ----

def _cost_group(day, model="claude-sonnet-4-6", evaluations=1, tracked=1,
                input_tokens=1_000_000, output_tokens=1_000_000):
    """One (date, model) row as get_cost_data's query returns it."""
    return {
        "date": day,
        "model_name": model,
        "evaluations": evaluations,
        "tracked": tracked,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def test_get_cost_data_returns_expected_keys(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = [_cost_group(date(2026, 5, 1))]

    data = db.get_cost_data()

    assert set(data) == {"by_day", "by_model", "totals"}
    # 1M in at $3 + 1M out at $15.
    assert data["totals"]["cost_usd"] == pytest.approx(18.0)


def test_get_cost_data_defaults_to_a_sentinel_date_range(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = []

    db.get_cost_data()

    _, params = cur.execute.call_args.args
    assert params == (date(2000, 1, 1), date(2099, 12, 31))


def test_get_cost_data_scopes_the_query_to_the_date_window(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = []

    db.get_cost_data(date(2026, 5, 1), date(2026, 5, 31))

    sql, params = cur.execute.call_args.args
    assert "st.created_at::date BETWEEN %s AND %s" in sql
    assert params == (date(2026, 5, 1), date(2026, 5, 31))


def test_get_cost_data_merges_models_within_one_day(monkeypatch):
    # Two models on the same day are two query rows but one calendar day, and
    # each is priced at its own rate.
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = [
        _cost_group(date(2026, 5, 1), model="claude-sonnet-4-6"),   # $18
        _cost_group(date(2026, 5, 1), model="claude-haiku-4-5"),    # $6
    ]

    data = db.get_cost_data()

    assert len(data["by_day"]) == 1
    assert data["by_day"][0]["cost_usd"] == pytest.approx(24.0)
    assert len(data["by_model"]) == 2


def test_get_cost_data_counts_untracked_rows_without_pricing_them(monkeypatch):
    # Pre-migration evaluations: counted, but they contribute no dollars and
    # must not drag the per-ticket average down.
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = [
        _cost_group(date(2026, 5, 1), evaluations=5, tracked=1),
        _cost_group(date(2026, 5, 1), model=None, evaluations=4, tracked=0,
                    input_tokens=0, output_tokens=0),
    ]

    data = db.get_cost_data()
    totals = data["totals"]

    assert totals["evaluations"] == 9
    assert totals["tracked"] == 1
    assert totals["untracked"] == 8
    assert totals["cost_usd"] == pytest.approx(18.0)
    assert totals["avg_cost_per_ticket_usd"] == pytest.approx(18.0)

    # The all-untracked model row reports no cost at all — $0.00 there would
    # read as "these four evaluations were free".
    untracked_row = next(m for m in data["by_model"] if m["model_name"] is None)
    assert untracked_row["priced"] is False
    assert untracked_row["cost_usd"] is None
    assert untracked_row["untracked"] == 4


def test_get_cost_data_reports_an_unpriced_model_as_unknown(monkeypatch):
    # Tokens are known, the model isn't in the price table. That has to read
    # as "unknown", never as $0.00.
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = [
        _cost_group(date(2026, 5, 1), model="some-local-llama")
    ]

    data = db.get_cost_data()

    assert data["by_model"][0]["priced"] is False
    assert data["by_model"][0]["cost_usd"] is None
    assert data["totals"]["unpriced"] == 1
    assert data["totals"]["cost_usd"] == 0.0
    assert data["totals"]["avg_cost_per_ticket_usd"] is None


def test_get_cost_data_accumulates_spend_across_days(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = [
        _cost_group(date(2026, 5, 3)),
        _cost_group(date(2026, 5, 1)),
        _cost_group(date(2026, 5, 2)),
    ]

    days = db.get_cost_data()["by_day"]

    assert [d["date"] for d in days] == [
        date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    ]
    assert [d["cumulative_cost_usd"] for d in days] == pytest.approx([18.0, 36.0, 54.0])


def test_get_cost_data_handles_an_empty_window(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchall.return_value = []

    data = db.get_cost_data()

    assert data["by_day"] == []
    assert data["totals"]["cost_usd"] == 0.0
    assert data["totals"]["avg_cost_per_ticket_usd"] is None


def test_get_summary_stats_returns_three_counts(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.side_effect = [(42,), (7,), (5,)]

    stats = db.get_summary_stats()

    assert stats == {
        "open_count": 42,
        "auto_denied_today": 7,
        "needs_review": 5,
    }


def test_get_ticket_date_bounds_returns_min_max(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = (date(2026, 1, 1), date(2026, 6, 1))

    assert db.get_ticket_date_bounds() == (date(2026, 1, 1), date(2026, 6, 1))


def test_get_ticket_date_bounds_falls_back_when_table_empty(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = (None, None)

    start, end = db.get_ticket_date_bounds()

    assert end == date.today()
    assert start == date.today() - timedelta(days=90)
