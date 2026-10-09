/* filters.js — pure filtering helpers behind the dashboard's views.
 *
 * Kept free of the DOM and of app.js's state so the same file runs in two
 * places: as a classic <script> loaded ahead of app.js, where these functions
 * become globals, and under Node's built-in test runner through the
 * module.exports guard at the bottom (tests in tests/js/filters.test.js).
 */

'use strict';

// created_at is an ISO 8601 string; its first ten characters are the
// YYYY-MM-DD submission date, which orders correctly as a plain string.
function ticketDate(ticket) {
  return ticket.created_at.slice(0, 10);
}

// Inclusive at both ends. An empty bound is open, so a cleared date input
// stops filtering rather than hiding everything.
function inDateRange(ticket, from, to) {
  const d = ticketDate(ticket);
  return (!from || d >= from) && (!to || d <= to);
}

// Earliest and latest submission dates; empty strings when there are no
// tickets, matching an unset date input.
function dateBounds(tickets) {
  const dates = tickets.map(ticketDate).sort();
  return { min: dates[0] || '', max: dates[dates.length - 1] || '' };
}

// Where a date-range edge belongs after a refresh. An edge sitting on the old
// data bound means "everything", so it moves with the bound and newly arrived
// tickets show up; an edge the analyst moved stays where they put it.
function followBound(edge, oldBound, newBound) {
  return edge === oldBound ? newBound : edge;
}

// The queue's filter rail applied to the full ticket list. `f` holds the
// rail's state: `cats` and `statuses` as {label: checked} maps, the
// confMin/confMax window, `admittedOnly`, and the dateFrom/dateTo range.
function filterQueue(tickets, f) {
  return tickets.filter((t) => {
    const cat = t.ai_category || 'Not yet evaluated';
    if (!f.cats[cat]) return false;
    if (!f.statuses[t.status]) return false;
    // Unevaluated rows have no score; the category filter governs them.
    if (t.confidence_score != null && (t.confidence_score < f.confMin || t.confidence_score > f.confMax)) return false;
    if (f.admittedOnly && t.admitted_cheating !== true) return false;
    if (!inDateRange(t, f.dateFrom, f.dateTo)) return false;
    return true;
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { inDateRange, dateBounds, followBound, filterQueue };
}
