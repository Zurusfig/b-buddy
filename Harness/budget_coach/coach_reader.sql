-- Read-only access for the Budget Buddy coach. Run once, as the database owner (Supabase SQL editor).
-- `python demo_db.py reader-sql` fills in __PASSWORD__ with a random value and writes the result to
-- coach_reader.generated.sql (git-ignored). Do not commit a copy that holds a real password.
--
-- The coach role can SELECT from two views (v_transactions, v_categories) and nothing else: no User table (password hashes), no
-- Asset, no writes. The views drop soft-deleted rows and the cash side of investment trades, as the
-- app's own reports do, and expose each moment in Thai time (the app shows Thai time everywhere).

CREATE OR REPLACE VIEW v_transactions AS
SELECT t.id,
       t."userId",
       t.amount,
       t.type,
       t.description,
       t.date,
       (t.date AT TIME ZONE 'Asia/Bangkok') AS local_date,
       c.name AS category,
       c.type AS category_type
FROM "Transaction" t
LEFT JOIN "Category" c ON c.id = t."categoryId"
WHERE t."deletedAt" IS NULL
  AND t.source IS DISTINCT FROM 'investment';

CREATE OR REPLACE VIEW v_categories AS
SELECT c."userId",
       c.name AS category,
       c.type AS category_type,
       c.budget AS monthly_limit
FROM "Category" c
WHERE c."deletedAt" IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'coach_reader') THEN
    CREATE ROLE coach_reader LOGIN PASSWORD '__PASSWORD__';
  ELSE
    ALTER ROLE coach_reader WITH LOGIN PASSWORD '__PASSWORD__';
  END IF;
END
$$;

ALTER ROLE coach_reader SET default_transaction_read_only = on;
ALTER ROLE coach_reader SET statement_timeout = '5s';

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM coach_reader;
GRANT USAGE ON SCHEMA public TO coach_reader;
GRANT SELECT ON v_transactions, v_categories TO coach_reader;
