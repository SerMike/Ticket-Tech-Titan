import json

import pytest

from evaluation.evaluator import EvaluationError, _parse_json, _validate, evaluate_ticket


VALID_EVALUATION = {
    "ai_summary": "The player denies cheating while the ban record cites detection.",
    "ai_category": "Needs Review",
    "admitted_cheating": False,
    "admitted_exploit": False,
    "confidence_score": 0.7,
    "ai_reasoning": "The appeal is specific enough to review manually.",
}

TICKET = {
    "ticket_id": "TKT-1",
    "user_name": "PlayerOne",
    "user_id": "USR-1",
    "ticket_issue_category": "Request Account Unban",
    "ticket_title": "Please review my ban",
    "ticket_body": "I think this was a false positive.",
}


def test_parse_json_accepts_plain_json():
    assert _parse_json('{"ai_category": "Needs Review"}') == {
        "ai_category": "Needs Review"
    }


def test_parse_json_strips_markdown_fence():
    assert _parse_json('```json\n{"ai_category": "Needs Review"}\n```') == {
        "ai_category": "Needs Review"
    }


def test_parse_json_rejects_invalid_payload():
    with pytest.raises(EvaluationError, match="not valid JSON"):
        _parse_json("not json")


def test_validate_accepts_valid_evaluation():
    _validate(VALID_EVALUATION.copy())


def test_validate_rejects_bad_category():
    data = VALID_EVALUATION | {"ai_category": "Other"}

    with pytest.raises(EvaluationError, match="ai_category"):
        _validate(data)


def test_validate_rejects_boolean_confidence_score():
    data = VALID_EVALUATION | {"confidence_score": True}

    with pytest.raises(EvaluationError, match="confidence_score"):
        _validate(data)


def test_evaluate_ticket_returns_clean_schema(monkeypatch):
    raw = (
        '{"ai_summary":"Summary","ai_category":"Needs Review",'
        '"admitted_cheating":false,"admitted_exploit":false,'
        '"confidence_score":0.5,"ai_reasoning":"Reasoning"}'
    )
    monkeypatch.setattr("evaluation.evaluator.call_model", lambda **kwargs: raw)

    result = evaluate_ticket(TICKET, ban_record=None)

    assert result == {
        "ticket_id": "TKT-1",
        "user_id": "USR-1",
        "ai_summary": "Summary",
        "ai_category": "Needs Review",
        "admitted_cheating": False,
        "admitted_exploit": False,
        "confidence_score": 0.5,
        "ai_reasoning": "Reasoning",
    }


def test_evaluate_ticket_raises_on_empty_response(monkeypatch):
    monkeypatch.setattr("evaluation.evaluator.call_model", lambda **kwargs: "")

    with pytest.raises(EvaluationError, match="not valid JSON"):
        evaluate_ticket(TICKET, ban_record=None)


def test_evaluate_ticket_raises_on_valid_json_but_missing_fields(monkeypatch):
    payload = {k: v for k, v in VALID_EVALUATION.items() if k != "confidence_score"}
    monkeypatch.setattr(
        "evaluation.evaluator.call_model", lambda **kwargs: json.dumps(payload)
    )

    with pytest.raises(EvaluationError, match="confidence_score"):
        evaluate_ticket(TICKET, ban_record=None)


def test_evaluate_ticket_raises_on_confidence_score_out_of_range(monkeypatch):
    payload = VALID_EVALUATION | {"confidence_score": 1.5}
    monkeypatch.setattr(
        "evaluation.evaluator.call_model", lambda **kwargs: json.dumps(payload)
    )

    with pytest.raises(EvaluationError, match="out of range"):
        evaluate_ticket(TICKET, ban_record=None)
