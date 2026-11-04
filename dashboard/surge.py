"""surge.py — Detect an appeal surge and name the ban cluster behind it.

Why detection is pure
---------------------
A surge is a question about a window of tickets, and the answer depends on the
clock you pass in, not on the clock the process happens to read. Taking
``as_of`` as an argument means the same rows always give the same verdict, so
a test can pin a moment in time, and the dashboard can ask "was there a surge
at 09:48?" as easily as "is there one now?". The caller fetches the rows; this
module only decides.

Why causes are grouped by ban cluster
-------------------------------------
A flood of appeals is usually one event: a detection rule misfired, or a
cheat signature caught a batch of innocent players. The reviewer needs to see
which ban wave the tickets share, not just a count. Grouping by
``(ban_date, detection_method)`` names that wave. Tickets with no ban record
are kept in their own bucket rather than dropped, since "we can't tell why
these were banned" is itself a signal.

Pure stdlib — no database, no network. The caller owns I/O.
"""

import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# Same sys.path shim as cost.py, so this resolves whether the importer put the
# project root or dashboard/ on the path.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

__all__ = ["NO_BAN_LABEL", "detect"]

NO_BAN_LABEL = "(no ban record)"

_MAX_CAUSES = 3


def detect(rows, as_of, threshold, window_minutes):
    """Report whether an appeal surge is active in the window ending at as_of.

    The window is half-open on the left: a ticket counts when
    ``as_of - window_minutes < created_at <= as_of``. A ticket created exactly
    at the window's start belongs to the previous window; one created exactly
    at as_of belongs to this one.

    Each row counts on its own, so several appeals from one player each add to
    the total. The caller should therefore pass one row per appeal ticket, not
    one per player.

    Args:
        rows: Dicts with ``created_at`` (datetime), ``ban_date`` (date or None)
            and ``detection_method`` (str or None). A None method means the
            ticket has no ban record.
        as_of: The moment the window ends, or None when there is no reference
            time (no tickets at all).
        threshold: Minimum ticket count in the window for a surge to be active.
        window_minutes: Width of the trailing window, in minutes.

    Returns:
        A dict with ``active``, ``as_of``, ``window_start``, ``window_minutes``,
        ``threshold``, ``count``, ``top_cause`` and ``causes``. ``causes`` holds
        up to three ``{ban_date, detection_method, count, share}`` entries,
        ordered by count, and is empty unless the surge is active.
        ``top_cause`` is ``causes[0]``, or None when there are no causes.
        ``as_of`` and ``window_start`` are datetimes (or None), left as
        datetimes so the caller can serialize them.
    """
    if as_of is None:
        return _result(False, None, None, window_minutes, threshold, 0, [])

    window_start = as_of - timedelta(minutes=window_minutes)
    in_window = [row for row in rows if window_start < row["created_at"] <= as_of]
    count = len(in_window)
    active = count >= threshold

    causes = _causes(in_window, count) if active else []
    top_cause = causes[0] if causes else None
    return _result(active, as_of, window_start, window_minutes, threshold, count,
                   causes, top_cause)


def _causes(in_window, count):
    clusters = Counter(
        (row["ban_date"], row["detection_method"] or NO_BAN_LABEL)
        for row in in_window
    )
    ordered = sorted(clusters.items(), key=_cluster_order)
    return [
        {
            "ban_date": ban_date,
            "detection_method": method,
            "count": n,
            "share": round(n / count, 2),
        }
        for (ban_date, method), n in ordered[:_MAX_CAUSES]
    ]


def _cluster_order(item):
    # Count descending, then ban_date descending with None last (oldest), then
    # method ascending. Negating the ordinal turns "newest first" into an
    # ascending sort key, which is why the None case is 1: every real date
    # gets a negative key and so sorts ahead of it.
    (ban_date, method), n = item
    date_key = -ban_date.toordinal() if ban_date is not None else 1
    return (-n, date_key, method)


def _result(active, as_of, window_start, window_minutes, threshold, count,
            causes, top_cause=None):
    return {
        "active": active,
        "as_of": as_of,
        "window_start": window_start,
        "window_minutes": window_minutes,
        "threshold": threshold,
        "count": count,
        "top_cause": top_cause,
        "causes": causes,
    }
