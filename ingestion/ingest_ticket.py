"""ingest_ticket.py — CLI tool for ingesting tickets and ban records into PostgreSQL.

Usage:
    python ingestion/ingest_ticket.py --tickets data/sample_tickets.json
    python ingestion/ingest_ticket.py --bans data/sample_bans.json
    python ingestion/ingest_ticket.py --tickets data/sample_tickets.json --bans data/sample_bans.json
"""

# ---------------------------------------------------------------------------
# Imports & Configuration
# ---------------------------------------------------------------------------

import argparse
import json
import sys
from pathlib import Path

# Make the project root importable so `from config.settings import ...` works
# regardless of the cwd this script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_connection as _get_connection  # noqa: E402

# Every ticket must have these 8 fields to pass validation
REQUIRED_TICKET_FIELDS = [
    "ticket_id", "user_name", "user_id", "ticket_issue_category",
    "ticket_title", "ticket_body", "status", "created_at",
]


# ---------------------------------------------------------------------------
# Database Connection
# ---------------------------------------------------------------------------

def get_connection():
    """Open the shared psycopg2 connection with autocommit enabled.

    Returns a (connection, cursor) tuple to preserve the existing call
    contract in main(). Exits the CLI with a friendly message if the
    connection cannot be established, so the ingestion UX is unchanged
    from before get_connection was promoted to config/settings.py."""
    try:
        conn = _get_connection(autocommit=True)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    cur = conn.cursor()
    print("Connected to PostgreSQL.")
    return conn, cur


# ---------------------------------------------------------------------------
# JSON File Loading
# ---------------------------------------------------------------------------

