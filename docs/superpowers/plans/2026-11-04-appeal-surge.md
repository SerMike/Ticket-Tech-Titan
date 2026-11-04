# Appeal-Surge Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag an appeal surge on the dashboard and name the enforcement
action (ban date plus detection method) that most likely caused it. This
closes issue #3.

**Architecture:**
- **Detection:** a pure `dashboard/surge.py` module decides whether a surge
  is active and groups the surge tickets by ban cluster. It has no I/O.
- **Query:** `dashboard/db.get_surge()` finds the newest ticket, fetches the
  rows in the trailing window, and calls the pure function.
- **API:** `GET /api/surge` passes that result through unchanged.
- **Front-end:** `web/app.js` renders a Dashboard banner and an Analytics
  chart marker from it.
- **Demo:** a seeded generator produces an optional banwave dataset.

**Tech Stack:** Python 3.11, FastAPI, psycopg2, pytest, and a vanilla-JS
front-end with no build step. PostgreSQL 16 is used only for the opt-in
integration test and the screenshot.

**Spec:** `docs/superpowers/specs/2026-11-04-appeal-surge-design.md`. Read
it first. Section numbers below (§5.3 and so on) refer to it.

## Global Constraints

- The unit suite stays offline, with no DB, no API key and no `.env`. Plain
  `pytest` must pass. CI runs `pytest` and `node --test "tests/js/*.test.js"`.
- `api/main.py` endpoints are thin 1:1 wrappers over `dashboard/db.py`.
- There is no schema change and no new dependency.
- Use only existing design tokens (`--status-deny`, `--status-deny-bg`,
  `--status-deny-fg`) and no new hex colors. Every interpolated string goes
  through `esc()`.
- The defaults are `SURGE_THRESHOLD=100` and `SURGE_WINDOW_MINUTES=60`.
- The window is half-open: `window_start < created_at <= as_of`, where
  `as_of` is the newest `support_tickets.created_at`.
- The no-ban group label is exactly `(no ban record)`, with
  `ban_date: None`.
- Demo IDs are prefixed `TKT-SURGE-` and `USR-SURGE-`, and the demo files
  are `data/surge_tickets.json` and `data/surge_bans.json`.
- The banner has no action button.
- The base sample files and the existing screenshots must not change.
- Commit messages follow the repo style (`feat:`, `test:`, `docs:`) and end
  with the session's attribution trailer.

## Review Focus

1. **Newer non-surge data hides the demo surge.** For example, perf data
   from `scripts/generate_tickets.py` is dated 2026-06-09. It moves `as_of`
   past the surge, so no banner shows. That's correct under the spec's clock,
   so it's pinned by a test in Task 2 and documented in Task 6.
2. **One player appealing several times inside the window.** Bot floods do
   this. Each ticket counts, not each user. Pinned in Task 2.
3. **Several tickets sharing the exact `as_of` second.** All of them are
   counted. Pinned in Task 2.
4. **A detection method or date containing HTML.** The banner and tooltip
   must render it as text. This is a checked step in Task 5.
5. **`/api/surge` returning 500 or being unreachable.** The Dashboard still
   renders, with a muted "Surge check unavailable" line. This is a checked
   step in Task 5.

---

### Task 1: Surge settings (plus environment baseline)

**Files:**
- Modify: `config/settings.py`, adding after the `LLM_MAX_TOKENS` block
- Modify: `.env.example`
- Create: `tests/test_surge.py`

**Interfaces:**
- Produces: `settings._positive_int(name: str, raw: str | None, default: int) -> int`,
  `settings.SURGE_THRESHOLD: int`, and `settings.SURGE_WINDOW_MINUTES: int`

- [ ] **Step 1: Set up the environment and confirm a green baseline**

Run:
```bash
python -m venv venv
venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
venv/bin/pytest
```
Expected: all tests pass, and integration tests are deselected. If anything
fails before you've changed a line, stop and report it.

- [ ] **Step 2: Write the failing settings tests in `tests/test_surge.py`**

