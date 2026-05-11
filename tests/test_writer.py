from evaluation.writer import WriterError, _validate


VALID_RESULT = {
    "ticket_id": "TKT-1",
    "user_id": "USR-1",
    "ai_summary": "Summary",
    "ai_category": "Needs Review",
    "admitted_cheating": False,
    "admitted_exploit": False,
    "confidence_score": 0.5,
    "ai_reasoning": "Reasoning",
}


def test_validate_accepts_complete_writer_payload():
    _validate(VALID_RESULT.copy())


def test_validate_rejects_missing_writer_field():
    data = VALID_RESULT.copy()
    data.pop("ai_reasoning")

    try:
        _validate(data)
    except WriterError as exc:
        assert "ai_reasoning" in str(exc)
    else:
        raise AssertionError("Expected WriterError")
