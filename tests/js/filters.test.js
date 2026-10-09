/* filters.test.js — tests for web/filters.js.
 *
 * Node's built-in runner, no packages to install (Node 22+, which expands
 * the quoted glob itself, so the same line works in PowerShell and bash):
 *
 *   node --test "tests/js/*.test.js"
 */

'use strict';

const { describe, test } = require('node:test');
const assert = require('node:assert/strict');

const { filterQueue, dateBounds, followBound } = require('../../web/filters.js');

// Rows shaped like GET /api/tickets, newest first as the API returns them.
// T3 is unevaluated, so its AI columns are null.
const TICKETS = [
  { ticket_id: 'T4', status: 'closed', created_at: '2026-06-04T10:30:00', ai_category: 'Admitted to Cheating', confidence_score: 0.88, admitted_cheating: true },
  { ticket_id: 'T3', status: 'open', created_at: '2026-06-03T00:00:00', ai_category: null, confidence_score: null, admitted_cheating: null },
  { ticket_id: 'T2', status: 'pending', created_at: '2026-06-02T23:59:59', ai_category: 'Likely Legitimate', confidence_score: 0.4, admitted_cheating: false },
  { ticket_id: 'T1', status: 'open', created_at: '2026-06-01T08:15:00', ai_category: 'Auto-Deny', confidence_score: 0.95, admitted_cheating: false },
];

// The rail with nothing filtered out: every box ticked, the full confidence
// window, no date bounds.
function rail(overrides) {
  return Object.assign({
    cats: { 'Auto-Deny': true, 'Likely Legitimate': true, 'Admitted to Cheating': true, 'Templated/Bot Appeal': true, 'Needs Review': true, 'Not yet evaluated': true },
    statuses: { open: true, pending: true, closed: true },
    confMin: 0,
    confMax: 1,
    admittedOnly: false,
    dateFrom: '',
    dateTo: '',
  }, overrides);
}

const ids = (rows) => rows.map((t) => t.ticket_id);

describe('filterQueue', () => {
  test('passes every ticket with the rail at its defaults', () => {
    assert.deepEqual(ids(filterQueue(TICKETS, rail())), ['T4', 'T3', 'T2', 'T1']);
  });

  test('drops unticked AI categories', () => {
    const f = rail({ cats: Object.assign({}, rail().cats, { 'Auto-Deny': false }) });
    assert.deepEqual(ids(filterQueue(TICKETS, f)), ['T4', 'T3', 'T2']);
  });

  test('files unevaluated tickets under "Not yet evaluated"', () => {
    const f = rail({ cats: Object.assign({}, rail().cats, { 'Not yet evaluated': false }) });
    assert.deepEqual(ids(filterQueue(TICKETS, f)), ['T4', 'T2', 'T1']);
  });

  test('drops unticked statuses', () => {
    const f = rail({ statuses: { open: true, pending: false, closed: true } });
    assert.deepEqual(ids(filterQueue(TICKETS, f)), ['T4', 'T3', 'T1']);
  });

  test('applies the confidence window inclusively and leaves unscored rows alone', () => {
    // 0.4 and 0.88 sit exactly on the window's edges; T3 has no score.
    const f = rail({ confMin: 0.4, confMax: 0.88 });
    assert.deepEqual(ids(filterQueue(TICKETS, f)), ['T4', 'T3', 'T2']);
  });

  test('keeps only confirmed admissions when admittedOnly is set', () => {
    // T3's null means "not evaluated", which is not an admission.
    assert.deepEqual(ids(filterQueue(TICKETS, rail({ admittedOnly: true }))), ['T4']);
  });

  test('scopes to the date range, including both end days whatever the time', () => {
    // T2 lands a second before midnight on the 2nd, T3 at midnight on the 3rd.
    const f = rail({ dateFrom: '2026-06-02', dateTo: '2026-06-03' });
    assert.deepEqual(ids(filterQueue(TICKETS, f)), ['T3', 'T2']);
  });

  test('treats an empty date bound as open', () => {
    assert.deepEqual(ids(filterQueue(TICKETS, rail({ dateFrom: '2026-06-03' }))), ['T4', 'T3']);
    assert.deepEqual(ids(filterQueue(TICKETS, rail({ dateTo: '2026-06-01' }))), ['T1']);
  });

  test('composes the date range with the other filters', () => {
    // The range alone keeps T2-T4; the status filter then drops T4 and the
    // category filter drops T3.
    const f = rail({
      dateFrom: '2026-06-02',
      dateTo: '2026-06-04',
      statuses: { open: true, pending: true, closed: false },
      cats: Object.assign({}, rail().cats, { 'Not yet evaluated': false }),
    });
    assert.deepEqual(ids(filterQueue(TICKETS, f)), ['T2']);
  });

  test('returns nothing for an inverted date range', () => {
    assert.deepEqual(filterQueue(TICKETS, rail({ dateFrom: '2026-06-04', dateTo: '2026-06-01' })), []);
  });
});

describe('dateBounds', () => {
  test('finds the earliest and latest submission dates whatever the order', () => {
    const expected = { min: '2026-06-01', max: '2026-06-04' };
    assert.deepEqual(dateBounds(TICKETS), expected);
    assert.deepEqual(dateBounds(TICKETS.slice().reverse()), expected);
  });

  test('returns empty bounds when there are no tickets', () => {
    assert.deepEqual(dateBounds([]), { min: '', max: '' });
  });
});

// A refresh that brings in a ticket from the 5th, after a page loaded with
// data ending on the 4th.
describe('followBound', () => {
  test('moves an edge that sat on the old bound', () => {
    assert.equal(followBound('2026-06-04', '2026-06-04', '2026-06-05'), '2026-06-05');
  });

  test('leaves an edge the analyst moved', () => {
    assert.equal(followBound('2026-06-02', '2026-06-04', '2026-06-05'), '2026-06-02');
  });

  test('leaves a cleared edge open', () => {
    assert.equal(followBound('', '2026-06-04', '2026-06-05'), '');
  });

  test('fills in an edge set before any tickets had loaded', () => {
    assert.equal(followBound('', '', '2026-06-05'), '2026-06-05');
  });
});