```python
import pytest
from config import settings

def test_positive_int_defaults_when_unset_or_empty():
    assert settings._positive_int("SURGE_THRESHOLD", None, 100) == 100
    assert settings._positive_int("SURGE_THRESHOLD", "", 100) == 100

def test_positive_int_parses_value():
    assert settings._positive_int("SURGE_WINDOW_MINUTES", "30", 60) == 30

@pytest.mark.parametrize("raw", ["0", "-5", "abc", "1.5"])
def test_positive_int_rejects_bad_values_naming_the_variable(raw):
    with pytest.raises(RuntimeError, match="SURGE_THRESHOLD"):
        settings._positive_int("SURGE_THRESHOLD", raw, 100)

def test_surge_defaults():
    # Holds while .env leaves both unset, as .env.example does.
    assert settings.SURGE_THRESHOLD == 100
    assert settings.SURGE_WINDOW_MINUTES == 60
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `venv/bin/pytest tests/test_surge.py -v`
Expected: FAIL with `AttributeError: ... '_positive_int'`.

- [ ] **Step 4: Implement `_positive_int` and the two constants**

The error message is
`f"{name} must be a positive whole number, got {raw!r}."`. Leave the
existing `_token_budget` untouched, because its message is asserted
elsewhere. Then:
```python
SURGE_THRESHOLD = _positive_int("SURGE_THRESHOLD", os.getenv("SURGE_THRESHOLD"), 100)
SURGE_WINDOW_MINUTES = _positive_int("SURGE_WINDOW_MINUTES", os.getenv("SURGE_WINDOW_MINUTES"), 60)
```
Add a short comment block above them that points to the README's
surge-detection section.

- [ ] **Step 5: Document the settings in `.env.example`**

Append both variables, commented out, with a one-line explanation:
"Appeal-surge alert: fire when at least SURGE_THRESHOLD tickets arrive
within SURGE_WINDOW_MINUTES of the newest ticket."

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `venv/bin/pytest -q`
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add config/settings.py .env.example tests/test_surge.py
git commit -m "feat: SURGE_THRESHOLD and SURGE_WINDOW_MINUTES settings"
```

---

### Task 2: Pure detection, `dashboard/surge.py`

**Files:**
- Create: `dashboard/surge.py`, using the same `sys.path` shim and module
  docstring style as `dashboard/cost.py`
- Modify: `tests/test_surge.py`

**Interfaces:**
- Produces:
  ```python
  NO_BAN_LABEL = "(no ban record)"
  def detect(rows: list[dict], as_of: datetime | None,
             threshold: int, window_minutes: int) -> dict
  ```
  - **`rows`:** dicts with `created_at: datetime`, `ban_date: date | None`
    and `detection_method: str | None`. A `None` method means no ban
    record.
  - **Return value:** exactly these keys: `active`, `as_of`, `window_start`,
    `window_minutes`, `threshold`, `count`, `top_cause` and `causes`.
  - **Each cause:** `{ban_date, detection_method, count, share}`.

- [ ] **Step 1: Write the failing detection tests**

Use a fixture time `AS_OF = datetime(2026, 4, 11, 9, 48)` and the helper
`r(minutes_before, ban_date=None, method=None)`. The helper returns a row
whose `created_at` is `AS_OF - timedelta(minutes=minutes_before)`. Tests and
their key assertions:

