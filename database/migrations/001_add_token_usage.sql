-- 001_add_token_usage.sql — per-evaluation LLM token usage.
--
-- Apply to an existing database:
--     psql "$DATABASE_URL" -f database/migrations/001_add_token_usage.sql
--
-- Do NOT run database/init_db.py to pick this change up. schema.sql opens
-- with DROP TABLE ... CASCADE on every table, so re-running it would delete
-- the seeded ticket corpus along with every evaluation.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS) and instant: nullable columns with
-- no default are a catalog-only change in modern PostgreSQL, so no table
-- rewrite happens regardless of row count.
--
-- All three columns are nullable on purpose. Evaluations written before this
-- migration have no usage data, and the cost layer must render those as
-- "untracked" rather than folding them into a total as $0.00.

ALTER TABLE support_tickets_with_ai
    ADD COLUMN IF NOT EXISTS input_tokens  INT,
    ADD COLUMN IF NOT EXISTS output_tokens INT,
    ADD COLUMN IF NOT EXISTS model_name    VARCHAR(100);
