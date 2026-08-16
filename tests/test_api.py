from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api import main


@pytest.fixture
def client():
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def test_list_tickets_returns_db_rows(client, monkeypatch):
    rows = [
        {"ticket_id": "TKT-1", "ai_category": "Auto-Deny", "status": "open"},
        {"ticket_id": "TKT-2", "ai_category": None, "status": "closed"},
    ]
    monkeypatch.setattr(main.db, "get_all_tickets", Mock(return_value=rows))

    res = client.get("/api/tickets")

    assert res.status_code == 200
    assert res.json() == rows


def test_ticket_detail_returns_row(client, monkeypatch):
    monkeypatch.setattr(
        main.db, "get_ticket_detail", Mock(return_value={"ticket_id": "TKT-1"})
    )

    res = client.get("/api/tickets/TKT-1")

    assert res.status_code == 200
    assert res.json()["ticket_id"] == "TKT-1"


def test_ticket_detail_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(main.db, "get_ticket_detail", Mock(return_value=None))

    res = client.get("/api/tickets/TKT-MISSING")

    assert res.status_code == 404


def test_evaluation_returns_ai_fields(client, monkeypatch):
    monkeypatch.setattr(
        main.db,
        "get_ai_evaluation",
        Mock(return_value={"ai_summary": "S", "ai_reasoning": "R"}),
    )

    res = client.get("/api/tickets/TKT-1/evaluation")

    assert res.status_code == 200
    assert res.json() == {"ai_summary": "S", "ai_reasoning": "R"}


def test_evaluation_404_when_not_evaluated(client, monkeypatch):
    monkeypatch.setattr(main.db, "get_ai_evaluation", Mock(return_value=None))

    assert client.get("/api/tickets/TKT-1/evaluation").status_code == 404


def test_stats_returns_three_counts(client, monkeypatch):
    stats = {"open_count": 42, "auto_denied_today": 7, "needs_review": 5}
    monkeypatch.setattr(main.db, "get_summary_stats", Mock(return_value=stats))

    assert client.get("/api/stats").json() == stats


def test_date_bounds_serializes_min_max(client, monkeypatch):
    monkeypatch.setattr(
        main.db,
        "get_ticket_date_bounds",
        Mock(return_value=(date(2026, 1, 1), date(2026, 6, 1))),
    )

    assert client.get("/api/date-bounds").json() == {
        "min": "2026-01-01",
        "max": "2026-06-01",
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def test_analytics_passes_dates_through(client, monkeypatch):
    fake = Mock(return_value={"category_breakdown": [], "admission_rates": {}})
    monkeypatch.setattr(main.db, "get_analytics_data", fake)

    res = client.get("/api/analytics?date_from=2026-04-01&date_to=2026-04-30")

    assert res.status_code == 200
    fake.assert_called_once_with(date(2026, 4, 1), date(2026, 4, 30))


def test_analytics_defaults_to_none_when_dates_omitted(client, monkeypatch):
    fake = Mock(return_value={})
    monkeypatch.setattr(main.db, "get_analytics_data", fake)

    client.get("/api/analytics")

    fake.assert_called_once_with(None, None)


# ---------------------------------------------------------------------------
# Status write path
# ---------------------------------------------------------------------------

def test_patch_status_returns_old_and_new(client, monkeypatch):
    fake = Mock(return_value="open")
    monkeypatch.setattr(main.db, "update_ticket_status", fake)

    res = client.patch("/api/tickets/TKT-1/status", json={"status": "pending"})

    assert res.status_code == 200
    assert res.json() == {
        "ticket_id": "TKT-1",
        "old_status": "open",
        "new_status": "pending",
    }
    fake.assert_called_once_with("TKT-1", "pending")


def test_patch_status_400_on_value_error(client, monkeypatch):
    monkeypatch.setattr(
        main.db,
        "update_ticket_status",
        Mock(side_effect=ValueError("Invalid status 'bogus'")),
    )

    res = client.patch("/api/tickets/TKT-1/status", json={"status": "bogus"})

    assert res.status_code == 400
    assert "Invalid status" in res.json()["detail"]


def test_patch_status_400_when_ticket_missing(client, monkeypatch):
    monkeypatch.setattr(
        main.db,
        "update_ticket_status",
        Mock(side_effect=ValueError("Ticket 'TKT-NOPE' not found")),
    )

    res = client.patch("/api/tickets/TKT-NOPE/status", json={"status": "open"})

    assert res.status_code == 400


def test_patch_status_422_when_body_missing_status(client):
    assert client.patch("/api/tickets/TKT-1/status", json={}).status_code == 422


# ---------------------------------------------------------------------------
# Static front-end
# ---------------------------------------------------------------------------

def test_root_serves_the_front_end(client):
    res = client.get("/")

    assert res.status_code == 200
    assert "Ticket Tech Titan" in res.text