```python
def test_no_tickets():
    out = surge.detect([], None, 100, 60)
    assert out == {"active": False, "as_of": None, "window_start": None,
                   "window_minutes": 60, "threshold": 100, "count": 0,
                   "top_cause": None, "causes": []}

def test_below_threshold_reports_count_but_no_causes():
    out = surge.detect([r(1, D10, "stat_anomaly")] * 2, AS_OF, 3, 60)
    assert (out["active"], out["count"], out["top_cause"], out["causes"]) == (False, 2, None, [])
    assert out["window_start"] == AS_OF - timedelta(minutes=60)

def test_exactly_at_threshold_is_active():
    assert surge.detect([r(1, D10, "stat_anomaly")] * 3, AS_OF, 3, 60)["active"] is True

def test_window_is_half_open():
    rows = [r(60, D10, "stat_anomaly"), r(0, D10, "stat_anomaly")]  # boundary out, as_of in
    assert surge.detect(rows, AS_OF, 1, 60)["count"] == 1

def test_rows_outside_window_are_ignored():
    rows = [r(5, D10, "stat_anomaly"), r(500, D10, "stat_anomaly"), r(-5, D10, "stat_anomaly")]
    assert surge.detect(rows, AS_OF, 1, 60)["count"] == 1

def test_groups_by_ban_cluster_with_share():
    rows = [r(1, D10, "stat_anomaly")] * 3 + [r(2, D09, "cheat_engine_detection")]
    out = surge.detect(rows, AS_OF, 4, 60)
    assert out["top_cause"] == {"ban_date": D10, "detection_method": "stat_anomaly", "count": 3, "share": 0.75}
    assert out["causes"][1]["share"] == 0.25

def test_tie_goes_to_more_recent_ban_date_and_null_is_oldest():
    rows = [r(1, D09, "a"), r(1, D10, "b"), r(1)]
    out = surge.detect(rows, AS_OF, 3, 60)
    assert [c["detection_method"] for c in out["causes"]] == ["b", "a", surge.NO_BAN_LABEL]

def test_full_tie_breaks_alphabetically():
    rows = [r(1, D10, "zeta"), r(1, D10, "alpha")]
    assert surge.detect(rows, AS_OF, 2, 60)["causes"][0]["detection_method"] == "alpha"

def test_no_ban_bucket():
    out = surge.detect([r(1)] * 2, AS_OF, 2, 60)
    assert out["top_cause"] == {"ban_date": None, "detection_method": "(no ban record)", "count": 2, "share": 1.0}

def test_top_three_only():
    rows = [r(1, D10, m) for m in "abcd"]
    assert len(surge.detect(rows, AS_OF, 4, 60)["causes"]) == 3

# Review Focus 1-3
def test_later_quiet_ticket_moves_the_clock_past_the_surge():
    rows = [r(0, D10, "stat_anomaly")] * 5
    later = AS_OF + timedelta(days=60)
    assert surge.detect(rows + [{"created_at": later, "ban_date": None, "detection_method": None}],
                        later, 5, 60)["active"] is False

def test_repeat_appeals_from_one_player_each_count():
    assert surge.detect([r(1, D10, "stat_anomaly"), r(2, D10, "stat_anomaly")], AS_OF, 2, 60)["active"] is True

def test_all_tickets_at_the_as_of_second_count():
    assert surge.detect([r(0, D10, "x")] * 4, AS_OF, 4, 60)["count"] == 4
```
`D09 = date(2026, 4, 9)` and `D10 = date(2026, 4, 10)`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `venv/bin/pytest tests/test_surge.py -v`
Expected: the new tests FAIL with `ImportError` or `AttributeError` on
`surge`.

- [ ] **Step 3: Implement `detect`**

1. If `as_of is None`, return the empty result.
2. Filter the rows by the half-open window, and set `count = len(in_window)`.
3. If the count is below the threshold, return no causes.
4. Otherwise group by `(ban_date, detection_method or NO_BAN_LABEL)` and set
   `share = round(n / count, 2)`.
5. Order the groups by count descending. Break ties by `ban_date`
   descending, with `None` sorting oldest. Break remaining ties by
   `detection_method` ascending.
6. Keep the first 3 groups, and set `top_cause = causes[0]`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `venv/bin/pytest tests/test_surge.py -v`
Expected: all of them PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/surge.py tests/test_surge.py
git commit -m "feat: pure appeal-surge detection with ban-cluster correlation"
```

---

### Task 3: Query and endpoint, `db.get_surge()` and `GET /api/surge`

**Files:**
- Modify: `dashboard/db.py`, adding a new "Appeal surge" section before
  `get_ticket_date_bounds`
- Modify: `api/main.py`, adding the endpoint after `/api/costs`
- Modify: `tests/test_dashboard_db.py` and `tests/test_api.py`

**Interfaces:**
- Consumes: `surge.detect` (Task 2), `settings.SURGE_THRESHOLD` and
  `settings.SURGE_WINDOW_MINUTES` (Task 1)
- Produces: `db.get_surge(threshold: int | None = None, window_minutes: int | None = None) -> dict`.
  A `None` argument falls back to the setting. The overrides exist for the
  integration test. The function returns `surge.detect`'s dict.

- [ ] **Step 1: Write the failing tests**

In `tests/test_dashboard_db.py`, using the existing `_mock_conn` helper:

```python
def test_get_surge_empty_table(monkeypatch):
    conn, cur = _mock_conn(monkeypatch)
    cur.fetchone.return_value = {"as_of": None}
    out = db.get_surge()
    assert out["active"] is False and out["as_of"] is None
    assert cur.execute.call_count == 1          # no window query when there's nothing
    conn.close.assert_called_once()

