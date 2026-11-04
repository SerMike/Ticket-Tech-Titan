# Appeal-surge detection — design spec

**Issue:** [#3 Appeal-surge detection — flag potential banwave impact](https://github.com/SerMike/Ticket-Tech-Titan/issues/3)
**Status:** Draft for owner review
**Date:** 2026-11-04

---

## 1. Problem

When a banwave lands, appeal volume spikes within hours. That spike is an
early warning that a recent enforcement action may have hit more players than
intended. In production at Bungie, triage load swung on exactly this: whether
a new detection had just gone out in a ban wave. Today the dashboard shows
daily volume but says nothing about a spike, and nothing about *which*
enforcement action is driving it. An analyst has to notice the spike and then
cross-reference ban records by hand.

The repo is also a portfolio artifact. A visitor running the demo should see
the feature fire and see the correlation, without having to stage data
themselves.

## 2. Success criteria

1. With the base sample plus the surge demo dataset loaded, the Dashboard
   shows a surge banner naming `stat_anomaly` bans on 2026-04-10 as the
   likely cause.
2. With only the base sample loaded, no banner appears.
3. The detection logic has offline unit tests (no database, no API key),
   covering the window boundary and the threshold edge.
4. A committed test proves the shipped demo data triggers the surge, so the
   demo can't silently break.
5. `pytest` and `node --test "tests/js/*.test.js"` pass. CI stays green.
6. The README documents the demo step, the settings, the endpoint, and the
   clock trade-off, and includes a screenshot of the banner.

## 3. Scope

**In:**

- A configurable threshold: a count plus a window length.
- A pure detection module, a DB query, and the `GET /api/surge` endpoint.
- A Dashboard banner shown while a surge is active.
- A surge marker on the Analytics volume-over-time chart.
- Correlation of the surge with `(ban_date, detection_method)` clusters.
- An optional demo dataset plus its generator script.
- Tests, README, `.env.example`, and screenshots.

**Out (deferred):**

| Item | Why it's deferred |
|---|---|
| Push notifications (email/webhook) | Needs a scheduled job. The issue defers it explicitly |
| Baseline-relative trigger (e.g. 3× the normal hourly rate) | The smarter next step, but more logic and tuning. v1 follows the issue's count-plus-window rule |
| Hourly resolution on the volume chart | That's a chart redesign. The marker highlights the surge's day instead |
| A "Review surge tickets" button on the banner | Cut by the owner to keep the banner informational |
| Surge history (past surges) | v1 reports only the current window |

## 4. Constraints

- The unit suite must stay offline-testable, as the README promises.
- Follow the existing seam: `dashboard/db.py` owns queries, and `api/main.py`
  is a thin 1:1 wrapper.
- Use the Industry design tokens only, with no new hex colors. Both themes
  must work.
- Make no schema change. Everything is derived from `support_tickets` and
  `ban_database`.
- The base 50-ticket sample, its screenshots, and its README cost estimate
  stay unchanged.

## 5. Design

### 5.1 Architecture

```
 support_tickets ─┐
                  ├─► db.get_surge() ──► surge.detect() ──► GET /api/surge ─┬─► Dashboard banner
 ban_database ────┘   (rows in window)   (pure logic)                     └─► Analytics chart marker
```

This mirrors the Costs feature. `dashboard/cost.py` is pure logic,
`db.get_cost_data()` runs the query, and `/api/costs` plus the Costs view
consume it.

| Unit | Responsibility | Depends on |
|---|---|---|
| `dashboard/surge.py` | `detect(rows, as_of, threshold, window_minutes) -> dict`. Pure, with no I/O | nothing |
| `dashboard/db.py` → `get_surge()` | Finds `as_of`, fetches the rows in the window, and calls `surge.detect` with the settings | `config.settings`, `surge` |
| `config/settings.py` | Parses `SURGE_THRESHOLD` and `SURGE_WINDOW_MINUTES` | env |
| `api/main.py` → `GET /api/surge` | Returns `db.get_surge()` unchanged | `db` |
| `web/app.js` | Fetches the surge and renders the banner and chart marker | `/api/surge` |

### 5.2 Settings

| Variable | Default | Rule |
|---|---|---|
| `SURGE_THRESHOLD` | `100` | A positive whole number of tickets |
| `SURGE_WINDOW_MINUTES` | `60` | A positive whole number of minutes |

An invalid value raises `RuntimeError` at import, naming the variable. This is
the same behavior as `LLM_MAX_TOKENS` (`_token_budget`). Unset or empty means
the default.

### 5.3 Detection rules

1. **Clock.** `as_of` is the newest `support_tickets.created_at`, not the wall
   clock. This keeps the demo and the tests deterministic, and it matches how
   the Dashboard's "Auto-denied today" card already anchors on the latest
   ticket.
   - *Trade-off:* if ingestion stalls, an old surge can still read as active.
   - *Mitigation:* the banner always shows "as of `<timestamp>`".
2. **Window.** `window_start = as_of − window_minutes`. A ticket is in the
   window when `window_start < created_at ≤ as_of`. The range is half-open,
   so a boundary ticket is never counted in two adjacent windows.
3. **Trigger.** `active = count ≥ threshold`.
4. **Correlation** (only when active). Group the surge tickets by their ban
   record's `(ban_date, detection_method)`, joined on `user_id`. Tickets
   without a ban record form one group, with `ban_date: null` and
   `detection_method: "(no ban record)"`.
   - **Order:** groups are sorted by count, largest first. Ties go to the
     more recent `ban_date`, and `null` counts as oldest. Remaining ties sort
     by `detection_method` alphabetically, so the order is deterministic.
   - **Share:** `share = group count / surge count`, rounded to 2 decimals.
   - **Output:** `causes` holds the top 3 groups, and `top_cause` is
     `causes[0]`.
5. `detect()` re-applies the window filter to its input rows. Callers and tests
   may pass in rows outside the window, and those rows are ignored.

### 5.4 Edge cases

| Case | Result |
|---|---|
| No tickets | `active: false`; `as_of`, `window_start` and `top_cause` are `null`; `count: 0`; `causes: []` |
| Below threshold | `active: false`, `count` populated, `top_cause: null`, `causes: []` |
| Exactly at threshold | `active: true` |
| Surge mostly from unbanned players | the top cause is `(no ban record)`, shown as is |
| Fewer than 3 groups | `causes` has however many groups exist |

### 5.5 API — `GET /api/surge`

There are no parameters. The response when a surge is active:

```json
{
  "active": true,
  "as_of": "2026-04-11T09:48:00",
  "window_start": "2026-04-11T08:48:00",
  "window_minutes": 60,
  "threshold": 100,
  "count": 124,
  "top_cause": {"ban_date": "2026-04-10", "detection_method": "stat_anomaly", "count": 102, "share": 0.82},
  "causes": [
    {"ban_date": "2026-04-10", "detection_method": "stat_anomaly", "count": 102, "share": 0.82},
    {"ban_date": "2026-04-09", "detection_method": "cheat_engine_detection", "count": 11, "share": 0.09},
    {"ban_date": null, "detection_method": "(no ban record)", "count": 6, "share": 0.05}
  ]
}
```

The figures are illustrative. The real counts come from the generated demo
data.

### 5.6 Dashboard banner

- **When it shows:** only when `active`, above the three metric cards.
- **Frame:** `.blueprint` with corner marks, colored with `--status-deny-bg`
  and `--status-deny-fg`.
- **Content:**
  - a heading, "Appeal surge", with "as of `<as_of>`" right-aligned
  - "`<count>` appeals in the last `<window>` min — threshold is
    `<threshold>`."
  - "Likely cause: `<method>` bans on `<date>` (`<pct>`% of the surge)."
  - when there are runners-up, a muted "Also:" line listing them with their
    shares
- **Escaping:** every interpolated value goes through `esc()`.
- **No surge:** nothing is rendered.
- **Fetch failure:** a muted one-line note, "Surge check unavailable:
  `<error>`", and the rest of the Dashboard renders normally. This follows the
  `costsError` pattern.
- **Fetching:** `/api/surge` is fetched in parallel with `/api/tickets` on
  first load and on **Refresh data**.

### 5.7 Analytics volume-chart marker

- **When it shows:** only when `active` and the date of `as_of` is inside the
  selected From/To range.
- **The marker:** a dashed vertical line at that day's x-position, stroked in
  `--status-deny`. The day's dot is recolored to `--status-deny`, and a small
  "SURGE" label sits at the top of the line.
- **Tooltip:** a `title` on the line repeats the banner's summary sentence.

### 5.8 Demo dataset

- **Generator:** `scripts/generate_surge.py` with a fixed seed. It reuses the
  appeal templates from `scripts/generate_tickets.py` and writes:
  - `data/surge_tickets.json` (key `tickets`)
  - `data/surge_bans.json` (key `bans`)

  Both match the existing sample shape. Both the script and its output are
  committed.
- **IDs:** prefixed `TKT-SURGE-` and `USR-SURGE-`.
- **The banwave:** 102 `stat_anomaly` bans dated 2026-04-10, the day the base
  sample ends.
- **The surge:** about 124 appeal tickets between 2026-04-11 08:50 and 09:48:

  | Tickets | Ban |
  |---|---|
  | ~102 | the banwave bans |
  | ~11 | `cheat_engine_detection` bans dated 2026-04-09 |
  | ~6 | no ban record |
  | ~5 | assorted other methods and dates |

  The banwave appeals lean toward the "wrongful ban / hardware upgrade"
  templates, so a pipeline run on them tells the same story as the alert.
- **Loading:** a README step after the base load:
  ```bash
  python ingestion/ingest_ticket.py --tickets data/surge_tickets.json --bans data/surge_bans.json
  ```
  A note says that running the pipeline without `--limit` would then evaluate
  these tickets too, for an extra ~$1–2.

## 6. Testing

| Test | Kind | Covers |
|---|---|---|
| `tests/test_surge.py` | offline unit | empty input; below threshold; exactly at threshold; window boundary (`window_start` excluded, `as_of` included); out-of-window rows ignored; grouping and share; tie-break by recent `ban_date`; the no-ban bucket; the top-3 cut-off |
| `tests/test_surge.py` (settings) | offline unit | defaults when unset or empty; `0`, a negative number, and `abc` raise, naming the variable |
| `tests/test_surge.py` (demo guard) | offline unit | `detect()` on the committed `data/surge_*.json` with the default settings is active, and the top cause is `stat_anomaly` / 2026-04-10 |
| `tests/test_dashboard_db.py` | offline unit | `get_surge()` with a mocked connection, including the empty-table path |
| `tests/test_api.py` | offline unit | `GET /api/surge` passes the db result through |
| `tests/test_integration.py` | opt-in, `-m integration` | ingests the surge files into a live database and checks that `/api/surge` returns `active: true` |

The banner and marker are presentation only, so there are no new JS tests.
They're checked visually with `scripts/capture_screenshots.py`.

## 7. Plan (build order)

1. Settings parsing and tests.
2. `dashboard/surge.py` and its unit tests, written test-first.
3. `db.get_surge()` and its test.
4. `GET /api/surge` and its test.
5. `scripts/generate_surge.py`, the generated `data/surge_*.json` files, and
   the demo-guard test.
6. The Dashboard banner and fetch wiring in `web/app.js`.
7. The Analytics chart marker.
8. The integration test.
9. The README, `.env.example`, and a new screenshot (dashboard with banner).
10. Open a PR that closes #3.

## 8. Decisions log

| Decision | Choice | Rejected |
|---|---|---|
| Where the logic lives | A server-side pure module (A) | client-side JS (B), SQL-only (C) |
| Clock | the newest ticket's `created_at` | the wall clock; a switchable setting |
| Demo data | an optional second dataset | merged into the default sample; a generator flag only |
| Trigger | an absolute count plus a window | a baseline-relative multiple (deferred) |
| Banner action button | none | "Review surge tickets" (cut by the owner) |
| Below threshold | render nothing | an "all clear" card |

## 9. Open questions

None are blocking. The exact demo counts may shift by a ticket or two when
the generator runs. The demo-guard test asserts the outcome (active, top
cause), not exact counts.
