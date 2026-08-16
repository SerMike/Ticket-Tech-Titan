/* app.js — Ticket Tech Titan single-page dashboard.
 *
 * Vanilla-JS port of the design prototype's logic class (see
 * docs/design/Ticket Tech Titan.dc.html): one
 * state object, one render() that rebuilds #app, delegated event
 * listeners. Data comes from the FastAPI endpoints in api/main.py;
 * all filtering/aggregation stays client-side, matching the prototype.
 */

'use strict';

// Configurable flags (kept as constants, per the handoff README).
const CONFIG = {
  defaultTheme: 'system',        // 'system' | 'light' | 'dark'
  confidenceAsPercent: false,    // table confidence as 92% instead of 0.92
  showRawAggregates: true,
};

const state = {
  view: 'dashboard', theme: 'light', tickets: [],
  cats: { 'Auto-Deny': true, 'Likely Legitimate': true, 'Admitted to Cheating': true, 'Templated/Bot Appeal': true, 'Needs Review': true, 'Not yet evaluated': true },
  statuses: { open: true, pending: true, closed: true },
  confMin: 0, confMax: 1, admittedOnly: false,
  selectedId: null, showReasoning: false,
  dateFrom: '', dateTo: '', aggTab: 'Categories',
  toastText: '', toastVisible: false,
  // ai_summary/ai_reasoning aren't in the queue join — fetched per ticket
  // from /api/tickets/{id}/evaluation and cached by id.
  evaluations: {},
};

