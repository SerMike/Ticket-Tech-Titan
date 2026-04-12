"""ingest_ticket.py — CLI tool for ingesting tickets and ban records into PostgreSQL."""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REQUIRED_TICKET_FIELDS = [
    "ticket_id", "user_name", "user_id", "ticket_issue_category",
    "ticket_title", "ticket_body", "status", "created_at",
]


def get_connection():
    """Connect to PostgreSQL using DATABASE_URL from .env."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL is not set. Add it to your .env file.")
        sys.exit(1)
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        print("Connected to PostgreSQL.")
        return conn, cur
    except psycopg2.OperationalError as e:
        print(f"ERROR: Could not connect to database.\n{e}")
        sys.exit(1)


def load_json_file(filepath):
    """Read and parse a JSON file. Exit on error."""
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


def validate_ticket(ticket):
    """Return a list of missing required fields (empty list = valid)."""
    return [f for f in REQUIRED_TICKET_FIELDS if f not in ticket]


def ingest_single_ticket(cur, ticket):
    """Validate and insert one ticket. Returns 'inserted', 'skipped', or 'failed'."""
    missing = validate_ticket(ticket)
    if missing:
        ticket_id = ticket.get("ticket_id", "UNKNOWN")
        print(f"  INVALID {ticket_id}: missing fields: {', '.join(missing)}")
        return "failed"

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

        # Create initial status history entry
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
    """Process a list of tickets and print a summary."""
    counts = {"inserted": 0, "skipped": 0, "failed": 0}
    for ticket in tickets:
        result = ingest_single_ticket(cur, ticket)
        counts[result] += 1

    total = len(tickets)
    print(f"\nTicket summary: Processed {total} tickets: "
          f"{counts['inserted']} inserted, {counts['skipped']} skipped, "
          f"{counts['failed']} failed.")
    return counts


def ingest_bans(cur, bans):
    """Insert ban records into ban_database with duplicate handling."""
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


def main():
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

    if args.tickets:
        data = load_json_file(args.tickets)

        # Detect single ticket vs bulk array
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

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
