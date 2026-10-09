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

const { filterQueue } = require('../../web/filters.js');

// Rows shaped like GET /api/tickets, newest first as the API returns them.
// T3 is unevaluated, so its AI columns are null.
const TICKETS = [
  { ticket_id: 'T4', status: 'closed', created_at: '2026-06-04T10:30:00', ai_category: 'Admitted to Cheating', confidence_score: 0.88, admitted_cheating: true },
  { ticket_id: 'T3', status: 'open', created_at: '2026-06-03T00:00:00', ai_category: null, confidence_score: null, admitted_cheating: null },
  { ticket_id: 'T2', status: 'pending', created_at: '2026-06-02T23:59:59', ai_category: 'Likely Legitimate', confidence_score: 0.4, admitted_cheating: false },
  { ticket_id: 'T1', status: 'open', created_at: '2026-06-01T08:15:00', ai_category: 'Auto-Deny', confidence_score: 0.95, admitted_cheating: false },
];

// The rail as the page loads it: every box ticked and the full confidence
// window.
function rail(overrides) {
  return Object.assign({
    cats: { 'Auto-Deny': true, 'Likely Legitimate': true, 'Admitted to Cheating': true, 'Templated/Bot Appeal': true, 'Needs Review': true, 'Not yet evaluated': true },
    statuses: { open: true, pending: true, closed: true },
    confMin: 0,
    confMax: 1,
    admittedOnly: false,
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
});