def test_get_surge_queries_the_window_and_detects(monkeypatch):
    _, cur = _mock_conn(monkeypatch)
    as_of = datetime(2026, 4, 11, 9, 48)
    cur.fetchone.return_value = {"as_of": as_of}
    cur.fetchall.return_value = [{"created_at": as_of, "ban_date": date(2026, 4, 10),
                                  "detection_method": "stat_anomaly"}] * 2
    out = db.get_surge(threshold=2, window_minutes=60)
    assert out["active"] is True and out["count"] == 2
    _, params = cur.execute.call_args.args
    assert params == (as_of - timedelta(minutes=60), as_of)
```

In `tests/test_api.py`:

```python
def test_surge_passes_db_result_through(client, monkeypatch):
    payload = {"active": False, "count": 0, "causes": []}
    monkeypatch.setattr(main.db, "get_surge", Mock(return_value=payload))
    res = client.get("/api/surge")
    assert res.status_code == 200 and res.json() == payload
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `venv/bin/pytest tests/test_dashboard_db.py tests/test_api.py -v -k surge`
Expected: FAIL. `db` has no `get_surge`, and the endpoint returns 404.

- [ ] **Step 3: Implement `get_surge` and the endpoint**

Use one `RealDictCursor` and run two queries:
1. `SELECT MAX(created_at) AS as_of FROM support_tickets`. If that's
   `None`, return `surge.detect([], None, ...)` without running the second
   query.
2. Otherwise:
   ```sql
   SELECT st.created_at, bd.ban_date, bd.detection_method
   FROM support_tickets st LEFT JOIN ban_database bd ON bd.user_id = st.user_id
   WHERE st.created_at > %s AND st.created_at <= %s
   ```
   with the parameters `(window_start, as_of)`. Call `detect` on the rows.
3. Close the connection in a `finally` block.

Add `get_surge` to the db module docstring's function list if it keeps one.
The endpoint is `@app.get("/api/surge") def surge(): return db.get_surge()`.
Name the function `surge_status` so it doesn't shadow anything.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `venv/bin/pytest -q`
Expected: everything passes.

- [ ] **Step 5: Commit**

```bash
git add dashboard/db.py api/main.py tests/test_dashboard_db.py tests/test_api.py
git commit -m "feat: add surge query and GET /api/surge"
```

---

### Task 4: Demo banwave dataset

**Files:**
- Create: `scripts/generate_surge.py`
- Create: `data/surge_tickets.json` and `data/surge_bans.json` (generated
  output, committed)
- Modify: `tests/test_surge.py`

**Interfaces:**
- Consumes: `BODY_TEMPLATES`, `BAN_REASONS`, `NAME_PARTS_A` and
  `NAME_PARTS_B` from `scripts/generate_tickets.py`. Import them by putting
  the script's own directory on `sys.path`, then
  `from generate_tickets import ...`. Also consumes `surge.detect`.
- Produces: `generate_surge.generate() -> tuple[list[dict], list[dict]]`,
  returning (tickets, bans) in the sample-file shapes, and `main()`, which
  writes `{"tickets": [...]}` and `{"bans": [...]}` to `data/` with
  `indent=1`.

- [ ] **Step 1: Write the failing tests**

