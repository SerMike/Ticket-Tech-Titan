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
