# Handoff: Ticket Tech Titan — Industry dashboard redesign

## Overview
A full redesign of the Ticket Tech Titan Streamlit dashboard (repo: `Ticket-Tech-Titan`) in the **Industry** design system: a blueprint/wireframe aesthetic — square corners, hairline borders, "+" registration marks, Barlow Condensed headings over Barlow body, steel-blue accent — with a **light/dark theme toggle** and **semantic status colors** for AI categories. Three views: Dashboard (summary metrics), Queue (filters + table + ticket detail), Analytics (metrics, charts, raw aggregates).

## Implementation plan (agreed with the owner)
**Replace the Streamlit UI with this front-end, keeping the existing Python data layer.**

1. Keep `dashboard/db.py` exactly as is — it is the seam.
2. Add a small FastAPI app (e.g. `api/main.py`, ~80 lines) exposing `db.py` over JSON:

| Endpoint | Maps to | Notes |
|---|---|---|
| `GET /api/tickets` | `db.get_all_tickets()` | Full joined rows (ticket + AI eval + ban record), newest first |
| `GET /api/tickets/{id}` | `db.get_ticket_detail(id)` | 404 when missing |
| `GET /api/tickets/{id}/evaluation` | `db.get_ai_evaluation(id)` | `ai_summary`, `ai_reasoning` |
| `PATCH /api/tickets/{id}/status` | `db.update_ticket_status(id, status)` | Body `{"status": "open"|"pending"|"closed"}`; 400 on ValueError |
| `GET /api/analytics?date_from=&date_to=` | `db.get_analytics_data(...)` | category_breakdown, admission_rates, detection_method_counts, volume_over_time, confidence_scores |
| `GET /api/stats` | `db.get_summary_stats()` | open_count, auto_denied_today, needs_review |
| `GET /api/date-bounds` | `db.get_ticket_date_bounds()` | min/max ticket dates |

3. Serve the front-end as static files from the same FastAPI app (`StaticFiles`), so there are no CORS concerns.
4. In the front-end, replace the bundled synthetic data module (`data/tickets-data.js`) with `fetch()` calls to the endpoints above. Everything else — filtering, detail view, charts, theme toggle — is already client-side logic to recreate.
5. The "Refresh data" button becomes a real re-fetch (it currently only shows a toast).

## About the design files
The files in this bundle are **design references created in HTML** — a working prototype showing intended look and behavior, not production code to ship as-is. `Ticket Tech Titan.dc.html` uses a proprietary streaming-component runtime (`<x-dc>`, `<sc-for>`, `<sc-if>`, `{{ holes }}`, a `Component` logic class); **recreate it in your chosen front-end stack** (vanilla JS + templates, or a small React/Preact app — the logic class translates 1:1 to a React component). All markup, inline styles, and the complete view logic are in that one file and are meant to be read and ported.