def load_json_file(filepath):
    """Read and parse a JSON file. Exits if the file is missing or malformed."""
    path = Path(filepath)
    if not path.exists():
        print(f"ERROR: File not found: {path}")
        sys.exit(1)
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}\n{e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Ticket Ingestion — Validation, Single Insert, and Bulk Processing
# ---------------------------------------------------------------------------

def validate_ticket(ticket):
    """Check that all 8 required fields are present in a ticket dict.
    Returns a list of missing field names (empty list means valid)."""
    return [f for f in REQUIRED_TICKET_FIELDS if f not in ticket]


def ingest_single_ticket(cur, ticket):
    """Validate and insert one ticket into support_tickets.

    Steps:
      1. Validate required fields — fail early if any are missing
      2. INSERT with ON CONFLICT DO NOTHING — skip duplicates gracefully
      3. If inserted, also create an initial ticket_status_history entry

    Returns: 'inserted', 'skipped', or 'failed'
    """
    # Step 1: Validate required fields
    missing = validate_ticket(ticket)
    if missing:
        ticket_id = ticket.get("ticket_id", "UNKNOWN")
        print(f"  INVALID {ticket_id}: missing fields: {', '.join(missing)}")
        return "failed"

    # Step 2: Attempt insert (duplicates are silently skipped via ON CONFLICT)
    ticket_id = ticket["ticket_id"]
    try:
        cur.execute(
            """INSERT INTO support_tickets
               (ticket_id, user_name, user_id, ticket_issue_category,
                ticket_title, ticket_body, status, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (ticket_id) DO NOTHING""",
            (ticket_id, ticket["user_name"], ticket["user_id"],
             ticket["ticket_issue_category"], ticket["ticket_title"],
             ticket["ticket_body"], ticket["status"], ticket["created_at"]),
        )
        if cur.rowcount == 0:
            print(f"  SKIPPED {ticket_id}: already exists.")
            return "skipped"

        # Step 3: Record the initial status in ticket_status_history
        cur.execute(
            """INSERT INTO ticket_status_history (ticket_id, old_status, new_status)
               VALUES (%s, NULL, %s)""",
            (ticket_id, ticket["status"]),
        )
        print(f"  INSERTED {ticket_id}")
        return "inserted"

    except Exception as e:
        print(f"  FAILED {ticket_id}: {e}")
        return "failed"


def ingest_tickets(cur, tickets):
    """Process a list of tickets by calling ingest_single_ticket for each one.
    Tracks inserted/skipped/failed counts and prints a summary at the end."""
    counts = {"inserted": 0, "skipped": 0, "failed": 0}
    for ticket in tickets:
        result = ingest_single_ticket(cur, ticket)
        counts[result] += 1

    total = len(tickets)
    print(f"\nTicket summary: Processed {total} tickets: "
          f"{counts['inserted']} inserted, {counts['skipped']} skipped, "
          f"{counts['failed']} failed.")
    return counts


# ---------------------------------------------------------------------------
# Ban Record Ingestion
# ---------------------------------------------------------------------------

def ingest_bans(cur, bans):
    """Insert ban records into ban_database.
    Skips duplicates via ON CONFLICT on user_id (each user has one ban record).
    Tracks inserted/skipped/failed counts and prints a summary at the end."""
    inserted = 0
    skipped = 0
    failed = 0

    for ban in bans:
        user_id = ban.get("user_id", "UNKNOWN")
        try:
            cur.execute(
                """INSERT INTO ban_database
                   (user_id, ban_reason, detection_method, ban_duration, ban_date)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (user_id) DO NOTHING""",
                (ban["user_id"], ban["ban_reason"], ban["detection_method"],
                 ban["ban_duration"], ban["ban_date"]),
            )
            if cur.rowcount == 1:
                print(f"  INSERTED ban: {user_id}")
                inserted += 1
            else:
                print(f"  SKIPPED ban: {user_id} (already exists)")
                skipped += 1
        except Exception as e:
            print(f"  FAILED ban {user_id}: {e}")
            failed += 1

    total = len(bans)
    print(f"\nBan summary: Processed {total} bans: "
          f"{inserted} inserted, {skipped} skipped, {failed} failed.")
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# CLI Entry Point — parse args, detect format, and route to the right handler
# ---------------------------------------------------------------------------

def main():
    # Set up command-line arguments: --tickets and --bans (at least one required)
    parser = argparse.ArgumentParser(
        description="Ingest tickets and/or ban records into the database."
    )
    parser.add_argument(
        "--tickets", metavar="FILE",
        help="Path to a JSON file containing a single ticket or a tickets array.",
    )
    parser.add_argument(
        "--bans", metavar="FILE",
        help="Path to a JSON file containing a bans array.",
    )
    args = parser.parse_args()

    if not args.tickets and not args.bans:
        parser.error("At least one of --tickets or --bans is required.")

    conn, cur = get_connection()

    # -- Ticket ingestion --
    # Supports two JSON formats:
    #   - Single ticket:  {"ticket_id": "...", "user_name": "...", ...}
    #   - Bulk array:     {"tickets": [{...}, {...}, ...]}
    if args.tickets:
        data = load_json_file(args.tickets)
        if "tickets" in data:
            tickets = data["tickets"]
            print(f"Loading {len(tickets)} tickets from {args.tickets}...")
        elif "ticket_id" in data:
            tickets = [data]
            print(f"Loading single ticket from {args.tickets}...")
        else:
            print(f"ERROR: Unrecognized JSON format in {args.tickets}. "
                  "Expected a ticket object or {{\"tickets\": [...]}}.")
            sys.exit(1)

        ingest_tickets(cur, tickets)

    # -- Ban record ingestion --
    # Expects JSON format: {"bans": [{...}, {...}, ...]}
    if args.bans:
        data = load_json_file(args.bans)

        if "bans" in data:
            bans = data["bans"]
            print(f"\nLoading {len(bans)} bans from {args.bans}...")
        else:
            print(f"ERROR: Unrecognized JSON format in {args.bans}. "
                  "Expected {{\"bans\": [...]}}.")
            sys.exit(1)

        ingest_bans(cur, bans)

    # -- Clean up --
    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