```python
DATA = Path(__file__).resolve().parent.parent / "data"

def _demo_rows():
    tickets = json.loads((DATA / "surge_tickets.json").read_text())["tickets"]
    bans = {b["user_id"]: b for b in json.loads((DATA / "surge_bans.json").read_text())["bans"]}
    rows = []
    for t in tickets:
        b = bans.get(t["user_id"])
        rows.append({"created_at": datetime.fromisoformat(t["created_at"]),
                     "ban_date": date.fromisoformat(b["ban_date"]) if b else None,
                     "detection_method": b["detection_method"] if b else None})
    return rows

def test_demo_dataset_triggers_the_stat_anomaly_surge():
    rows = _demo_rows()
    as_of = max(r["created_at"] for r in rows)
    out = surge.detect(rows, as_of, settings.SURGE_THRESHOLD, settings.SURGE_WINDOW_MINUTES)
    assert out["active"] is True
    assert (out["top_cause"]["detection_method"], out["top_cause"]["ban_date"]) == ("stat_anomaly", date(2026, 4, 10))

def test_demo_dataset_is_newer_than_the_base_sample():
    base = json.loads((DATA / "sample_tickets.json").read_text())["tickets"]
    surge_t = json.loads((DATA / "surge_tickets.json").read_text())["tickets"]
    assert min(t["created_at"] for t in surge_t) > max(t["created_at"] for t in base)

def test_committed_demo_files_match_the_generator():
    gen = _load_generate_surge()   # importlib.util.spec_from_file_location on scripts/generate_surge.py
    tickets, bans = gen.generate()
    assert {"tickets": tickets} == json.loads((DATA / "surge_tickets.json").read_text())
    assert {"bans": bans} == json.loads((DATA / "surge_bans.json").read_text())
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `venv/bin/pytest tests/test_surge.py -v -k demo`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Implement `scripts/generate_surge.py`**

Write the docstring in the style of `generate_tickets.py`: what it makes, the
ingest command, and the ID prefixes. Use `rng = random.Random(20260411)`
throughout, never the global `random`. Pin these exact values:

| Slice | Tickets | Ban |
|---|---|---|
| Banwave | 102 | `stat_anomaly`, `ban_date` `2026-04-10` |
| Runner-up | 11 | `cheat_engine_detection`, `2026-04-09` |
| No ban | 6 | none (the user has no ban entry) |
| Assorted | 5 | one each: `aim_lock_detection` 04-08, `speed_hack` 04-07, `connection_manipulation` 04-06, `manual_review` 04-05, `aim_lock_detection` 04-03 |

- **Timestamps:** 124 tickets in total. The first is exactly
  `2026-04-11T08:50:00` and the last exactly `2026-04-11T09:48:00`. The rest
  are seeded-random seconds in between. Sort them ascending, then number the
  IDs `TKT-SURGE-00001` onward in that order, with users `USR-SURGE-00001`
  onward.
- **Ticket fields:** `ticket_issue_category` is `"Request Account Unban"` and
  `status` is `"open"`.
- **Body text:** banwave tickets alternate between `BODY_TEMPLATES[1]`
  (hardware upgrade) and `BODY_TEMPLATES[4]` (loyal player). Everything else
  picks a template with `rng`. Fill the placeholders as `generate_tickets.py`
  does, using `rng`.
- **Ban fields:** `ban_reason` comes from `BAN_REASONS[method]`, and
  `ban_duration` is picked with `rng` from
  `["permanent", "30 days", "90 days"]`.
- **Slice order:** assign the slices to the shuffled ticket order with
  `rng.shuffle`, so the slices are interleaved in time.

- [ ] **Step 4: Generate the files and run the tests**

Run:
```bash
venv/bin/python scripts/generate_surge.py
venv/bin/pytest -q
```
Expected: the script prints "Wrote 124 tickets …" and "Wrote 118 bans …"
(124 tickets minus the 6 with no ban). All tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_surge.py data/surge_tickets.json data/surge_bans.json tests/test_surge.py
git commit -m "feat: seeded stat_anomaly banwave demo dataset"
```

---

### Task 5: Dashboard banner and Analytics chart marker

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consumes: the `GET /api/surge` JSON (spec §5.5)
- Produces: the state fields `surge` (object or `null`) and `surgeError`
  (string, `''` when fine), and the functions `loadSurge()`,
  `surgeSummary(surge) -> string` and `surgeBanner() -> string`

- [ ] **Step 1: Start a live stack**

1. **Database:** start a throwaway Postgres 16 under
   `/usr/lib/postgresql/16/bin` (`initdb`, then `pg_ctl start` on port 5432).
   Alternatively use `docker compose up -d`.
2. **Point at it:** export
   `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ticket_tech_titan`.
3. **Load data:** run `init_db.py`, then ingest the base sample. **Don't**
   load the surge files yet.
