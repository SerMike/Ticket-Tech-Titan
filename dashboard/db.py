"""db.py — Database access layer for the Streamlit dashboard.

All dashboard SQL queries live here so pages stay UI-only. Query
functions (get_all_tickets, get_ticket_detail, get_ai_evaluation,
update_ticket_status, get_analytics_data) are added in Step 2 of
planning/phase-3-checklist.md.

The connection itself is NOT duplicated — it re-exports the shared
``get_connection`` from ``config.settings`` so the dashboard and the
ingestion pipeline share one source of truth for DB config.
"""

import sys
from pathlib import Path

# When launched via `streamlit run dashboard/app.py`, sys.path includes
# the ``dashboard/`` folder but not the project root. Insert the project
# root so ``from config.settings import ...`` resolves for every page.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import ALLOWED_STATUSES, get_connection  # noqa: E402

__all__ = ["ALLOWED_STATUSES", "get_connection"]
