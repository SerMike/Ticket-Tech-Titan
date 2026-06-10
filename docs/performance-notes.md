# Performance Baseline — Phase 4

Measured 2026-06-09 on a local dev machine (Windows 11, PostgreSQL 17 on
localhost, model `claude-sonnet-4-6`, sequential pipeline).

## Dataset

- 500 synthetic tickets + 500 ban records generated with
  `python scripts/generate_tickets.py --count 500` (IDs prefixed `TKT-PERF-` /
  `USR-PERF-` so they can be removed without touching the curated samples).
- Detection methods distributed across all four confirmed auto-deny methods
  plus `manual_review` and `stat_anomaly`; bodies rotate through five appeal
  archetypes (generic denial, specific/plausible, cheating admission, exploit
  admission, templated/bot).
- Total DB size after ingest: 550 tickets, 550 ban records.

## Pipeline throughput (`run_pipeline.py --limit 50`)

| Metric | Result |
|---|---|
| Tickets processed | 50 (50 succeeded, 0 failed) |
| Elapsed | 309.9 s |
| Per-ticket average | 6.2 s |
| API retries triggered | 0 |
| Auto-deny overrides | 1 |
| Category split | 20 Admitted to Cheating / 19 Auto-Deny / 11 Needs Review |

**The original < 90 s target (1.8 s/ticket) was missed by ~3.4×.** The
pipeline is almost entirely **API-bound**: each ticket is one synchronous
`messages.create` call carrying a ~2.5k-token system prompt, and 5–7 s
round-trips dominate. The per-ticket DB work (UPSERT + commit + one
follow-up SELECT) is low single-digit milliseconds — see the dashboard
numbers below.

Realistic paths to the target, deliberately out of scope for Phase 4:

1. **Concurrency** — the per-ticket commit design means N workers need no
   coordination; 8 parallel workers would put 50 tickets at roughly 40 s.
2. **Anthropic Batches API** — for non-interactive backfills, 50% cheaper
   and latency stops mattering.

## Dashboard queries at 550 tickets / 100 evaluations

| Query | Time |
|---|---|
| `get_all_tickets` (full queue join, 550 rows) | 45 ms |
| `get_summary_stats` | 32 ms |
| `get_analytics_data` (all-time, 5 aggregates) | 36 ms |
| `get_ticket_detail` | 33 ms |
| `get_ticket_date_bounds` | 32 ms |

All queries stay well under perceptible latency, before Streamlit's
`@st.cache_data` layer is even involved. Queue filtering and analytics
charts render instantly at this volume; the DB will not be the bottleneck
until well past 10k tickets.

## Cleanup

Synthetic data can be removed at any time:

```sql
DELETE FROM support_tickets_with_ai WHERE ticket_id LIKE 'TKT-PERF-%';
DELETE FROM ticket_status_history   WHERE ticket_id LIKE 'TKT-PERF-%';
DELETE FROM support_tickets         WHERE ticket_id LIKE 'TKT-PERF-%';
DELETE FROM ban_database            WHERE user_id   LIKE 'USR-PERF-%';
```
