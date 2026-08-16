"""load_sample_data.py — Loads sample tickets and bans into the database."""

import json
import sys
from pathlib import Path

# Make the project root importable so `from config.settings import ...` works
# regardless of the cwd this script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_connection  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent


def load_json(filename):
    filepath = DATA_DIR / filename
    if not filepath.exists():
        print(f"ERROR: {filepath} not found.")
        sys.exit(1)
    with open(filepath) as f:
        return json.load(f)


def main():
    try:
        conn = get_connection(autocommit=True)
        cur = conn.cursor()
        print("Connected to PostgreSQL.")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Load tickets
    tickets_data = load_json("sample_tickets.json")
    tickets = tickets_data["tickets"]
    tickets_inserted = 0
    tickets_skipped = 0

    for t in tickets:
        try:
            cur.execute(
                """INSERT INTO support_tickets
                   (ticket_id, user_name, user_id, ticket_issue_category,
                    ticket_title, ticket_body, status, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (ticket_id) DO NOTHING""",
                (t["ticket_id"], t["user_name"], t["user_id"],
                 t["ticket_issue_category"], t["ticket_title"],
                 t["ticket_body"], t["status"], t["created_at"]),
            )
            if cur.rowcount == 1:
                tickets_inserted += 1
            else:
                tickets_skipped += 1
                print(f"  Skipped duplicate ticket: {t['ticket_id']}")
        except Exception as e:
            print(f"  ERROR inserting ticket {t['ticket_id']}: {e}")
            tickets_skipped += 1

    print(f"Tickets: {tickets_inserted} inserted, {tickets_skipped} skipped.")

    # Load bans
    bans_data = load_json("sample_bans.json")
    bans = bans_data["bans"]
    bans_inserted = 0
    bans_skipped = 0

    for b in bans:
        try:
            cur.execute(
                """INSERT INTO ban_database
                   (user_id, ban_reason, detection_method, ban_duration, ban_date)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (user_id) DO NOTHING""",
                (b["user_id"], b["ban_reason"], b["detection_method"],
                 b["ban_duration"], b["ban_date"]),
            )
            if cur.rowcount == 1:
                bans_inserted += 1
            else:
                bans_skipped += 1
                print(f"  Skipped duplicate ban: {b['user_id']}")
        except Exception as e:
            print(f"  ERROR inserting ban {b['user_id']}: {e}")
            bans_skipped += 1

    print(f"Bans: {bans_inserted} inserted, {bans_skipped} skipped.")

    # Create initial status history entries for each ticket
    history_inserted = 0
    history_skipped = 0

    for t in tickets:
        try:
            # Only insert if no history exists for this ticket yet
            cur.execute(
                """INSERT INTO ticket_status_history (ticket_id, old_status, new_status)
                   SELECT %s, NULL, %s
                   WHERE NOT EXISTS (
                       SELECT 1 FROM ticket_status_history WHERE ticket_id = %s
                   )""",
                (t["ticket_id"], t["status"], t["ticket_id"]),
            )
            if cur.rowcount == 1:
                history_inserted += 1
            else:
                history_skipped += 1
                print(f"  Skipped duplicate history: {t['ticket_id']}")
        except Exception as e:
            print(f"  ERROR inserting history for {t['ticket_id']}: {e}")
            history_skipped += 1

    print(f"Status history: {history_inserted} inserted, {history_skipped} skipped.")

    print(f"\nSummary: Inserted {tickets_inserted} tickets, "
          f"{bans_inserted} bans, {history_inserted} status history entries.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
