# PostgreSQL adapter contract and implementation

Milestone 2, 17 November 2026. The experimental resource adapter and disposable database fixture are implemented. Project configuration, journal recovery integration, and deployment support remain pending.

## Scope and philosophy

The initial adapter supports Foresee's existing Catalog/Patch domain: stable row IDs, immutable source fields, bounded derived unit-price changes, a target revision, and durable operation receipts. It will not execute model-supplied SQL, migrate arbitrary user tables, or provide a generic SQL agent. Reuse the language checker, plan validation, pure simulation, deterministic selection, and offline report replay.

A receipt records the outcome of one operation at one target. Its transaction must include both the changed rows and revision. Recovery must read this record, not infer success from the current row values. A failed network acknowledgement is an unknown outcome until the original operation identity is reconciled.

## Storage contract

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

The shared adapter runner registers fixture `close()` before opening an adapter. Pass `adapter_factory=PostgresCatalog` from `foresee.postgres` to run the real adapter. The factory accepts `(dsn, schema)`. Without that factory, `connect()` fails explicitly. This avoids substituting SQL fixture helpers for an adapter implementation and accidentally claiming conformance.

## Run database integration checks

Provide `FORESEE_TEST_POSTGRES_DSN` through the environment, pointing only to a disposable test database whose role may create/drop schemas and create trigger functions. Do not put credentials in source control or reports. Then run:

```sh
python -m unittest discover -s integration -v
```

Missing configuration or driver is a test failure, not a skip. The dedicated CI job starts an isolated PostgreSQL 18 service with test-only credentials. Its six checks cover schema isolation/seed identity, receipt-write rollback, bounded row-lock contention and reuse after rollback, repeatable-read consistency, scoped/idempotent cleanup, and receipt uniqueness. These are database foundation tests. The same job also runs all twelve shared resource-adapter conformance checks plus seven PostgreSQL-specific adapter tests.

A killed test process may leave its generated schema behind. On a disposable server, inspect the test namespace before removing abandoned schemas. The fixture does not scan or delete other schemas automatically. Successful teardown is registered for ordinary failures; this is not a server-wide resource management or cleanup service.

## Next acceptance gates

1. Add true process termination and reconnect/reconciliation tests. Fixture exceptions alone are not crash testing.
2. Replace the SQLite-specific path assumption in journal/resource references with an explicit adapter target reference while preserving old journals. Database credentials must remain local configuration.
3. Add project configuration, deployment examples, and installed-package PostgreSQL checks before exposing this as a supported runtime target.

## Experimental Python API

```python
import os
from foresee.postgres import PostgresCatalog

adapter = PostgresCatalog(os.environ["FORESEE_POSTGRES_DSN"], "managed_catalog")
try:
    before = adapter.snapshot()
    # selection comes from the checked runtime and its pure simulation.
    # outcome = adapter.commit(selection, program_digest, operation_id=operation_id)
    # receipt = adapter.receipt(outcome["commit_id"])
finally:
    adapter.close()
```

The schema must already contain the four managed tables. Opening validates readable columns, row values, revision, and a canonical target UUID; it does not certify permissions, constraints, triggers, or administrator behavior. There is no public provisioning command yet. The disposable fixture remains for tests only.

Each adapter instance belongs to one caller. Use separate instances for concurrent operations. Public snapshot/commit/receipt operations require an idle connection; they never adopt or commit a caller's transaction. SQL identifiers are composed and application tables are fully schema-qualified, preventing temporary tables from shadowing the target. Schema names use a restricted lowercase identifier syntax (up to 63 ASCII characters, excluding system namespaces). Snapshot rows are sorted in Python to preserve the existing digest ordering independently of database collation.

The adapter uses the fixture's connection and session timeout bounds. It never automatically retries. `receipt(commit_id)` returns a persisted row or `None`; absence alone cannot establish that another session has no in-flight operation. The conformance test for lost acknowledgement injects a failure after commit, not a network disconnection or process kill. Such crash/reconnect coverage and identity-checked journal reconciliation remain the next milestone.

The adapter has no filesystem `path` and is currently usable through the Python runtime without a journal. Do not pass it to the SQLite journal or select it in project configuration yet. No DSN is added to the report or receipt, and connection establishment errors are redacted. Operators should still treat raw database diagnostics as local diagnostic data.
