# Migrations

Numbered, forward-only, applied by hand:

```
psql "$DATABASE_URL" -f database/migrations/001_add_token_usage.sql
```

There is no migration framework and no version table — this project has one
developer and one database, so a numbered directory and a note in the README
is the whole system. Each file is written to be idempotent (`IF NOT EXISTS`),
so re-running one is safe.

**`database/init_db.py` is not the way to apply these.** It executes
`schema.sql`, which begins by dropping every table; running it against a
seeded database destroys the ticket corpus. It is for first-time setup only.
To run it against a scratch database instead of the default one, see "Pointing
at a non-default database" in the [README](../../README.md) — an exported
`DATABASE_URL` beats `.env`, but only for commands in that same shell.

### Known gap: a wrong-target `init_db.py` run is visible, not impossible

`init_db.py` prints the database it resolved (`Connected to PostgreSQL:
<dbname> on <host>:<port>`) before applying the schema, so a run aimed at the
wrong database leaves evidence in the output at the moment it happens. It does
not *stop* that run — the drop still executes, and the print scrolls past in a
copy-pasted command sequence.

Closing the gap properly means a confirmation gate (prompt unless `--yes`, or
refuse outright when the target looks like the default database while
`DATABASE_URL` is exported). That was deliberately deferred: it breaks the
copy-pasteable Quickstart in the [README](../../README.md) and any scripted
setup, which is a real cost for a script run a handful of times a year. Worth
revisiting if this bites twice.

`schema.sql` stays the source of truth for a from-scratch install, so every
migration must also be folded into the matching `CREATE TABLE` there. The two
are kept in sync by hand — if you add a migration, edit `schema.sql` in the
same commit.

| File | What it does |
|---|---|
| `001_add_token_usage.sql` | Adds nullable `input_tokens`, `output_tokens`, `model_name` to `support_tickets_with_ai` for per-evaluation cost reporting |
