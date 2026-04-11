"""init_db.py — Creates tables and seeds default categories."""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set. Add it to your .env file.")
    sys.exit(1)

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
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        print("Connected to PostgreSQL.")
    except psycopg2.OperationalError as e:
        print(f"ERROR: Could not connect to database.\n{e}")
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