4. **Serve:** run `venv/bin/uvicorn api.main:app` in the background.
5. **Check:** `curl -s localhost:8000/api/surge` should show
   `"active":false`.

- [ ] **Step 2: Implement the fetch and state wiring**

- **`loadSurge()`** fetches `/api/surge`. On success it sets
  `{surge: json, surgeError: ''}`. On a non-OK response or a network error
  it sets `{surge: null, surgeError: err.message}`. It never throws.
- **First load:** call it from `loadInitial()` without awaiting it before
  the tickets.
- **Refresh:** call it from `refreshData()`, so the banner refreshes with
  the queue.
- **Defaults:** initialize `surge: null` and `surgeError: ''` in the
  initial state object.

- [ ] **Step 3: Implement the banner (spec §5.6)**

- **`surgeSummary(s)`** returns the sentence
  `"<count> appeals in the last <window_minutes> min — threshold is <threshold>. Likely cause: <method> bans on <date> (<pct>% of the surge)."`.
  - `pct` is `Math.round(share * 100)`.
  - When `top_cause.ban_date` is null, the cause clause reads
    `"Likely cause: (no ban record) (<pct>% of the surge)."`.
- **`surgeBanner()`** returns:
  - `''` when there's no active surge and no error
  - the muted line `Surge check unavailable: <error>` when `surgeError` is
    set
  - otherwise a `.blueprint` frame with `CORNERS`, the background
    `var(--status-deny-bg)` and the color `var(--status-deny-fg)`. Inside
    it:
    - an `h5` "Appeal surge" with a right-aligned muted
      "as of <as_of YYYY-MM-DD HH:mm>"
    - the summary sentence
    - an "Also: …" muted line listing `causes[1..]` as
      `method · date (pct%)`, shown only when they exist
- **Placement:** in `renderDashboard()`, insert `surgeBanner()` between the
  intro paragraph and the metric grid.
- **Escaping:** every interpolated value goes through `esc()`.

- [ ] **Step 4: Implement the chart marker (spec §5.7)**

In `renderAnalytics()`'s volume SVG:
- **When to draw:** only when `s.surge && s.surge.active` and
  `as_of.slice(0, 10)` is one of the `volEntries` days.
- **What to draw:** at that day's `volDots` x-position, a dashed `line`
  (`stroke-dasharray="3 3"`, `stroke="var(--status-deny)"`) from y=10 to
  y=190, carrying a `<title>` with `esc(surgeSummary(s.surge))`.
- **Label:** a 10px "SURGE" `text` at the top of the line, filled with
  `var(--status-deny)`.
- **Dot:** that day's dot is filled `var(--status-deny)` instead of the
  accent.

- [ ] **Step 5: Check the inactive state in the browser**

Reload `localhost:8000` with Playwright (bundled chromium, no channel).
- **Dashboard:** there's no banner and no "unavailable" line.
- **Analytics:** there's no marker.

- [ ] **Step 6: Check the active state**

1. Ingest the surge files:
   ```bash
   venv/bin/python ingestion/ingest_ticket.py --tickets data/surge_tickets.json --bans data/surge_bans.json
   ```
2. Click **Refresh data**.
3. **Dashboard:** the banner shows "124 appeals in the last 60 min",
   "stat_anomaly bans on 2026-04-10 (82% of the surge)", and an "Also:" line
   with `cheat_engine_detection` and `(no ban record)`.
4. **Analytics:** the marker sits on 2026-04-11. Setting **To** to
   2026-04-10 removes it.
5. **Themes:** check both light and dark.

- [ ] **Step 7: Check Review Focus 4 and 5**

- **Escaping (Focus 4):** temporarily run
  `UPDATE ban_database SET detection_method = '<i>x</i>' WHERE user_id = 'USR-SURGE-00001'`.
  Refresh, and confirm the banner and tooltip show the literal text
  `<i>x</i>` rather than italics.
- **Restore:** reset that row's method to its original value, which you can
  read from `data/surge_bans.json`.
- **Endpoint down (Focus 5):** use Playwright
  `page.route("**/api/surge", lambda r: r.fulfill(status=500))`. Confirm the
  Dashboard renders the metric cards plus the muted
  "Surge check unavailable: …" line.

