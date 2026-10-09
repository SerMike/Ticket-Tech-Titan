/* filters.js — pure filtering helpers behind the dashboard's views.
 *
 * Kept free of the DOM and of app.js's state so the same file runs in two
 * places: as a classic <script> loaded ahead of app.js, where these functions
 * become globals, and under Node's built-in test runner through the
 * module.exports guard at the bottom (tests in tests/js/filters.test.js).
 */

'use strict';

// The queue's filter rail applied to the full ticket list. `f` holds the
// rail's state: `cats` and `statuses` as {label: checked} maps, the
// confMin/confMax window, and `admittedOnly`.
function filterQueue(tickets, f) {
  return tickets.filter((t) => {
    const cat = t.ai_category || 'Not yet evaluated';
    if (!f.cats[cat]) return false;
    if (!f.statuses[t.status]) return false;
    // Unevaluated rows have no score; the category filter governs them.
    if (t.confidence_score != null && (t.confidence_score < f.confMin || t.confidence_score > f.confMax)) return false;
    if (f.admittedOnly && t.admitted_cheating !== true) return false;
    return true;
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { filterQueue };
}
