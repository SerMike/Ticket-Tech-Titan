# Ticket Tech Titan

AI-powered support ticket analysis system for gaming companies that evaluates ban appeal requests.

## Setup

1. Copy `.env.example` to `.env` and fill in your credentials:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/ticket_tech_titan
   ANTHROPIC_API_KEY=sk-ant-...
   ```
2. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate   # Windows
   source venv/bin/activate  # macOS / Linux
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Initialize the database:
   ```
   python database/init_db.py
   ```
5. Ingest sample data:
   ```
   python ingestion/ingest_ticket.py --tickets data/sample_tickets.json --bans data/sample_bans.json
   ```
6. Run the AI evaluation pipeline (requires `ANTHROPIC_API_KEY`):
   ```
   python evaluation/run_pipeline.py
   ```

## Running the dashboard

```
streamlit run dashboard/app.py
```

Opens at http://localhost:8501. The dashboard has three pages:

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `/` | Summary metrics — open tickets, auto-denies today, needs-review backlog |
| Queue | `/queue` | Filterable ticket table; click any ticket to read the full appeal, ban record, and AI evaluation, and update its status |
| Analytics | `/analytics` | Plotly charts — category breakdown, admission rates, detection methods, volume over time |

Use the **🔄 Refresh data** button in the sidebar to pull the latest DB state at any time.

## Running tests

Install dev dependencies and run pytest:

```
pip install -r requirements-dev.txt
pytest
```

All 18 tests run offline with no DB or API key required.

## Project structure

```
dashboard/          Streamlit UI
  app.py            Landing page + summary metrics
  db.py             All DB queries (read + status update)
  pages/
    01_queue.py     Ticket queue with filters and detail view
    02_analytics.py Aggregate charts

database/
  schema.sql        PostgreSQL schema
  init_db.py        One-shot schema initialiser

ingestion/
  ingest_ticket.py  CSV / JSON ticket ingestor

evaluation/
  evaluator.py      Claude-powered ticket classifier
  auto_deny.py      Deterministic override rules
  writer.py         Persist evaluations to DB
  run_pipeline.py   End-to-end pipeline runner

config/
  settings.py       DB connection, ALLOWED_STATUSES

tests/              Offline unit tests (pytest + mocks)
scripts/
  smoke_client.py   Manual live-API smoke test
```