- `Ticket Tech Titan.dc.html` — the full design: template (markup + inline styles + theme CSS in the `<helmet>` block) and logic class (filtering, chart math, theme handling) at the bottom.
- `industry-styles.css` — the Industry design-system stylesheet (tokens + component classes). Ship this verbatim; the design links it on every page.
- `data/tickets-data.js` — the synthetic joined dataset the prototype renders. Its shape **is the API contract**: each row is a ticket joined with its AI evaluation and ban record (same columns as `db.py`'s `_QUEUE_SELECT`). Delete once real endpoints exist.

## Fidelity
**High-fidelity.** Recreate pixel-perfectly: exact tokens, spacing variables, type, and component classes below. All values not listed inline come from `industry-styles.css` variables.

## Theming — light/dark
Theme is an attribute on the root element: `<html data-theme="dark">` (absent/anything else = light). All colors are CSS variables, overridden per theme — components never branch on theme.

Behavior (implemented in the prototype's logic class, port as-is):
- On load: `localStorage['ttt-theme']` wins; otherwise `prefers-color-scheme` via `matchMedia` (default mode is "system").
- Toggle button (sun/moon, top-right of nav) flips light↔dark and persists to `localStorage['ttt-theme']`.
- While in system mode (no stored choice), listen for `matchMedia('(prefers-color-scheme: dark)')` changes.
- `body { transition: background 0.2s, color 0.2s; }`.

### Token overrides (copy verbatim from the `<helmet>` `<style>` in the HTML)
**Light (base, warm off-white ground):**
```css
:root:not([data-theme="dark"]) {
  --color-bg: oklch(0.955 0.012 85);      /* warm beige off-white */
  --color-surface: oklch(0.93 0.014 85);
  --color-divider: color-mix(in srgb, #1d1f20 18%, transparent);
}
```
**Dark (same warm undertone; full ramp + shadow overrides are in the HTML — copy the whole `[data-theme="dark"]` block):**
```css
:root[data-theme="dark"] {
  --color-bg: oklch(0.21 0.012 85);       /* warm charcoal */
  --color-surface: oklch(0.26 0.014 85);
  --color-text: #e6e7e9;
  --color-accent: #7ea3c9;
  --color-divider: color-mix(in srgb, #e6e7e9 18%, transparent);
  /* neutral + accent 100–900 ramps are FLIPPED (100 = darkest) — see HTML */
}
```

### Semantic status colors (both themes; copy the two blocks from the HTML)
OKLCH hues on the accent's lightness/chroma register. Each has `--status-*` (chart fill), `--status-*-bg` (tag fill), `--status-*-fg` (tag text):

| Category | Hue | Light: base / bg / fg |
|---|---|---|
| Auto-Deny | red 25 | `oklch(0.56 0.13 25)` / `oklch(0.92 0.04 25)` / `oklch(0.38 0.12 25)` |
| Admitted to Cheating | amber 65 | `oklch(0.62 0.11 65)` / `oklch(0.93 0.045 70)` / `oklch(0.4 0.09 60)` |
| Needs Review | gold 92 | `oklch(0.72 0.11 92)` / `oklch(0.94 0.06 95)` / `oklch(0.44 0.08 85)` |
| Likely Legitimate | green 155 | `oklch(0.58 0.1 155)` / `oklch(0.92 0.045 155)` / `oklch(0.37 0.08 155)` |
| Templated/Bot Appeal | neutral | `var(--color-neutral-500)` / `-200` / `-800` |
| (Admitted exploit, chart only) | purple 300 | `oklch(0.56 0.11 300)` |

Dark variants (lighter base, dark bg ~0.32 L, light fg ~0.87 L) are in the HTML. "Not yet evaluated" tag: transparent bg, 1px dashed `var(--color-divider)`, 45%-mix muted text.

## Screens / Views
Shell shared by all views: content in a `max-width: 1280px` centered container, `padding: var(--space-8) var(--space-6) 80px`.

### Top nav (replaces the Streamlit sidebar)
Full-width bar with `border-bottom: 1px solid var(--color-divider)`; inner `.nav` (1280px, `padding: var(--space-3) var(--space-6)`).
- Brand: "TICKET TECH TITAN" (Barlow Condensed 600, 18px, uppercase, letter-spacing 0.04em) + muted 12px "AI-powered ban appeal review", baseline-aligned.
- Links: DASHBOARD / QUEUE / ANALYTICS — Barlow Condensed 600 15px uppercase, letter-spacing 0.05em; active link: `color: var(--color-accent)` + `border-bottom: 2px solid var(--color-accent)` (inactive: transparent 2px border, inherit color); `aria-current="page"` on active.
- Right: "Refresh data" `.btn.btn-secondary` with Lucide `refresh-cw` at stroke 1.5 (14px), and a 36px `.btn.btn-secondary.btn-icon` theme toggle showing Lucide `sun` (dark mode) / `moon` (light mode) at 15px.

### 1. Dashboard
- Kicker `h6` "Overview" in `var(--color-accent)`, `h1` "Dashboard", muted intro paragraph (max-width 560px).
- 3-column grid (`gap: var(--space-6)`, `margin-top: var(--space-8)`) of blueprint metric cards — `.card.blueprint` + four `<i class="corner tl/tr/bl/br">`, `padding: var(--space-6)`: `.card-kicker` label, value in Barlow Condensed 600 56px/1, `.card-meta` caption.
  - Open tickets (count of `status === 'open'`) — "Queue depth right now"
  - Auto-denied today (Auto-Deny tickets on latest ingest date) — "Deterministic override — {date}"
  - Needs review (count of AI category Needs Review) — "AI-flagged backlog for analysts"
- Buttons: "Open the queue" (`.btn.btn-primary.blueprint` **with corner marks** — the one solid object) + "View analytics" (`.btn.btn-secondary`).

### 2. Queue
Kicker "Workflow", `h1` "Ticket queue". Grid `232px 1fr`, gap `var(--space-6)`.

**Filter rail** (left, sticky `top: 20px`, blueprint frame, `padding: var(--space-4)`):
- `h6` "Filters".
- "AI category" checkbox list: the 5 categories + "Not yet evaluated", all checked by default. Native checkboxes 14px with `accent-color: var(--color-accent)`, 13px labels, 5px row gap.
- "Status" checkbox list: open / pending / closed, all checked.
- "Confidence score · {min} – {max}": two stacked range sliders (min, max), step 0.05, accent-colored; min clamps ≤ max and vice versa. Only constrains rows that have a score (unevaluated rows are governed by the category filter).
- "Admitted cheating only" checkbox.

**Table** (right): muted 12px caption "Showing N of M tickets — click a row to inspect it." above a blueprint-framed scroll container (`max-height: 480px`, sticky `thead` cells with `background: var(--color-bg)`), `.table` with `min-width: 900px`. Columns: Ticket ID (12px monospace) · Player · User category (13px) · AI category (tag: 10px Barlow Condensed uppercase, letter-spacing 0.04em, square, status bg/fg) · Confidence (72×5px track `var(--color-neutral-200)`, accent fill at score%, 12px numeric label — `0.92` or `92%` per config) · Adm. cheat / Adm. exploit (centered ☑ in `var(--color-accent-600)` / ☐ at 35% text mix; blank when unevaluated) · Status · Submitted (`YYYY-MM-DD HH:mm`). Row: `cursor: pointer`; selected row bg `color-mix(in srgb, var(--color-accent) 12%, transparent)`. Empty state: muted "No tickets match the current filters."

**Ticket detail** (below table, blueprint frame, `padding: var(--space-6)`, shown for the selected row — first row selected by default):
- Header row (bottom divider): `h3` "Ticket {id}" + AI category tag.
- Two columns (gap `var(--space-8)`):
  - **Appeal**: accent `h6`; meta grid (Player bold, User ID monospace 12px, Submitted, User category); `h4` appeal title; 14px body (`text-wrap: pretty`); Status `select.input` (max-width 200px, options open/pending/closed) → on change PATCH status, then toast "Ticket {id}: {old} → {new}" (fixed bottom-right blueprint card, `background: var(--color-bg)`, `.elev-md`, auto-dismiss 2.6s).
  - **Ban record**: accent `h6`; meta grid (Reason, Detection monospace, Duration, Ban date) — or, when no ban record, an accent-bordered blueprint callout: "**No ban record** — potential wrongful ban." (bold lead in `var(--color-accent-700)`).
- **AI evaluation** (below top divider): 3-col grid `1fr 1fr 1.4fr` — Category tag; "Confidence · {pct}%" with 180×6px accent progress bar; Admitted cheating/exploit as "Yes"/"No"/"— Not evaluated" (bold values). Then muted "Summary" label + blueprint-framed 14px summary box; "Show full reasoning" `.btn.btn-ghost` toggling a muted 13px reasoning paragraph. Unevaluated: muted "Not yet evaluated. Run the evaluation pipeline to populate."

### 3. Analytics
Kicker "Signals", `h1` "Analytics".
- Date range: two `.field` date inputs (From/To, 170px), defaulting to the data's min/max ticket dates; all sections below recompute on change (string date comparison on `created_at[:10]`).
- 4-col metric card grid (same card recipe as Dashboard, value 40px): Evaluated tickets / Not evaluated / Cheating admissions ({pct}% of evaluated) / Exploit admissions.
- 2×2 chart grid, each panel a blueprint frame (`padding: var(--space-4)`) with an `h5` title:
  - **AI category breakdown** — horizontal bars: grid `150px 1fr 30px`, 18px track `var(--color-neutral-200)`, fill = `--status-*` per category, width % of max, count at right; sorted desc.
  - **Admission rates** — same recipe (`150px 1fr 48px`): Admitted cheating (`--status-admit`), Admitted exploit (`--status-exploit`), % labels; footnote muted 12px.
  - **Detection method volume** — same recipe (`175px 1fr 30px`), 11px monospace labels, fill `var(--color-accent-500)`; includes "(no ban record)" bucket.
  - **Ticket volume over time** — SVG 600×220: hairline axes (`var(--color-divider)`), accent polyline stroke 1.5 + 2.5px dots, one point per day; 10px labels: start/end date, max count, 0.
- **Confidence score distribution** — full-width blueprint panel: 20 bins, flex bars (3px gap, 150px tall area), fill `var(--color-accent-500)` (empty bins show a 1px `var(--color-neutral-200)` sliver), height % of max bin; 0.0 / 0.5 / 1.0 scale row; per-bar `title` tooltip "0.55–0.60: 3".
- **Raw aggregates** (config-hideable) — `.seg` segmented control (Categories / Detection methods / Volume / Confidence scores; radio inputs) + blueprint `.table` (max-width 560px), right-aligned monospace value column. Confidence tab shows count/mean/std/min/25%/50%/75%/max.

## Interactions & behavior
- View switching is client-side (single-page, three views); nav links `preventDefault`.
- All filtering/aggregation is client-side over the fetched ticket list (50–550 rows — fine in-browser; re-fetch on Refresh).
- Hover/focus states come from `industry-styles.css` (accent-ramp hovers, 2px accent `:focus-visible` ring) — do not restyle.
- Status change should optimistically update the row and show the toast; surface a 400 as an error toast.
- Configurable flags in the prototype (keep as constants or settings): default theme (`system`/`light`/`dark`), confidence as percent vs decimal in the table, show/hide raw aggregates.

## State
`view`, `theme`, `tickets[]`, category/status filter sets, `confMin/confMax`, `admittedOnly`, `selectedId`, `showReasoning`, `dateFrom/dateTo`, `aggTab`, toast. All derived data (filtered rows, chart series, histogram bins, describe() stats) is computed per render from these — see `renderVals()` in the HTML for the exact math.

## Design tokens
Everything comes from `industry-styles.css` variables (`--color-*` ramps, `--font-heading`/`--font-body`, `--space-1..8` = 3.4/6.8/10.2/13.6/20.4/27.2px, `--shadow-*`) plus the theme/status overrides above. Fonts: Barlow + Barlow Condensed via Google Fonts (imported by the stylesheet). Radius is always 0 on framed objects (blueprint grammar). Never hard-code a hex the tokens already carry.

## Assets
No images. Icons are inline Lucide SVGs at stroke-width 1.5: `refresh-cw`, `sun`, `moon` (paths embedded in the HTML).

## Screenshots
`screenshots/` holds rendered references of every view in both themes: `light-dashboard.png`, `light-queue.png`, `light-analytics.png`, `dark-dashboard.png`, `dark-queue.png`, `dark-analytics.png`.

## Files
- `Ticket Tech Titan.dc.html` — full design reference (markup, styles, logic)
- `industry-styles.css` — design-system stylesheet (ship verbatim)
- `data/tickets-data.js` — synthetic dataset = API response contract