function setState(patch) {
  Object.assign(state, patch);
  render();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const ICONS = {
  refresh: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg>',
  sun: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.93 4.93 1.41 1.41"></path><path d="m17.66 17.66 1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.34 17.66-1.41 1.41"></path><path d="m19.07 4.93-1.41 1.41"></path></svg>',
  moon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path></svg>',
};

const CORNERS = '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';

const TAG_BASE = 'white-space: nowrap; font-family: var(--font-heading); letter-spacing: 0.04em; text-transform: uppercase; font-size: 10px;';
const TAG_MAP = {
  'Auto-Deny': 'background: var(--status-deny-bg); color: var(--status-deny-fg);',
  'Admitted to Cheating': 'background: var(--status-admit-bg); color: var(--status-admit-fg);',
  'Needs Review': 'background: var(--status-review-bg); color: var(--status-review-fg);',
  'Likely Legitimate': 'background: var(--status-legit-bg); color: var(--status-legit-fg);',
  'Templated/Bot Appeal': 'background: var(--status-bot-bg); color: var(--status-bot-fg);',
};

function tagStyle(cat) {
  return TAG_BASE + (TAG_MAP[cat] ||
    'color: color-mix(in srgb, var(--color-text) 45%, transparent); border: 1px dashed var(--color-divider); background: transparent;');
}

function tagHtml(cat) {
  const label = cat || 'Not yet evaluated';
  return '<span class="tag" style="' + tagStyle(cat) + '">' + esc(label) + '</span>';
}

let toastTimer = null;
function toast(text) {
  clearTimeout(toastTimer);
  setState({ toastText: text, toastVisible: true });
  toastTimer = setTimeout(() => setState({ toastVisible: false }), 2600);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  setState({ theme });
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

async function fetchTickets() {
  const res = await fetch('/api/tickets');
  if (!res.ok) throw new Error('GET /api/tickets failed: ' + res.status);
  return res.json();
}

async function ensureEvaluation(ticketId) {
  if (!ticketId || state.evaluations[ticketId] !== undefined) return;
  state.evaluations[ticketId] = null;  // in-flight marker; keeps re-renders from refetching
  try {
    const res = await fetch('/api/tickets/' + encodeURIComponent(ticketId) + '/evaluation');
    setState({ evaluations: Object.assign({}, state.evaluations, { [ticketId]: res.ok ? await res.json() : {} }) });
  } catch (err) {
    setState({ evaluations: Object.assign({}, state.evaluations, { [ticketId]: {} }) });
  }
}

async function loadInitial() {
  const tickets = await fetchTickets();
  const dates = tickets.map((t) => t.created_at.slice(0, 10)).sort();
  setState({
    tickets,
    dateFrom: dates[0] || '',
    dateTo: dates[dates.length - 1] || '',
    selectedId: tickets[0] ? tickets[0].ticket_id : null,
  });
}

async function refreshData() {
  try {
    const tickets = await fetchTickets();
    const stillThere = tickets.some((t) => t.ticket_id === state.selectedId);
    setState({
      tickets,
      evaluations: {},
      selectedId: stillThere ? state.selectedId : (tickets[0] ? tickets[0].ticket_id : null),
    });
    toast('Data refreshed from the latest DB state.');
  } catch (err) {
    toast('Refresh failed: ' + err.message);
  }
}

async function changeStatus(ticketId, newStatus) {
  const ticket = state.tickets.find((t) => t.ticket_id === ticketId);
  if (!ticket) return;
  const oldStatus = ticket.status;
  // Optimistic update + toast; revert with an error toast on failure.
  setState({ tickets: state.tickets.map((t) => (t.ticket_id === ticketId ? Object.assign({}, t, { status: newStatus }) : t)) });
  toast('Ticket ' + ticketId + ': ' + oldStatus + ' → ' + newStatus);
  try {
    const res = await fetch('/api/tickets/' + encodeURIComponent(ticketId) + '/status', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || ('HTTP ' + res.status));
    }
  } catch (err) {
    setState({ tickets: state.tickets.map((t) => (t.ticket_id === ticketId ? Object.assign({}, t, { status: oldStatus }) : t)) });
    toast('Status update failed: ' + err.message);
  }
}

// ---------------------------------------------------------------------------
// Derived data (ported from the prototype's renderVals)
// ---------------------------------------------------------------------------

function filteredQueue() {
  const s = state;
  return s.tickets.filter((t) => {
    const cat = t.ai_category || 'Not yet evaluated';
    if (!s.cats[cat]) return false;
    if (!s.statuses[t.status]) return false;
    if (t.confidence_score != null && (t.confidence_score < s.confMin || t.confidence_score > s.confMax)) return false;
    if (s.admittedOnly && t.admitted_cheating !== true) return false;
    return true;
  });
}

function analyticsSet() {
  const s = state;
  return s.tickets.filter((t) => {
    const d = t.created_at.slice(0, 10);
    return (!s.dateFrom || d >= s.dateFrom) && (!s.dateTo || d <= s.dateTo);
  });
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

function renderNav() {
  const links = ['Dashboard', 'Queue', 'Analytics'].map((label) => {
    const view = label.toLowerCase();
    const active = state.view === view;
    const style = 'font-family: var(--font-heading); font-weight: 600; font-size: 15px; letter-spacing: 0.05em; text-transform: uppercase; text-decoration: none;'
      + ' color: ' + (active ? 'var(--color-accent)' : 'inherit') + ';'
      + ' border-bottom: ' + (active ? '2px solid var(--color-accent)' : '2px solid transparent') + '; padding-bottom: 2px;';
    return '<a href="#" data-action="nav" data-view="' + view + '"' + (active ? ' aria-current="page"' : '') + ' style="' + style + '">' + label + '</a>';
  }).join('');

  return '<div style="border-bottom: 1px solid var(--color-divider);">'
    + '<nav class="nav" style="max-width: 1280px; margin: 0 auto; padding: var(--space-3) var(--space-6);">'
    + '<div class="nav-brand" style="display: flex; align-items: baseline; gap: 10px; margin-right: auto;">'
    + '<span style="letter-spacing: 0.04em; text-transform: uppercase;">Ticket Tech Titan</span>'
    + '<span class="text-muted" style="font-family: var(--font-body); font-weight: 400; font-size: 12px;">AI-powered ban appeal review</span>'
    + '</div>'
    + links
    + '<button class="btn btn-secondary" data-action="refresh" style="gap: 8px;">' + ICONS.refresh + 'Refresh data</button>'
    + '<button class="btn btn-secondary btn-icon" data-action="toggle-theme" title="Toggle light/dark" aria-label="Toggle light/dark theme">'
    + (state.theme === 'dark' ? ICONS.sun : ICONS.moon)
    + '</button>'
    + '</nav></div>';
}

function renderDashboard() {
  const s = state;
  const openCount = s.tickets.filter((t) => t.status === 'open').length;
  const latestDay = s.tickets.length ? s.tickets[0].created_at.slice(0, 10) : '';
  const autoDeniedToday = s.tickets.filter((t) => t.ai_category === 'Auto-Deny' && t.created_at.slice(0, 10) === latestDay).length;
  const needsReview = s.tickets.filter((t) => t.ai_category === 'Needs Review').length;
  const cards = [
    { kicker: 'Open tickets', value: String(openCount), meta: 'Queue depth right now' },
    { kicker: 'Auto-denied today', value: String(autoDeniedToday), meta: 'Deterministic override — ' + latestDay },
    { kicker: 'Needs review', value: String(needsReview), meta: 'AI-flagged backlog for analysts' },
  ];

  return '<section>'
    + '<h6 style="color: var(--color-accent);">Overview</h6>'
    + '<h1 style="margin-bottom: var(--space-2);">Dashboard</h1>'
    + '<p class="text-muted" style="max-width: 560px;">Overview of the ticket queue and recent AI activity. Use the navigation above to open the queue or the analytics page.</p>'
    + '<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-6); margin-top: var(--space-8);">'
    + cards.map((card) =>
      '<div class="card blueprint" style="padding: var(--space-6); gap: var(--space-3);">' + CORNERS
      + '<div class="card-kicker">' + esc(card.kicker) + '</div>'
      + '<div style="font-family: var(--font-heading); font-weight: 600; font-size: 56px; line-height: 1;">' + esc(card.value) + '</div>'
      + '<div class="card-meta">' + esc(card.meta) + '</div>'
      + '</div>').join('')
    + '</div>'
    + '<div style="display: flex; gap: var(--space-3); margin-top: var(--space-8);">'
    + '<button class="btn btn-primary blueprint" data-action="go-queue">' + CORNERS + 'Open the queue</button>'
    + '<button class="btn btn-secondary" data-action="go-analytics">View analytics</button>'
    + '</div>'
    + '</section>';
}

function renderQueue() {
  const s = state;
  const filtered = filteredQueue();

  const checkboxList = (items, action) => items.map((f) =>
    '<label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer;">'
    + '<input type="checkbox"' + (f.checked ? ' checked' : '') + ' data-action="' + action + '" data-label="' + esc(f.label) + '" style="accent-color: var(--color-accent); width: 14px; height: 14px; margin: 0;">'
    + '<span>' + esc(f.label) + '</span></label>').join('');

  const catFilters = Object.keys(s.cats).map((label) => ({ label, checked: s.cats[label] }));
  const statusFilters = Object.keys(s.statuses).map((label) => ({ label, checked: s.statuses[label] }));

  const rail = '<aside class="blueprint" style="padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-4); position: sticky; top: 20px;">' + CORNERS
    + '<h6 style="margin: 0;">Filters</h6>'
    + '<div><div style="font-size: 12px; margin-bottom: 6px; color: color-mix(in srgb, var(--color-text) 70%, transparent);">AI category</div>'
    + '<div style="display: flex; flex-direction: column; gap: 5px;">' + checkboxList(catFilters, 'cat-filter') + '</div></div>'
    + '<div><div style="font-size: 12px; margin-bottom: 6px; color: color-mix(in srgb, var(--color-text) 70%, transparent);">Status</div>'
    + '<div style="display: flex; flex-direction: column; gap: 5px;">' + checkboxList(statusFilters, 'status-filter') + '</div></div>'
    + '<div><div style="font-size: 12px; margin-bottom: 6px; color: color-mix(in srgb, var(--color-text) 70%, transparent);">Confidence score · ' + s.confMin.toFixed(2) + ' – ' + s.confMax.toFixed(2) + '</div>'
    + '<div style="display: flex; flex-direction: column; gap: 6px;">'
    + '<input type="range" min="0" max="1" step="0.05" value="' + s.confMin + '" data-action="conf-min" style="accent-color: var(--color-accent); width: 100%;">'
    + '<input type="range" min="0" max="1" step="0.05" value="' + s.confMax + '" data-action="conf-max" style="accent-color: var(--color-accent); width: 100%;">'
    + '</div></div>'
    + '<label style="display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer;">'
    + '<input type="checkbox"' + (s.admittedOnly ? ' checked' : '') + ' data-action="admitted-only" style="accent-color: var(--color-accent); width: 14px; height: 14px; margin: 0;">'
    + '<span>Admitted cheating only</span></label>'
    + '</aside>';

  const th = (label, center) => '<th style="position: sticky; top: 0; background: var(--color-bg);' + (center ? ' text-align: center;' : '') + '">' + label + '</th>';
  const glyph = (v) => (v == null ? { g: '', c: 'inherit' } : v ? { g: '☑', c: 'var(--color-accent-600)' } : { g: '☐', c: 'color-mix(in srgb, var(--color-text) 35%, transparent)' });

  const rows = filtered.map((t) => {
    const selected = t.ticket_id === s.selectedId;
    const gc = glyph(t.admitted_cheating), ge = glyph(t.admitted_exploit);
    const confLabel = t.confidence_score != null
      ? (CONFIG.confidenceAsPercent ? Math.round(t.confidence_score * 100) + '%' : t.confidence_score.toFixed(2))
      : '';
    const conf = t.confidence_score != null
      ? '<div style="display: flex; align-items: center; gap: 8px;">'
        + '<div style="width: 72px; height: 5px; background: var(--color-neutral-200); flex: none;"><div style="height: 100%; width: ' + Math.round(t.confidence_score * 100) + '%; background: var(--color-accent);"></div></div>'
        + '<span style="font-size: 12px;">' + confLabel + '</span></div>'
      : '';
    return '<tr data-action="select-row" data-id="' + esc(t.ticket_id) + '" style="cursor: pointer; background: ' + (selected ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)' : 'transparent') + ';">'
      + '<td style="font-size: 12px; font-family: ui-monospace, monospace;">' + esc(t.ticket_id) + '</td>'
      + '<td>' + esc(t.user_name) + '</td>'
      + '<td style="font-size: 13px;">' + esc(t.ticket_issue_category) + '</td>'
      + '<td>' + tagHtml(t.ai_category) + '</td>'
      + '<td>' + conf + '</td>'
      + '<td style="text-align: center; font-size: 15px; color: ' + gc.c + ';">' + gc.g + '</td>'
      + '<td style="text-align: center; font-size: 15px; color: ' + ge.c + ';">' + ge.g + '</td>'
      + '<td style="font-size: 13px;">' + esc(t.status) + '</td>'
      + '<td style="font-size: 12px; white-space: nowrap;">' + esc(t.created_at.slice(0, 16).replace('T', ' ')) + '</td>'
      + '</tr>';
  }).join('');

  const table = '<div>'
    + '<div class="text-muted" style="font-size: 12px; margin-bottom: var(--space-2);">Showing ' + filtered.length + ' of ' + s.tickets.length + ' tickets — click a row to inspect it.</div>'
    + '<div class="blueprint" id="queue-scroll" style="max-height: 480px; overflow: auto;">' + CORNERS
    + '<table class="table" style="min-width: 900px;"><thead><tr>'
    + th('Ticket ID') + th('Player') + th('User category') + th('AI category') + th('Confidence')
    + th('Adm. cheat', true) + th('Adm. exploit', true) + th('Status') + th('Submitted')
    + '</tr></thead><tbody>' + rows + '</tbody></table></div>'
    + (s.tickets.length > 0 && filtered.length === 0
      ? '<p class="text-muted" style="margin-top: var(--space-3);">No tickets match the current filters.</p>' : '')
    + '</div>';

  return '<section>'
    + '<h6 style="color: var(--color-accent);">Workflow</h6>'
    + '<h1 style="margin-bottom: var(--space-6);">Ticket queue</h1>'
    + '<div style="display: grid; grid-template-columns: 232px 1fr; gap: var(--space-6); align-items: start;">'
    + rail
    + '<div style="display: flex; flex-direction: column; gap: var(--space-6); min-width: 0;">'
    + table
    + renderDetail()
    + '</div></div></section>';
}

function renderDetail() {
  const s = state;
  const sel = s.tickets.find((t) => t.ticket_id === s.selectedId) || null;
  if (!sel) return '';
  const admLabel = (v) => (v == null ? '— Not evaluated' : v ? 'Yes' : 'No');
  const statusOption = (v) => '<option value="' + v + '"' + (sel.status === v ? ' selected' : '') + '>' + v + '</option>';
  const evalRow = s.evaluations[sel.ticket_id] || {};

  const banRecord = sel.ban_reason
    ? '<div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; font-size: 13px;">'
      + '<span class="text-muted">Reason</span><span>' + esc(sel.ban_reason) + '</span>'
      + '<span class="text-muted">Detection</span><span style="font-family: ui-monospace, monospace; font-size: 12px;">' + esc(sel.detection_method) + '</span>'
      + '<span class="text-muted">Duration</span><span>' + esc(sel.ban_duration) + '</span>'
      + '<span class="text-muted">Ban date</span><span>' + esc(sel.ban_date) + '</span>'
      + '</div>'
    : '<div class="blueprint" style="padding: var(--space-3); font-size: 13px; border-color: var(--color-accent);">' + CORNERS
      + '<strong style="color: var(--color-accent-700);">No ban record</strong> — potential wrongful ban.'
      + '</div>';

  const evaluation = sel.ai_category
    ? '<div style="display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: var(--space-6); margin-bottom: var(--space-4);">'
      + '<div><div class="text-muted" style="font-size: 12px; margin-bottom: 4px;">Category</div>' + tagHtml(sel.ai_category) + '</div>'
      + '<div><div class="text-muted" style="font-size: 12px; margin-bottom: 4px;">Confidence · ' + (sel.confidence_score != null ? Math.round(sel.confidence_score * 100) + '%' : '') + '</div>'
      + '<div style="width: 100%; max-width: 180px; height: 6px; background: var(--color-neutral-200); margin-top: 8px;"><div style="height: 100%; width: ' + (sel.confidence_score != null ? Math.round(sel.confidence_score * 100) : 0) + '%; background: var(--color-accent);"></div></div></div>'
      + '<div style="font-size: 13px; display: flex; flex-direction: column; gap: 3px;">'
      + '<div><span class="text-muted">Admitted cheating:</span> <strong>' + admLabel(sel.admitted_cheating) + '</strong></div>'
      + '<div><span class="text-muted">Admitted exploit:</span> <strong>' + admLabel(sel.admitted_exploit) + '</strong></div>'
      + '</div></div>'
      + '<div class="text-muted" style="font-size: 12px; margin-bottom: 5px;">Summary</div>'
      + '<div class="blueprint" style="padding: var(--space-3); font-size: 14px;">' + CORNERS + esc(evalRow.ai_summary) + '</div>'
      + '<button class="btn btn-ghost" data-action="toggle-reasoning" style="margin-top: var(--space-3);">' + (s.showReasoning ? 'Hide full reasoning' : 'Show full reasoning') + '</button>'
      + (s.showReasoning ? '<p style="font-size: 13px; margin-top: var(--space-2); text-wrap: pretty;" class="text-muted">' + esc(evalRow.ai_reasoning) + '</p>' : '')
    : '<p class="text-muted" style="font-size: 14px;">Not yet evaluated. Run the evaluation pipeline to populate.</p>';

  return '<div class="blueprint" style="padding: var(--space-6);">' + CORNERS
    + '<div style="display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-4); border-bottom: 1px solid var(--color-divider); padding-bottom: var(--space-3); margin-bottom: var(--space-4);">'
    + '<h3 style="margin: 0;">Ticket ' + esc(sel.ticket_id) + '</h3>' + tagHtml(sel.ai_category)
    + '</div>'
    + '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-8);">'
    + '<div>'
    + '<h6 style="color: var(--color-accent);">Appeal</h6>'
    + '<div style="display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; font-size: 13px; margin-bottom: var(--space-3);">'
    + '<span class="text-muted">Player</span><strong>' + esc(sel.user_name) + '</strong>'
    + '<span class="text-muted">User ID</span><span style="font-family: ui-monospace, monospace; font-size: 12px;">' + esc(sel.user_id) + '</span>'
    + '<span class="text-muted">Submitted</span><span>' + esc(sel.created_at.slice(0, 16).replace('T', ' ')) + '</span>'
    + '<span class="text-muted">User category</span><span>' + esc(sel.ticket_issue_category) + '</span>'
    + '</div>'
    + '<h4 style="margin-bottom: var(--space-2);">' + esc(sel.ticket_title) + '</h4>'
    + '<p style="font-size: 14px; text-wrap: pretty;">' + esc(sel.ticket_body) + '</p>'
    + '<div style="margin-top: var(--space-4);">'
    + '<div style="font-size: 12px; margin-bottom: 5px; color: color-mix(in srgb, var(--color-text) 70%, transparent);">Status</div>'
    + '<select class="input" data-action="status-select" style="max-width: 200px;">'
    + statusOption('open') + statusOption('pending') + statusOption('closed')
    + '</select></div>'
    + '</div>'
    + '<div><h6 style="color: var(--color-accent);">Ban record</h6>' + banRecord + '</div>'
    + '</div>'
    + '<div style="border-top: 1px solid var(--color-divider); margin-top: var(--space-6); padding-top: var(--space-4);">'
    + '<h6 style="color: var(--color-accent);">AI evaluation</h6>' + evaluation
    + '</div></div>';
}

function renderAnalytics() {
  const s = state;
  const aset = analyticsSet();
  const evaluated = aset.filter((t) => t.ai_category != null);
  const admC = evaluated.filter((t) => t.admitted_cheating === true).length;
  const admE = evaluated.filter((t) => t.admitted_exploit === true).length;
  const pct = (n, d) => (d ? (100 * n / d).toFixed(1) + '%' : '0.0%');

  const metrics = [
    { kicker: 'Evaluated tickets', value: String(evaluated.length), meta: 'In selected date range' },
    { kicker: 'Not evaluated', value: String(aset.length - evaluated.length), meta: 'Awaiting the pipeline' },
    { kicker: 'Cheating admissions', value: String(admC), meta: pct(admC, evaluated.length) + ' of evaluated' },
    { kicker: 'Exploit admissions', value: String(admE), meta: pct(admE, evaluated.length) + ' of evaluated' },
  ];

  const CAT_ORDER = ['Auto-Deny', 'Admitted to Cheating', 'Needs Review', 'Templated/Bot Appeal', 'Likely Legitimate'];
  const CAT_FILL = { 'Auto-Deny': 'var(--status-deny)', 'Admitted to Cheating': 'var(--status-admit)', 'Needs Review': 'var(--status-review)', 'Templated/Bot Appeal': 'var(--status-bot)', 'Likely Legitimate': 'var(--status-legit)' };
  const catCounts = {};
  for (const t of evaluated) catCounts[t.ai_category] = (catCounts[t.ai_category] || 0) + 1;
  const catEntries = CAT_ORDER.filter((c) => catCounts[c]).map((c) => [c, catCounts[c]]).sort((a, b) => b[1] - a[1]);
  const catMax = Math.max(1, ...catEntries.map((e) => e[1]));

  const barRow = (cols, label, fillPct, fill, count, mono) =>
    '<div style="display: grid; grid-template-columns: ' + cols + '; gap: 10px; align-items: center;">'
    + '<div style="font-size: ' + (mono ? '11px; font-family: ui-monospace, monospace;' : '12px;') + ' text-align: right; color: color-mix(in srgb, var(--color-text) 75%, transparent);">' + esc(label) + '</div>'
    + '<div style="height: 18px; background: var(--color-neutral-200);"><div style="height: 100%; width: ' + fillPct + '%; background: ' + fill + ';"></div></div>'
    + '<div style="font-size: 12px;">' + esc(count) + '</div>'
    + '</div>';

  const catBars = catEntries.map(([label, count]) =>
    barRow('150px 1fr 30px', label, Math.round(100 * count / catMax), CAT_FILL[label], String(count))).join('');

  const admBars = [
    barRow('150px 1fr 48px', 'Admitted cheating', evaluated.length ? Math.round(100 * admC / evaluated.length) : 0, 'var(--status-admit)', pct(admC, evaluated.length)),
    barRow('150px 1fr 48px', 'Admitted exploit', evaluated.length ? Math.round(100 * admE / evaluated.length) : 0, 'var(--status-exploit)', pct(admE, evaluated.length)),
  ].join('');

  const detCounts = {};
  for (const t of aset) { const k = t.detection_method || '(no ban record)'; detCounts[k] = (detCounts[k] || 0) + 1; }
  const detEntries = Object.entries(detCounts).sort((a, b) => b[1] - a[1]);
  const detMax = Math.max(1, ...detEntries.map((e) => e[1]));
  const detBars = detEntries.map(([label, count]) =>
    barRow('175px 1fr 30px', label, Math.round(100 * count / detMax), 'var(--color-accent-500)', String(count), true)).join('');

  // Volume over time
  const volCounts = {};
  for (const t of aset) { const d = t.created_at.slice(0, 10); volCounts[d] = (volCounts[d] || 0) + 1; }
  const volEntries = Object.entries(volCounts).sort((a, b) => a[0].localeCompare(b[0]));
  const volMax = Math.max(1, ...volEntries.map((e) => e[1]));
  const X0 = 36, X1 = 592, Y0 = 190, Y1 = 14;
  const volDots = volEntries.map(([d, c], i) => ({
    x: (volEntries.length > 1 ? X0 + (X1 - X0) * i / (volEntries.length - 1) : (X0 + X1) / 2).toFixed(1),
    y: (Y0 - (Y0 - Y1) * c / volMax).toFixed(1),
  }));
  const volPoints = volDots.map((p) => p.x + ',' + p.y).join(' ');
  const volSvg = '<svg viewBox="0 0 600 220" style="width: 100%; display: block;">'
    + '<line x1="36" y1="190" x2="592" y2="190" stroke="var(--color-divider)" stroke-width="1"></line>'
    + '<line x1="36" y1="10" x2="36" y2="190" stroke="var(--color-divider)" stroke-width="1"></line>'
    + '<polyline points="' + volPoints + '" fill="none" stroke="var(--color-accent)" stroke-width="1.5"></polyline>'
    + volDots.map((d) => '<circle cx="' + d.x + '" cy="' + d.y + '" r="2.5" fill="var(--color-accent)"></circle>').join('')
    + '<text x="36" y="208" font-size="10" fill="currentColor" opacity="0.55">' + (volEntries.length ? volEntries[0][0] : '') + '</text>'
    + '<text x="592" y="208" font-size="10" fill="currentColor" opacity="0.55" text-anchor="end">' + (volEntries.length ? volEntries[volEntries.length - 1][0] : '') + '</text>'
    + '<text x="30" y="14" font-size="10" fill="currentColor" opacity="0.55" text-anchor="end">' + volMax + '</text>'
    + '<text x="30" y="193" font-size="10" fill="currentColor" opacity="0.55" text-anchor="end">0</text>'
    + '</svg>';

  // Confidence histogram
  const scores = evaluated.map((t) => t.confidence_score).filter((v) => v != null);
  const bins = new Array(20).fill(0);
  for (const v of scores) bins[Math.min(19, Math.floor(v * 20))]++;
  const binMax = Math.max(1, ...bins);
  const confBins = bins.map((c, i) =>
    '<div title="' + (i / 20).toFixed(2) + '–' + ((i + 1) / 20).toFixed(2) + ': ' + c + '"'
    + ' style="flex: 1; height: ' + Math.round(100 * c / binMax) + '%; min-height: 1px; background: ' + (c ? 'var(--color-accent-500)' : 'var(--color-neutral-200)') + ';"></div>').join('');

  // Raw aggregates
  const aggTabs = ['Categories', 'Detection methods', 'Volume', 'Confidence scores'].map((label) =>
    '<label class="seg-opt"><input type="radio" name="aggtab"' + (s.aggTab === label ? ' checked' : '') + ' data-action="agg-tab" data-label="' + label + '">' + label + '</label>').join('');
  let aggCol1 = 'ai_category', aggCol2 = 'count', aggRows = catEntries.map(([a, b]) => ({ a, b: String(b) }));
  if (s.aggTab === 'Detection methods') { aggCol1 = 'detection_method'; aggRows = detEntries.map(([a, b]) => ({ a, b: String(b) })); }
  else if (s.aggTab === 'Volume') { aggCol1 = 'date'; aggRows = volEntries.map(([a, b]) => ({ a, b: String(b) })); }
  else if (s.aggTab === 'Confidence scores') {
    aggCol1 = 'statistic'; aggCol2 = 'value';
    const n = scores.length, mean = n ? scores.reduce((x, y) => x + y, 0) / n : 0;
    const sorted = scores.slice().sort((a, b) => a - b);
    const q = (p) => (n ? sorted[Math.min(n - 1, Math.floor(p * n))] : 0);
    const std = n ? Math.sqrt(scores.reduce((acc, v) => acc + (v - mean) * (v - mean), 0) / n) : 0;
    aggRows = [['count', String(n)], ['mean', mean.toFixed(3)], ['std', std.toFixed(3)], ['min', (sorted[0] || 0).toFixed(2)], ['25%', q(0.25).toFixed(2)], ['50%', q(0.5).toFixed(2)], ['75%', q(0.75).toFixed(2)], ['max', (sorted[n - 1] || 0).toFixed(2)]].map(([a, b]) => ({ a, b }));
  }

  const panel = (title, body, titleMargin) =>
    '<div class="blueprint" style="padding: var(--space-4);">' + CORNERS
    + '<h5 style="margin-bottom: ' + (titleMargin || 'var(--space-4)') + ';">' + title + '</h5>' + body + '</div>';

  return '<section>'
    + '<h6 style="color: var(--color-accent);">Signals</h6>'
    + '<h1 style="margin-bottom: var(--space-6);">Analytics</h1>'
    + '<div style="display: flex; gap: var(--space-4); align-items: end; margin-bottom: var(--space-6);">'
    + '<div class="field"><label>From</label><input type="date" class="input" value="' + esc(s.dateFrom) + '" data-action="date-from" style="width: 170px;"></div>'
    + '<div class="field"><label>To</label><input type="date" class="input" value="' + esc(s.dateTo) + '" data-action="date-to" style="width: 170px;"></div>'
    + '</div>'
    + '<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-6); margin-bottom: var(--space-8);">'
    + metrics.map((m) =>
      '<div class="card blueprint" style="padding: var(--space-4); gap: var(--space-2);">' + CORNERS
      + '<div class="card-kicker">' + esc(m.kicker) + '</div>'
      + '<div style="font-family: var(--font-heading); font-weight: 600; font-size: 40px; line-height: 1;">' + esc(m.value) + '</div>'
      + '<div class="card-meta">' + esc(m.meta) + '</div>'
      + '</div>').join('')
    + '</div>'
    + '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-6); margin-bottom: var(--space-6);">'
    + panel('AI category breakdown', '<div style="display: flex; flex-direction: column; gap: 10px;">' + catBars + '</div>')
    + panel('Admission rates', '<div style="display: flex; flex-direction: column; gap: 10px;">' + admBars + '</div>'
      + '<p class="text-muted" style="font-size: 12px; margin: var(--space-4) 0 0;">Share of evaluated tickets where the appeal itself admits the offense.</p>')
    + panel('Detection method volume', '<div style="display: flex; flex-direction: column; gap: 10px;">' + detBars + '</div>')
    + panel('Ticket volume over time', volSvg, 'var(--space-2)')
    + '</div>'
    + '<div class="blueprint" style="padding: var(--space-4); margin-bottom: var(--space-6);">' + CORNERS
    + '<h5 style="margin-bottom: var(--space-4);">Confidence score distribution</h5>'
    + '<div style="display: flex; align-items: flex-end; gap: 3px; height: 150px;">' + confBins + '</div>'
    + '<div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 6px;" class="text-muted"><span>0.0</span><span>0.5</span><span>1.0</span></div>'
    + '</div>'
    + (CONFIG.showRawAggregates
      ? '<div><h5 style="margin-bottom: var(--space-3);">Raw aggregates</h5>'
        + '<div class="seg" style="margin-bottom: var(--space-4);">' + aggTabs + '</div>'
        + '<div class="blueprint" style="max-width: 560px;">' + CORNERS
        + '<table class="table"><thead><tr><th>' + aggCol1 + '</th><th style="text-align: right;">' + aggCol2 + '</th></tr></thead><tbody>'
        + aggRows.map((r) => '<tr><td>' + esc(r.a) + '</td><td style="text-align: right; font-family: ui-monospace, monospace; font-size: 13px;">' + esc(r.b) + '</td></tr>').join('')
        + '</tbody></table></div></div>'
      : '')
    + '</section>';
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function render() {
  const app = document.getElementById('app');
  const scroller = document.getElementById('queue-scroll');
  const scroll = scroller ? { top: scroller.scrollTop, left: scroller.scrollLeft } : null;

  let viewHtml = '';
  if (state.view === 'dashboard') viewHtml = renderDashboard();
  else if (state.view === 'queue') viewHtml = renderQueue();
  else if (state.view === 'analytics') viewHtml = renderAnalytics();

  const toastHtml = state.toastVisible
    ? '<div class="blueprint elev-md" style="position: fixed; right: 24px; bottom: 24px; padding: var(--space-3) var(--space-4); background: var(--color-bg); font-size: 13px; z-index: 50;">' + CORNERS + esc(state.toastText) + '</div>'
    : '';

  app.innerHTML = '<div style="min-height: 100vh; background: var(--color-bg); color: var(--color-text); font-family: var(--font-body);">'
    + renderNav()
    + '<main style="max-width: 1280px; margin: 0 auto; padding: var(--space-8) var(--space-6) 80px;">' + viewHtml + '</main>'
    + toastHtml
    + '</div>';

  const newScroller = document.getElementById('queue-scroll');
  if (scroll && newScroller) { newScroller.scrollTop = scroll.top; newScroller.scrollLeft = scroll.left; }

  const sel = state.tickets.find((t) => t.ticket_id === state.selectedId);
  if (sel && sel.ai_category) ensureEvaluation(sel.ticket_id);
}

// ---------------------------------------------------------------------------
// Events (delegated)
// ---------------------------------------------------------------------------

document.getElementById('app').addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  if (action === 'nav') { e.preventDefault(); setState({ view: el.dataset.view }); }
  else if (action === 'refresh') refreshData();
  else if (action === 'toggle-theme') {
    const t = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('ttt-theme', t);
    applyTheme(t);
  }
  else if (action === 'go-queue') setState({ view: 'queue' });
  else if (action === 'go-analytics') setState({ view: 'analytics' });
  else if (action === 'select-row') setState({ selectedId: el.dataset.id, showReasoning: false });
  else if (action === 'toggle-reasoning') setState({ showReasoning: !state.showReasoning });
});

document.getElementById('app').addEventListener('change', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  if (action === 'cat-filter') setState({ cats: Object.assign({}, state.cats, { [el.dataset.label]: !state.cats[el.dataset.label] }) });
  else if (action === 'status-filter') setState({ statuses: Object.assign({}, state.statuses, { [el.dataset.label]: !state.statuses[el.dataset.label] }) });
  else if (action === 'conf-min') setState({ confMin: Math.min(parseFloat(el.value), state.confMax) });
  else if (action === 'conf-max') setState({ confMax: Math.max(parseFloat(el.value), state.confMin) });
  else if (action === 'admitted-only') setState({ admittedOnly: !state.admittedOnly });
  else if (action === 'status-select') changeStatus(state.selectedId, el.value);
  else if (action === 'date-from') setState({ dateFrom: el.value });
  else if (action === 'date-to') setState({ dateTo: el.value });
  else if (action === 'agg-tab') setState({ aggTab: el.dataset.label });
});

// ---------------------------------------------------------------------------
// Boot: theme, system-mode listener, initial data
// ---------------------------------------------------------------------------

(function boot() {
  const stored = localStorage.getItem('ttt-theme');
  let theme = stored || CONFIG.defaultTheme;
  if (theme === 'system') theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  state.theme = theme;

  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener('change', (e) => {
    if (!localStorage.getItem('ttt-theme') && CONFIG.defaultTheme === 'system') applyTheme(e.matches ? 'dark' : 'light');
  });

  render();
  loadInitial().catch((err) => toast('Failed to load tickets: ' + err.message));
})();
