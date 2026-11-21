-- PostgreSQL 18. Run as a separate provisioning owner using psql -v ON_ERROR_STOP=1.
-- Supply schema and runtime_role with psql -v. The role must already exist.
-- This is a fresh target only: existing schemas fail instead of being modified.
BEGIN;
CREATE SCHEMA :"schema";
CREATE TABLE :"schema".catalog_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    revision BIGINT NOT NULL CHECK (revision >= 0));
CREATE TABLE :"schema".catalog_rows (
    id TEXT PRIMARY KEY, title TEXT NOT NULL,
    pack_price_cents BIGINT NOT NULL CHECK (pack_price_cents >= 0),
    units_per_pack BIGINT NOT NULL CHECK (units_per_pack > 0),
    unit_price_cents BIGINT CHECK (unit_price_cents >= 0));
CREATE TABLE :"schema".foresee_target (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1), target_id TEXT NOT NULL);
CREATE TABLE :"schema".foresee_receipts (
    commit_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('applied', 'stale')),
    snapshot_digest TEXT NOT NULL,
    resulting_revision BIGINT NOT NULL CHECK (resulting_revision >= 0), detail TEXT NOT NULL);
INSERT INTO :"schema".catalog_meta VALUES (1, 0);
INSERT INTO :"schema".foresee_target VALUES (1, pg_catalog.gen_random_uuid()::text);
REVOKE ALL ON SCHEMA :"schema" FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA :"schema" FROM PUBLIC;
GRANT USAGE ON SCHEMA :"schema" TO :"runtime_role";
GRANT SELECT ON ALL TABLES IN SCHEMA :"schema" TO :"runtime_role";
-- MAINTAIN permits the explicit write lock without granting source-field UPDATE.
GRANT MAINTAIN ON :"schema".catalog_rows TO :"runtime_role";
GRANT UPDATE (unit_price_cents) ON :"schema".catalog_rows TO :"runtime_role";
GRANT UPDATE (revision) ON :"schema".catalog_meta TO :"runtime_role";
GRANT INSERT ON :"schema".foresee_receipts TO :"runtime_role";
COMMIT;
