# PostgreSQL adapter contract and test foundation

Milestone 1, 16 November 2026. The disposable database fixture is implemented. The resource adapter, project configuration, journal recovery integration, and deployment support are not implemented yet. This document defines their intended behavior before those components are written.

## Scope and philosophy

The initial adapter will support Foresee's existing Catalog/Patch domain: stable row IDs, immutable source fields, bounded derived unit-price changes, a target revision, and durable operation receipts. It will not execute model-supplied SQL, migrate arbitrary user tables, or provide a generic SQL agent. Reuse the language checker, plan validation, pure simulation, deterministic selection, and offline report replay.

A receipt records the outcome of one operation at one target. Its transaction must include both the changed rows and revision. Recovery must read this record, not infer success from the current row values. A failed network acknowledgement is an unknown outcome until the original operation identity is reconciled.

## Proposed storage contract

The fixture creates four tables in a unique schema: `catalog_rows`, `catalog_meta`, `foresee_target`, and `foresee_receipts`. Money/revision fields use PostgreSQL BIGINT, matching the existing signed 64-bit bound. Receipt status is constrained to applied/stale; receipt IDs are unique. The fixture seeds the same three catalog rows as SQLite.

| Operation | Required behavior |
| --- | --- |
| Open | Connect to an explicitly configured existing target/schema; validate schema and persistent target UUID; never seed or migrate automatically |
| Snapshot | An idle connection opens a short repeatable-read, read-only transaction; read revision and ordered rows from the same database snapshot; compute the existing canonical digest |
| Simulation | Pure Catalog helpers, no SQL writes |
| Commit | Validate a copied selection and operation identity before writes; acquire the table write lock, then metadata row lock; check existing receipt before freshness; apply changes/revision/receipt in one transaction |
| Retry | Same operation and intent returns original terminal receipt without another effect; different intent for that operation is an error |
| Stale | Record one terminal stale receipt; do not apply patches or increment revision |
| Failure | Any pre-commit error rolls back rows, revision, and receipt; post-commit acknowledgement failure must not be described as rollback |
| Reconcile | Reopen the explicitly configured target, validate target UUID, then inspect the receipt for the original operation; no automatic new operation ID |

Initial commit locking is deliberately coarse: `LOCK TABLE catalog_rows IN SHARE ROW EXCLUSIVE MODE`, then `SELECT ... FROM catalog_meta ... FOR UPDATE`. Use a short read-committed write transaction so a queued retry sees the receipt committed by the prior writer. All managed mutation helpers use the same lock order. Read-only observers must see the prior committed state while this transaction is in progress. More granular locking requires new concurrency tests before changing this contract.

PostgreSQL [read committed and repeatable read](https://www.postgresql.org/docs/current/transaction-iso.html) have different snapshot behavior; do not port SQLite's implicit assumptions by substituting SQL placeholders. Psycopg's [transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) will delimit writes on otherwise autocommit connections. No silent transaction retry is planned. An aborted SQL transaction requires rollback before reuse.

The schema belongs to this adapter. Administrators and other writers can invalidate assumptions by modifying metadata, receipts, triggers, or permissions. Production integration must restrict direct writes and define least-privilege provisioning. The initial fixture uses a test owner role and does not establish that production role design.

## Disposable fixture

Install `python -m pip install ".[postgres]"`. The extra pins Psycopg 3.3.9 with its separately installed binary package. It is optional and does not add a base runtime dependency.

`foresee.postgres_fixture.PostgresFixture(dsn, adapter_factory=...)` creates a new `foresee_test_<uuid>` schema in an explicitly supplied disposable database. No existing schema name is accepted. Initialization is transactional. Cleanup drops only that fixture-owned schema. Connections use a search path containing only the generated schema, without a public fallback. Table identifiers for schema creation/drop use Psycopg identifier composition; values use bound parameters.

The fixture provides `database()` for independent autocommit sessions, pure plan/simulation helpers, a locked external-mutation helper, receipt inspection, and a context manager that installs a rejecting receipt trigger. Sessions have a 5-second connection timeout, 5-second statement timeout, 2-second lock timeout, and 10-second idle-in-transaction timeout. Connection failures are redacted; the fixture never prints its DSN.

The shared adapter runner registers fixture `close()` before opening an adapter. Later, pass a factory accepting `(dsn, schema)` that returns the actual PostgreSQL resource adapter. Without that factory, `connect()` fails explicitly. This avoids substituting SQL fixture helpers for an adapter implementation and accidentally claiming conformance.

## Run database integration checks

Provide `FORESEE_TEST_POSTGRES_DSN` through the environment, pointing only to a disposable test database whose role may create/drop schemas and create trigger functions. Do not put credentials in source control or reports. Then run:

```sh
python -m unittest discover -s integration -v
```

Missing configuration or driver is a test failure, not a skip. The dedicated CI job starts an isolated PostgreSQL 18 service with test-only credentials. Its six checks cover schema isolation/seed identity, receipt-write rollback, bounded row-lock contention and reuse after rollback, repeatable-read consistency, scoped/idempotent cleanup, and receipt uniqueness. These are database foundation tests, not the twelve resource-adapter conformance tests.

A killed test process may leave its generated schema behind. On a disposable server, inspect the test namespace before removing abandoned schemas. The fixture does not scan or delete other schemas automatically. Successful teardown is registered for ordinary failures; this is not a server-wide resource management or cleanup service.

## Next acceptance gates

1. Implement open/snapshot/commit/receipt lookup using the contract above, with no automatic target provisioning and no DSN in evidence.
2. Run all twelve existing adapter checks against the real implementation, including concurrent retries, conflicting intent, stale receipts, and lost acknowledgement.
3. Add true process termination and reconnect/reconciliation tests. Fixture exceptions alone are not crash testing.
4. Replace the SQLite-specific path assumption in journal/resource references with an explicit adapter target reference while preserving old journals. Database credentials must remain local configuration.
5. Add project configuration, deployment examples, and installed-package PostgreSQL checks before exposing this as a supported runtime target.
