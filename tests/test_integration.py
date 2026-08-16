"""Integration tests — require a live PostgreSQL database (see pyproject.toml).

Skipped by default; run with `pytest -m integration`. Each test seeds a
uniquely-named throwaway ticket and removes it (and all dependent rows)
in teardown, so the existing data is never touched.

`test_pipeline_idempotency` additionally requires ANTHROPIC_API_KEY and
makes two real API calls (one ticket, evaluated twice).
"""

import uuid

import psycopg2
import pytest

from config import settings
from dashboard import db as dashboard_db
from evaluation import run_pipeline as rp
from ingestion.ingest_ticket import ingest_single_ticket

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded_ticket():
    """Insert a committed, uniquely-named test ticket; delete it (and any
    evaluation/history rows) afterwards.

    Committed rather than rolled back because the functions under test
    (get_ticket_detail, update_ticket_status, run_pipeline) open their own
    connections and would never see an uncommitted insert.
    """
    suffix = uuid.uuid4().hex[:8].upper()
    ticket = {
        "ticket_id": f"TKT-INTEG-{suffix}",
        "user_name": "IntegrationTester",
        "user_id": f"USR-INTEG-{suffix}",
        "ticket_issue_category": "Request Account Unban",
        "ticket_title": "Integration test ticket",
        "ticket_body": "This ticket was created by the integration test suite.",
        "status": "open",
        "created_at": "2026-06-09T12:00:00",
    }
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            assert ingest_single_ticket(cur, ticket) == "inserted"
        yield ticket
    finally:
        with conn, conn.cursor() as cur:
            for table in ("support_tickets_with_ai", "ticket_status_history",
                          "support_tickets"):
                cur.execute(
                    f"DELETE FROM {table} WHERE ticket_id = %s",
                    (ticket["ticket_id"],),
                )
        conn.close()


def test_ingest_then_query_round_trip(seeded_ticket):
    detail = dashboard_db.get_ticket_detail(seeded_ticket["ticket_id"])

    assert detail is not None
    for field in ("ticket_id", "user_name", "user_id", "ticket_issue_category",
                  "ticket_title", "ticket_body", "status"):
        assert detail[field] == seeded_ticket[field]
    assert detail["ai_category"] is None  # not evaluated yet
    assert detail["ban_reason"] is None   # no ban record for the test user


def test_pipeline_idempotency(seeded_ticket):
    if not settings.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")
    tid = seeded_ticket["ticket_id"]

    first = rp.run_pipeline(force=False, ticket_id=tid, limit=None)
    second = rp.run_pipeline(force=False, ticket_id=tid, limit=None)

    assert (first.succeeded, first.failed, first.inserted) == (1, 0, 1)
    assert (second.succeeded, second.failed, second.updated) == (1, 0, 1)

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM support_tickets_with_ai WHERE ticket_id = %s",
                (tid,),
            )
            assert cur.fetchone()[0] == 1  # UPSERT, not double-insert
    finally:
        conn.close()


def test_pipeline_persists_token_usage(seeded_ticket):
    """The only test that proves migration 001 was actually applied.

    Every other cost test mocks the cursor, so a database missing the three
    columns would still show a green suite while the pipeline failed on every
    ticket.
    """
    if not settings.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")
    tid = seeded_ticket["ticket_id"]

    stats = rp.run_pipeline(force=False, ticket_id=tid, limit=None)
    assert (stats.succeeded, stats.failed) == (1, 0)

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT input_tokens, output_tokens, model_name "
                "FROM support_tickets_with_ai WHERE ticket_id = %s",
                (tid,),
            )
            input_tokens, output_tokens, model_name = cur.fetchone()
    finally:
        conn.close()

    assert input_tokens > 0
    assert output_tokens > 0
    assert model_name == settings.MODEL_NAME


def test_status_update_creates_history_row(seeded_ticket):
    tid = seeded_ticket["ticket_id"]

    old_status = dashboard_db.update_ticket_status(tid, "pending")

    assert old_status == "open"
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT old_status, new_status FROM ticket_status_history "
                "WHERE ticket_id = %s ORDER BY id",
                (tid,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    # Ingestion logs (NULL -> open); the update must add exactly (open -> pending).
    assert rows == [(None, "open"), ("open", "pending")]
