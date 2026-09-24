# SQLite transaction contract

Day 4 hardens the local Catalog adapter. All guarantees here apply to one SQLite database containing both domain rows and Foresee receipts.

## Consistent snapshots

Standalone snapshot reads open an explicit read transaction, read revision and ordered rows, and close that transaction. A writer that commits between the two SELECT statements cannot produce a mixed snapshot. When a caller already owns a transaction, snapshot reads use it and do not commit or roll it back.

Commit requires an idle connection. It never silently commits or rolls back an unrelated caller transaction.

## Operation identity and intent

Adapter protocol 2 distinguishes operation identity from intent. An optional `operation_id` keyword argument identifies a caller's logical operation. It must be persisted and reused by that caller for retries. It is scoped to the database's receipt ledger. Without it, identity is derived from protocol version, program digest, snapshot digest, and the adapter's physical catalog resource. This default allows one intent per program/snapshot pair; a different selected plan with that identity is a conflict.

Intent includes the program digest, snapshot digest, resource, and full plan. Reusing an operation identity with a different intent raises an error. A receipt's `commit_id` is the full SHA-256 digest of the operation identity, independent of the intent digest. Day 5 journaled demo runs use persisted operation UUIDs; low-level unjournaled runtimes use the deterministic default.

Earlier versions derived identity from intent and used shorter IDs. Existing receipts are preserved but are not automatically migrated or matched by protocol 2. Do not retry an interrupted pre-Day-4 operation through this adapter without first inspecting its old receipt. This is an adapter protocol change; the compiler IR remains 0.0.3.

## Commit sequence

1. Copy the caller payload and validate patch structure and scalar values.
2. Acquire `BEGIN IMMEDIATE` on the target database.
3. Look up the receipt inside that transaction. Return a matching terminal receipt, or reject a conflicting intent.
4. Read a consistent live snapshot and compare its digest with the selected snapshot. A mismatch stores a terminal `stale` receipt without changing domain rows.
5. Validate target row existence and expected unit-price arithmetic against the live snapshot before writing.
6. Apply the patches, advance the revision, and compare resulting rows and revision with the expected state.
7. Insert the applied receipt and commit once. Any exception rolls back the transaction, including row changes and revision updates.

Patch entries must contain exactly `id` and `unit_price_cents`. IDs must be nonempty strings with no repeated row ID in a plan. Prices must be actual integers from zero through SQLite's signed 64-bit maximum; booleans, floats, strings, nulls, negative values, and oversized integers are rejected. Every non-null unit price in the resulting catalog must multiply by the units per pack to equal the pack price. Empty patch lists remain valid no-op plans and still produce a revision and receipt.

## Supported writers and limits

Use separate connections for concurrent operations. SQLite serializes these writes; lock contention can time out and callers must treat that as an error, not an applied result. Default sqlite3 timeout behavior is unchanged. No automatic external side-effect retry is introduced.

All participating writers must preserve the schema and update domain rows and revision in the same transaction. The full-state digest also detects changes without a revision bump when they are visible at commit time, but schema changes, arbitrary triggers, and direct receipt edits are outside the supported writer model. A regression test confirms a row-modifying trigger is caught by the postcondition check; this is not a guarantee against arbitrary trigger behavior.

Data and receipt live in the same local transaction. This does not establish exactly-once behavior for external APIs, network filesystems, hardware failures outside SQLite's durability model, or manually altered ledgers. See the [recovery guide](recovery.md) for Day 5 receipt reconciliation.
