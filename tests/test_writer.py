from unittest.mock import MagicMock

import pytest

from evaluation.writer import WriterError, _validate, save_evaluation


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


def _mock_conn(inserted: bool):
    """Connection mock whose cursor context manager reports the upsert's
    RETURNING (xmax = 0) value — True for INSERT, False for UPDATE."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (inserted,)
    return conn, cur


def test_save_evaluation_inserts_new_row():
    conn, cur = _mock_conn(inserted=True)

    assert save_evaluation(conn, VALID_RESULT.copy()) is True

    cur.execute.assert_called_once()
    _, params = cur.execute.call_args.args
    assert params[0] == "TKT-1"


def test_save_evaluation_updates_existing_row():
    conn, _ = _mock_conn(inserted=False)

    assert save_evaluation(conn, VALID_RESULT.copy()) is False


def test_save_evaluation_does_not_commit():
    # Transaction boundaries belong to the pipeline runner, not the writer.
    conn, _ = _mock_conn(inserted=True)

    save_evaluation(conn, VALID_RESULT.copy())

    conn.commit.assert_not_called()


def test_save_evaluation_rejects_invalid_payload():
    conn, _ = _mock_conn(inserted=True)
    data = VALID_RESULT.copy()
    data.pop("confidence_score")

    with pytest.raises(WriterError, match="confidence_score"):
        save_evaluation(conn, data)

    conn.cursor.assert_not_called()
