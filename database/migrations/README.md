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

`schema.sql` stays the source of truth for a from-scratch install, so every
migration must also be folded into the matching `CREATE TABLE` there. The two
are kept in sync by hand — if you add a migration, edit `schema.sql` in the
same commit.

| File | What it does |
|---|---|
| `001_add_token_usage.sql` | Adds nullable `input_tokens`, `output_tokens`, `model_name` to `support_tickets_with_ai` for per-evaluation cost reporting |
