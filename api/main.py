"""main.py — FastAPI app exposing dashboard/db.py over JSON.

Thin HTTP wrapper: every endpoint maps 1:1 to a db.py function and
returns its dicts unchanged (FastAPI serializes date/datetime to ISO
strings and Decimal to float). The static front-end in web/ is served
from the same app, so there are no CORS concerns.

Run with:  uvicorn api.main:app --reload
"""

import sys
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Like dashboard/db.py: make `from dashboard import db` resolve when
# uvicorn is launched from anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard import db  # noqa: E402

app = FastAPI(title="Ticket Tech Titan API")


class StatusUpdate(BaseModel):
    status: str


@app.get("/api/tickets")
def list_tickets():
    return db.get_all_tickets()


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: str):
    row = db.get_ticket_detail(ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id!r} not found")
    return row


@app.get("/api/tickets/{ticket_id}/evaluation")
def ticket_evaluation(ticket_id: str):
    row = db.get_ai_evaluation(ticket_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No AI evaluation for ticket {ticket_id!r}"
        )
    return row


@app.patch("/api/tickets/{ticket_id}/status")
def patch_status(ticket_id: str, body: StatusUpdate):
    try:
        old_status = db.update_ticket_status(ticket_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ticket_id": ticket_id,
        "old_status": old_status,
        "new_status": body.status,
    }


@app.get("/api/analytics")
def analytics(date_from: date | None = None, date_to: date | None = None):
    return db.get_analytics_data(date_from, date_to)


@app.get("/api/costs")
def costs(date_from: date | None = None, date_to: date | None = None):
    return db.get_cost_data(date_from, date_to)


@app.get("/api/stats")
def stats():
    return db.get_summary_stats()


@app.get("/api/date-bounds")
def date_bounds():
    min_date, max_date = db.get_ticket_date_bounds()
    return {"min": min_date, "max": max_date}


# Mounted last so /api/* routes win; html=True serves web/index.html at /.
app.mount("/", StaticFiles(directory=_PROJECT_ROOT / "web", html=True), name="web")
