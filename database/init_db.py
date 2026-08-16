"""init_db.py — Creates tables and seeds default categories."""

import sys
from pathlib import Path

# Make the project root importable so `from config.settings import ...` works
# regardless of the cwd this script is launched from. Config lives there and
# nowhere else: this script drops every table, so it must resolve
# DATABASE_URL exactly the way the rest of the project does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_connection  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

DEFAULT_CATEGORIES = [
    ("Request Account Unban", None),
    ("Report False Ban", None),
    ("Report Account Compromise", None),
    ("Report Bug", None),
    ("General Inquiry", None),
]


def main():
    try:
        conn = get_connection(autocommit=True)
        cur = conn.cursor()
        # Name the target: the next step drops every table, and an exported
        # DATABASE_URL silently redirects this script away from .env.
        print(f"Connected to PostgreSQL: {conn.info.dbname} "
              f"on {conn.info.host}:{conn.info.port}")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Create tables
    try:
        schema_sql = SCHEMA_FILE.read_text()
        cur.execute(schema_sql)
        print("Schema applied — all tables created.")
    except Exception as e:
        print(f"ERROR: Failed to apply schema.\n{e}")
        sys.exit(1)

    # Seed default categories
    try:
        for name, description in DEFAULT_CATEGORIES:
            cur.execute(
                """INSERT INTO ticket_categories (category_name, description)
                   VALUES (%s, %s)
                   ON CONFLICT (category_name) DO NOTHING""",
                (name, description),
            )
        print("Default ticket categories seeded.")
    except Exception as e:
        print(f"ERROR: Failed to seed categories.\n{e}")
        sys.exit(1)

    # Verify tables exist
    cur.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public' ORDER BY table_name"""
    )
    tables = [row[0] for row in cur.fetchall()]
    print(f"Tables in database: {', '.join(tables)}")

    cur.close()
    conn.close()
    print("Database setup complete.")


if __name__ == "__main__":
    main()
