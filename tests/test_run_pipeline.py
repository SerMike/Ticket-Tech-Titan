from evaluation.run_pipeline import _build_fetch_query, _split_row


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
