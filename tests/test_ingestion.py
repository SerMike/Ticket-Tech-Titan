from pathlib import Path
from unittest.mock import Mock

from ingestion.ingest_ticket import (
    ingest_single_ticket,
    load_json_file,
    validate_ticket,
)

VALID_TICKET = {
    "ticket_id": "TKT-1",
    "user_name": "PlayerOne",
    "user_id": "USR-1",
    "ticket_issue_category": "Request Account Unban",
    "ticket_title": "Please unban me",
    "ticket_body": "I did not cheat.",
    "status": "open",
    "created_at": "2026-05-01T12:00:00",
}


def test_ingest_valid_ticket_calls_execute():
    cur = Mock()
    cur.rowcount = 1  # INSERT succeeded

    result = ingest_single_ticket(cur, VALID_TICKET.copy())

    assert result == "inserted"
    # Two executes: the ticket INSERT, then the initial status-history row.
    assert cur.execute.call_count == 2
    insert_sql, insert_params = cur.execute.call_args_list[0].args
    assert "INSERT INTO support_tickets" in insert_sql
    assert "TKT-1" in insert_params


def test_ingest_duplicate_ticket_upserts():
    cur = Mock()
    cur.rowcount = 0  # ON CONFLICT DO NOTHING hit an existing row

    result = ingest_single_ticket(cur, VALID_TICKET.copy())

    assert result == "skipped"
    insert_sql, _ = cur.execute.call_args.args
    assert "ON CONFLICT (ticket_id) DO NOTHING" in insert_sql
    # No status-history row for a skipped duplicate.
    assert cur.execute.call_count == 1


def test_ingest_missing_required_field_fails_without_db_call():
    # ingest_single_ticket reports a validation failure rather than raising;
    # the DB must never be touched.
    cur = Mock()
    ticket = VALID_TICKET.copy()
    ticket.pop("ticket_id")

    result = ingest_single_ticket(cur, ticket)

    assert result == "failed"
    cur.execute.assert_not_called()
    assert validate_ticket(ticket) == ["ticket_id"]


def test_ingest_reads_json_file_correctly():
    sample = Path(__file__).resolve().parent.parent / "data" / "sample_tickets.json"

    data = load_json_file(sample)

    tickets = data["tickets"]
    assert len(tickets) >= 50
    assert all("ticket_id" in t for t in tickets)