- [ ] **Step 8: Run the suites**

Run:
```bash
venv/bin/pytest -q
node --test "tests/js/*.test.js"
```
Expected: both pass.

- [ ] **Step 9: Commit**

```bash
git add web/app.js
git commit -m "feat: surge banner on the dashboard and marker on the volume chart"
```

---

### Task 6: Integration test, docs and screenshot

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `scripts/capture_screenshots.py`
- Create: `docs/screenshots/dashboard-surge.png`
- Modify: `README.md`

**Interfaces:**
- Consumes: `db.get_surge(threshold, window_minutes)` (Task 3)

> **A deliberate deviation from spec §6.** The integration test seeds its
> own rows rather than ingesting `data/surge_*.json`. Whatever is already in
> a developer's database decides `as_of`. For example, perf data dated
> 2026-06 would bury an April surge and make the test fail spuriously.
> Seeding rows at 2099 keeps them the newest. The intent is unchanged: a
> live round trip reports an active surge with the right cause.

- [ ] **Step 1: Write the integration test**

Add a fixture `seeded_surge`. It:
- inserts 5 committed tickets (`TKT-INTEG-SURGE-<uuid>-<n>`) at
  `2099-01-01T00:0n:00`
- gives 4 of them a `ban_database` row with method `integ_wave` and date
  `2098-12-31`
- deletes those tickets and bans in teardown

Test:
```python
def test_surge_detected_end_to_end(seeded_surge):
    out = dashboard_db.get_surge(threshold=5, window_minutes=60)
    assert out["active"] is True and out["count"] == 5
    assert out["top_cause"]["detection_method"] == "integ_wave"
    assert out["top_cause"]["share"] == 0.8
```
Run: `venv/bin/pytest -m integration -k surge -v` against the Task 5
database.
Expected: PASS.

- [ ] **Step 2: Add a surge-only capture mode to `capture_screenshots.py`**

Add two `argparse` flags:
- **`--surge`:** captures *only* `dashboard-surge.png`. That's the
  Dashboard in dark mode, full page. It never overwrites the other
  screenshots, which were taken from an evaluated database.
- **`--channel`:** defaults to `msedge`. Pass `""` to use Playwright's
  bundled chromium.

Update the docstring to match.

- [ ] **Step 3: Capture the screenshot**

With the surge loaded, run:
```bash
venv/bin/python scripts/capture_screenshots.py --surge --channel ""
```
Expected: `docs/screenshots/dashboard-surge.png` exists and shows the banner.
`git status` shows no other screenshot changed.

- [ ] **Step 4: Update the README**

| Where | Change |
|---|---|
| How it works, step 4 | mention the surge alert |
| Screenshots | a "Surge alert" entry with `dashboard-surge.png` |
| Getting started, step 3 | an optional "Try the surge demo" sub-step with the ingest command, plus notes that it adds 124 unevaluated tickets, that running the pipeline without `--limit` evaluates them too (an extra ~$1–2), and that newer data (e.g. perf tickets) moves the surge clock past the demo |
| Views table, Dashboard row | add "appeal-surge alert" |
| Configuration table | `SURGE_THRESHOLD` and `SURGE_WINDOW_MINUTES` |
| API reference | `GET /api/surge`, which returns whether a surge is active, its count, and the top-3 ban clusters behind it |
| Design notes | one bullet: the clock is the newest ticket, not the wall clock, so it's deterministic and demoable. The trade-off is stale data, which is mitigated by the "as of" stamp. A baseline-relative trigger is the natural next step |
| Project structure | `dashboard/surge.py` and `scripts/generate_surge.py` |

- [ ] **Step 5: Run the final verification**

Run:
```bash
venv/bin/pytest -q
node --test "tests/js/*.test.js"
venv/bin/pytest -m integration -k surge
```
Expected: all three pass.

- [ ] **Step 6: Commit and push**

```bash
git add tests/test_integration.py scripts/capture_screenshots.py docs/screenshots/dashboard-surge.png README.md
git commit -m "docs: document appeal-surge detection, add surge screenshot and integration test"
git push -u origin c-/friendly-fermi-69zvfy
```
Opening the PR (which closes #3) waits for the owner's go-ahead.
