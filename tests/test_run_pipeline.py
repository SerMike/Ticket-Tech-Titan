from datetime import date
from unittest.mock import MagicMock

import pytest

from evaluation import run_pipeline as rp
from evaluation.evaluator import EvaluationError
from evaluation.run_pipeline import PipelineStats, _build_fetch_query, _split_row, process_one
from evaluation.writer import WriterError


def test_build_fetch_query_skips_processed_by_default():
    sql, params = _build_fetch_query(force=False, ticket_id=None, limit=None)

    assert "NOT EXISTS" in sql
    assert "LIMIT" not in sql
    assert params == ()


def test_build_fetch_query_ticket_id_overrides_force_and_limit():
    sql, params = _build_fetch_query(force=True, ticket_id="TKT-1", limit=5)

    assert "t.ticket_id = %s" in sql
    assert "LIMIT %s" in sql
    assert params == ("TKT-1", 5)


def test_split_row_returns_none_when_no_ban_record():
    row = {
        "ticket_id": "TKT-1",
        "user_name": "PlayerOne",
        "user_id": "USR-1",
        "ticket_issue_category": "Request Account Unban",
        "ticket_title": "Please review",
        "ticket_body": "Appeal body",
        "ban_user_id": None,
        "ban_reason": None,
        "detection_method": None,
        "ban_duration": None,
        "ban_date": None,
    }

    ticket, ban = _split_row(row)

    assert ticket["ticket_id"] == "TKT-1"
    assert ban is None


def test_split_row_returns_ban_when_ban_user_id_present():
    row = {
        "ticket_id": "TKT-1",
        "user_name": "PlayerOne",
        "user_id": "USR-1",
        "ticket_issue_category": "Request Account Unban",
        "ticket_title": "Please review",
        "ticket_body": "Appeal body",
        "ban_user_id": "USR-1",
        "ban_reason": "Aimbot detected",
        "detection_method": "cheat_engine_signature",
        "ban_duration": "permanent",
        "ban_date": date(2026, 5, 1),
    }

    ticket, ban = _split_row(row)

    assert ticket["ticket_id"] == "TKT-1"
    assert ban == {
        "user_id": "USR-1",
        "ban_reason": "Aimbot detected",
        "detection_method": "cheat_engine_signature",
        "ban_duration": "permanent",
        "ban_date": "2026-05-01",
    }


_EVAL_RESULT = {
    "ticket_id": "TKT-1",
    "user_id": "USR-1",
    "ai_summary": "Summary",
    "ai_category": "Needs Review",
    "admitted_cheating": False,
    "admitted_exploit": False,
    "confidence_score": 0.8,
    "ai_reasoning": "Reasoning",
}


def test_process_one_happy_path(monkeypatch):
    monkeypatch.setattr(rp, "evaluate_ticket", lambda t, b: _EVAL_RESULT.copy())
    monkeypatch.setattr(rp, "enforce_auto_deny", lambda r, b: r)
    monkeypatch.setattr(rp, "save_evaluation", lambda conn, r: True)
    conn = MagicMock()

    category, inserted, overridden = process_one(conn, {"ticket_id": "TKT-1"}, None)

    assert (category, inserted, overridden) == ("Needs Review", True, False)
    conn.commit.assert_called_once()


def test_process_one_reports_auto_deny_override(monkeypatch):
    overriding = dict(_EVAL_RESULT, ai_category="Auto-Deny")
    monkeypatch.setattr(rp, "evaluate_ticket", lambda t, b: _EVAL_RESULT.copy())
    monkeypatch.setattr(rp, "enforce_auto_deny", lambda r, b: overriding)
    monkeypatch.setattr(rp, "save_evaluation", lambda conn, r: False)

    category, inserted, overridden = process_one(MagicMock(), {}, None)

    assert (category, inserted, overridden) == ("Auto-Deny", False, True)


def test_process_one_propagates_evaluation_error(monkeypatch):
    def _raise(t, b):
        raise EvaluationError("model returned garbage")

    monkeypatch.setattr(rp, "evaluate_ticket", _raise)
    conn = MagicMock()

    with pytest.raises(EvaluationError):
        process_one(conn, {"ticket_id": "TKT-1"}, None)

    conn.commit.assert_not_called()


def test_process_one_propagates_writer_error(monkeypatch):
    def _raise(conn, r):
        raise WriterError("db write failed")

    monkeypatch.setattr(rp, "evaluate_ticket", lambda t, b: _EVAL_RESULT.copy())
    monkeypatch.setattr(rp, "enforce_auto_deny", lambda r, b: r)
    monkeypatch.setattr(rp, "save_evaluation", _raise)
    conn = MagicMock()

    with pytest.raises(WriterError):
        process_one(conn, {"ticket_id": "TKT-1"}, None)

    conn.commit.assert_not_called()


def test_pipeline_stats_record_success_increments_counters():
    stats = PipelineStats(total=3)

    stats.record_success("Auto-Deny", inserted=True, overridden=True,
                         admitted_cheat=True, admitted_exp=False, had_ban=True)
    stats.record_success("Auto-Deny", inserted=False, overridden=False,
                         admitted_cheat=False, admitted_exp=True, had_ban=True)
    stats.record_success("Needs Review", inserted=True, overridden=False,
                         admitted_cheat=False, admitted_exp=False, had_ban=False)

    assert stats.succeeded == 3
    assert stats.categories == {"Auto-Deny": 2, "Needs Review": 1}
    assert stats.inserted == 2
    assert stats.updated == 1
    assert stats.overrides == 1
    assert stats.admitted_cheating == 1
    assert stats.admitted_exploit == 1
    assert stats.no_ban_record == 1


def test_pipeline_stats_record_failure_appends_to_list():
    stats = PipelineStats(total=2)

    stats.record_failure("TKT-1", "EvaluationError: bad json")
    stats.record_failure("TKT-2", "WriterError: db down")

    assert stats.failed == 2
    assert stats.failures == [
        ("TKT-1", "EvaluationError: bad json"),
        ("TKT-2", "WriterError: db down"),
    ]
