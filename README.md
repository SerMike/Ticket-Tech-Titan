<a id="readme-top"></a>

# Ticket Tech Titan

![Python](https://img.shields.io/badge/python-3.11+-blue)
[![CI](https://github.com/SerMike/Ticket-Tech-Titan/actions/workflows/ci.yml/badge.svg)](https://github.com/SerMike/Ticket-Tech-Titan/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-green)

AI-powered triage for game ban-appeal tickets. An LLM reads each ban appeal against the internal ban evidence, summarizes it for analysts, and sorts it into one of five priority buckets, and a deterministic rule layer guarantees confirmed cheaters can't talk their way out. Every ban appeal is still reviewed by a human. The point is prioritization: getting genuine appeals in front of a reviewer fast, so a player isn't left waiting on a response because templated bot appeals are gumming up the works.

```mermaid
%%{init: {'theme':'base','themeVariables':{'fontFamily':'ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif','fontSize':'14px','lineColor':'#7a7a7d'}}}%%
flowchart LR
    A["<b>Ingest</b><br/>tickets + ban records"] --> B["<b>Evaluate</b><br/>Claude reads the appeal"] --> C["<b>Enforce</b><br/>rules catch confirmed cheats"] --> D["<b>Review</b><br/>analysts work the queue"]
    classDef step fill:#eef6ff,stroke:#597ea3,stroke-width:1.5px,color:#1d2d3d
    classDef rule fill:#f8dcd8,stroke:#b84f47,stroke-width:1.5px,color:#7a2a26
    classDef review fill:#2c455d,stroke:#1d2d3d,color:#ffffff
    class A,B step
    class C rule
    class D review
```

**Contents:** [Background](#based-on-a-system-shipped-in-production-at-bungie) · [How it works](#how-it-works) · [Screenshots](#screenshots) · [Getting started](#getting-started) · [Running tests](#running-tests) · [Configuration](#configuration) · [API reference](#api-reference) · [Design notes](#design-notes) · [Project structure](#project-structure)

## Based on a system shipped in production at Bungie

As a **Security Data Analyst on Bungie's Product Security team**, I spent 3–4 hours of every workday triaging Destiny 2 ban-appeal tickets. The routine was always the same: open a ticket, read the appeal, look up the player's profile in a separate internal tool, review the case, and conclude, most of the time, that the ban was justified and none of it had needed my attention. Worse, a flood of templated, botnet-generated appeals buried the tickets that actually mattered: the rare players who might have been banned mistakenly or accidentally.

Classical machine learning couldn't fix this. The appeal body is a freeform field where players write long, winding appeals, and traditional classifiers broke down on them quickly. An LLM doesn't: it digests a rambling appeal into a 2–3 sentence summary, weighs the player's claims against the internal ban evidence, and returns its judgment as strict JSON that flows straight back into a database. You end up with the best of both worlds: the programmatic, deterministic value of a traditional data pipeline with the flexibility of a model that can actually read.

I conceived the first version in late 2023 on the GPT-3.5 API (the only commercial model available at the outset) and it shipped to production in January 2024 after a 3–4 month build alongside a project manager, a data scientist, and a data engineer. **My daily triage time dropped from 3–4 hours to 20 minutes–1 hour**, depending on if we implemented new detection in a ban wave. The team later helped adapt the workflow to wider player-support queries, so urgent requests surfaced faster with better priorities.

This repository is a from-scratch, rough approximation of the real system that took a small, dedicated team over a handful of months to build. It uses synthetic data and Claude Sonnet 4.6 in place of confidential tickets and the original model. It exists to show concretely that AI in a production workflow delivers a meaningful return on time and investment, and to document what that takes in practice: prompt engineering grounded in real ban policy, schema design that treats model output as untrusted input, and an architecture that stays fully testable without a database or an API key.

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## How it works

1. **Ingest** — ticket and ban-record JSON exports are validated and loaded into PostgreSQL.
2. **Evaluate** — Claude reads each appeal against its ban record and returns a summary, reasoning, a category, and a confidence score as JSON.
3. **Enforce** — deterministic rules override the model whenever the ban record shows a confirmed technical detection.
4. **Review** — analysts work the prioritized queue in a web dashboard, with analytics and per-decision cost tracking.

Each ticket lands in one of five categories:

| Category | Meaning |
|---|---|
| Auto-Deny | The ban record shows a confirmed technical detection (e.g. cheat-engine signature, aim-lock, speed-hack, connection manipulation); also enforced by deterministic rules |
| Admitted to Cheating | The appeal itself admits to cheating, exploiting, mods, or other prohibited behavior |
| Templated/Bot Appeal | Generic, copy-pasted, or bot-generated text with no case-specific detail |
| Likely Legitimate | Rare: weak or missing ban evidence plus a specific, verifiable appeal; flagged for priority human review |
| Needs Review | Doesn't fit cleanly elsewhere, or the model is uncertain; needs an analyst's judgment |

```mermaid
flowchart TD
    subgraph ING["Ingestion"]
        J["Ticket + ban record<br/>JSON exports"] --> I["ingest_ticket.py<br/>validate + insert, skip duplicates"]
    end
    I --> ST[("support_tickets")]
    I --> BD[("ban_database")]
    subgraph PIPE["Evaluation pipeline (run_pipeline.py)"]
        EV["LLM evaluation<br/>claude-sonnet-4-6 by default<br/>(evaluator.py)"] --> AD["Auto-deny override<br/>deterministic safety net<br/>(auto_deny.py)"]
        AD --> WR["Schema-validated UPSERT<br/>(writer.py)"]
    end
    ST -->|"LEFT JOIN on user_id"| EV
    BD --> EV
    WR --> AI[("support_tickets_with_ai")]
    subgraph DASH["Dashboard (FastAPI + web/)"]
        Q["Queue + ticket detail"]
        AN["Analytics charts"]
        CO["Cost breakdown"]
    end
    AI --> Q
    AI --> AN
    AI --> CO
    ST --> Q
    Q -->|"status updates"| ST
    Q -->|"audit trail"| TH[("ticket_status_history")]
```

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## Screenshots

**Ticket queue** — the AI-triaged queue with category tags and confidence scores, plus the detail view pairing the player's appeal with the ban record and the AI's evaluation:

![Queue page](docs/screenshots/queue.png)

**Analytics** — category breakdown, admission rates, detection-method volume, ticket volume over time, and confidence distribution:

![Analytics page](docs/screenshots/analytics.png)

**Costs** — spend per day, cumulative spend, spend by model, and API spend set against the analyst time it displaced:

![Costs page](docs/screenshots/costs.png)

**Light theme** — follows your OS setting, or the toggle in the top-right:

![Dashboard page in light mode](docs/screenshots/dashboard-light.png)

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## Getting started

### Prerequisites

- Python 3.11+
- Docker (or your own PostgreSQL 16 — see [Configuration](#configuration))
- An [Anthropic API key](https://console.anthropic.com/), or a key for OpenAI, Gemini or Groq, or a local Ollama model (see [Using other models](#using-other-models))
- Node 22+ *(optional, only for the front-end tests)*

### 1. Install

```bash
git clone https://github.com/SerMike/Ticket-Tech-Titan.git
cd Ticket-Tech-Titan
python -m venv venv
source venv/bin/activate          # Git Bash on Windows: source venv/Scripts/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ticket_tech_titan
ANTHROPIC_API_KEY=sk-ant-...
```

Using a different provider? Set the variables in [Using other models](#using-other-models) instead of `ANTHROPIC_API_KEY`.

### 3. Start the database and load sample data

```bash
docker compose up -d                  # PostgreSQL 16 on localhost:5432
python database/init_db.py            # create schema + categories (drops existing tables)
python ingestion/ingest_ticket.py --tickets data/sample_tickets.json --bans data/sample_bans.json
```

### 4. Run the AI pipeline

```bash
python evaluation/run_pipeline.py --limit 5     # ~5 cents of API spend
```

Drop `--limit 5` to evaluate all 50 sample tickets (well under a dollar). Re-running is safe; evaluations are replaced, not duplicated.

### 5. Open the dashboard

```bash
uvicorn api.main:app
```

Then visit http://localhost:8000. One FastAPI process serves both the JSON API and the plain HTML/CSS/JS front-end, so there's nothing to build.

| View | Purpose |
|------|---------|
| Dashboard | Summary metrics: open tickets, auto-denies today, needs-review backlog |
| Queue | Ticket table filtered by AI category, status, submission date, confidence, and admitted cheating; click a ticket to read the appeal, ban record, and AI evaluation, and update its status |
| Analytics | Category breakdown, admission rates, detection methods, volume over time, and confidence distribution |
| Costs | LLM spend per ticket and per day, cumulative spend, spend by model, and API spend against the analyst time it displaced |

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## Running tests

The unit suite runs fully offline — no database, no API key, no `.env`:

```bash
pytest                              # unit tests
pytest -m integration               # integration tests (live PostgreSQL; one test makes 2 API calls)
pytest --cov=evaluation --cov=ingestion --cov=config --cov=dashboard --cov=api --cov-report=term-missing
node --test "tests/js/*.test.js"    # front-end queue-filter tests (Node 22+, nothing to install)
```

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## Configuration

All settings live in `.env` (see [`.env.example`](.env.example)):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `LLM_PROVIDER` | `anthropic` (default) or `openai`; see [Using other models](#using-other-models) |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `OPENAI_API_KEY` | Your key for an OpenAI-compatible provider, when `LLM_PROVIDER=openai` |
| `LLM_BASE_URL` | Endpoint of an OpenAI-compatible provider other than OpenAI itself |
| `MODEL_NAME` | Model used for evaluation (default `claude-sonnet-4-6`; required for other providers) |
| `LLM_MAX_TOKENS` | Reply budget per evaluation (default `1024`); raise it for reasoning models |
| `PRICE_PER_MTOK_INPUT` / `PRICE_PER_MTOK_OUTPUT` | Optional USD-per-million-token prices for a model not in the built-in price table |

A real environment variable takes precedence over `.env`, so you can point a single shell at a different database:

```bash
export DATABASE_URL=postgresql://localhost:5432/scratch
```

Keep that in mind before running `init_db.py`, which drops every table in whichever database it resolves.

**Using your own PostgreSQL:** create a database named `ticket_tech_titan`, set `DATABASE_URL` to point at it, and continue from step 3 without `docker compose`.

**Upgrading an existing database:** `init_db.py` is for first-time setup only. To pick up schema changes without losing data, apply the numbered files in [`database/migrations/`](database/migrations/):

```bash
psql "$DATABASE_URL" -f database/migrations/001_add_token_usage.sql
```

### Using other models

Claude is the default, but the pipeline runs on any provider that speaks the OpenAI chat-completions API: OpenAI itself, or Gemini, Groq, or a local Ollama model through their OpenAI-compatible endpoints. In `.env`, set:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=...
MODEL_NAME=...
```

`OPENAI_API_KEY` takes that provider's key (Ollama accepts any placeholder) and `MODEL_NAME` one of its models; there's no default model outside Anthropic. For anything but OpenAI itself, also set `LLM_BASE_URL`:

| Provider | `LLM_BASE_URL` |
|---|---|
| OpenAI | *(leave unset)* |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Groq | `https://api.groq.com/openai/v1` |
| Ollama (local) | `http://localhost:11434/v1` |

Check the key and model with one cheap call before a full run:

```bash
python scripts/smoke_client.py --provider openai --model <model-name>
```

- **The prompts were tuned against Claude**, so results may vary by model. Every reply still goes through the same validation and auto-deny rules.
- **Reasoning models need a bigger reply budget.** Models that reason before answering (e.g. OpenAI's o-series and GPT-5, Gemini's thinking models) spend part of `LLM_MAX_TOKENS` on hidden reasoning. If replies come back empty with `Finish reason: length` or cut off mid-JSON, raise it (8000 is a generous start). You're billed for the tokens used, not the budget.
- **Pricing.** The built-in price table covers Anthropic's models. For anything else, set `PRICE_PER_MTOK_INPUT` and `PRICE_PER_MTOK_OUTPUT` from your provider's pricing page (both `0` for a local model); otherwise the Costs view shows the tokens with an unknown price, never $0.00. OpenAI's automatic prompt-cache discount isn't applied, so its figures can run high.

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## API reference

`dashboard/db.py` holds every query; the API is a thin JSON wrapper over it.

| Endpoint | Returns |
|---|---|
| `GET /api/tickets` | Every ticket joined with its AI evaluation and ban record, newest first |
| `GET /api/tickets/{id}` | One joined ticket row (404 when missing) |
| `GET /api/tickets/{id}/evaluation` | `ai_summary` and `ai_reasoning` for a ticket (404 when unevaluated) |
| `PATCH /api/tickets/{id}/status` | Body `{"status": "open"\|"pending"\|"closed"}`; returns old + new status, 400 on an invalid status or unknown ticket |
| `GET /api/analytics?date_from=&date_to=` | Category breakdown, admission rates, detection-method counts, volume over time, confidence scores |
| `GET /api/costs?date_from=&date_to=` | LLM spend per day and per model plus totals, priced from stored token counts |
| `GET /api/stats` | `open_count`, `auto_denied_today`, `needs_review` |
| `GET /api/date-bounds` | Earliest and latest ticket dates |

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## Design notes

- **The LLM proposes; deterministic rules decide.** [`auto_deny.py`](evaluation/auto_deny.py) forces Auto-Deny whenever the ban record carries a confirmed technical detection, so a persuasive appeal can never override hard evidence.
- **Model output is untrusted input.** [`evaluator.py`](evaluation/evaluator.py) parses and schema-validates every response (required fields, category whitelist, strict booleans, confidence range) before anything touches the database. Malformed output is logged and the ticket is left unevaluated; it never corrupts a row.
- **Swappable model.** Everything calls `call_model()` in [`client.py`](evaluation/client.py), where one adapter per API family (Anthropic, or OpenAI-compatible) translates the request and normalizes token usage. Validation, the auto-deny rules, and cost tracking don't change with the model.
- **Idempotent pipeline.** Evaluations UPSERT on `ticket_id` ([`writer.py`](evaluation/writer.py)) and commit per ticket, so re-runs are safe and one bad ticket can't break a batch.
- **Measured cost.** Each evaluation stores the token counts the API billed ([`client.py`](evaluation/client.py)). Dollars are computed at query time from the price table in [`settings.py`](config/settings.py), so a price correction re-prices all history. Evaluations without usage data show as untracked rather than $0.00.
- **Offline-testable.** The database layer, LLM client, and orchestration are mockable seams; integration tests are opt-in via `pytest -m integration`.
- **Performance.** Throughput is ~6.2 s/ticket, almost entirely API-bound; dashboard queries return in 32–45 ms with 550 tickets loaded. Per-ticket commits make the pipeline easy to parallelize. Details in [docs/performance-notes.md](docs/performance-notes.md).

<p align="right"><a href="#readme-top">↑ Back to top</a></p>

## Project structure

```
api/
  main.py           FastAPI app — JSON endpoints over db.py + static file serving

web/                Single-page front-end (no build step)
  index.html        Shell, theme tokens, status colors
  app.js            State, views, aggregation, API calls
  filters.js        Queue filter predicates — DOM-free, so Node can test them
  industry-styles.css  Design-system stylesheet

dashboard/
  db.py             All DB queries (read + status update) — the API's seam
  cost.py           Token counts → dollars, priced at query time

database/
  schema.sql        PostgreSQL schema
  init_db.py        One-shot schema initialiser
  migrations/       Numbered forward-only migrations, applied by hand

ingestion/
  ingest_ticket.py  JSON ticket + ban record ingestor

evaluation/
  prompts.py        System prompt + user-prompt builder
  client.py         LLM client: Anthropic + OpenAI-compatible adapters, logged retry/backoff
  evaluator.py      Claude-powered ticket classifier
  auto_deny.py      Deterministic override rules
  writer.py         Persist evaluations to DB
  run_pipeline.py   End-to-end pipeline runner

analytics/          SQL analysis queries
reference/          Industry ban-policy reference docs
config/
  settings.py       DB connection, LLM provider settings, ALLOWED_STATUSES, model price table

tests/              Offline unit tests + opt-in integration tests
  js/               Node tests for web/filters.js
scripts/
  run_api.cmd          Launch the API + dashboard on Windows
  generate_tickets.py  Synthetic ticket/ban generator for perf testing
  capture_screenshots.py  Regenerates the README screenshots
  smoke_client.py      Manual live-API smoke test (--provider / --model to try another key)
  smoke_evaluate.py    Manual end-to-end evaluation spot-check
docs/
  performance-notes.md Performance baseline + scaling analysis
  screenshots/         README images, regenerated by capture_screenshots.py
  design/              Design source of truth for web/ — the Industry design
                       system generated with Claude Design: prototype, tokens,
                       and rendered references for both themes
```

<p align="right"><a href="#readme-top">↑ Back to top</a></p>
