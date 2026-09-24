# Crash recovery and receipt reconciliation

The demo now journals run and operation identities in `WORKSPACE/runs.db`. Each run has a UUID; each commit attempt has a separate UUID. Before the target adapter is called, a journal transaction stores the selected payload, program digest, operation and intent digests, resolved target path, and target identity. SQLite synchronous FULL is enabled on the journal connection.

The target database has a persistent identity in `foresee_target`. Existing catalogs receive this additive table on ordinary adapter initialization. Reconciliation does not initialize or migrate targets.

## Normal execution

```bash
python3 -m foresee demo examples/repair.fore --workspace build/recovery-demo
python3 -m foresee reconcile build/recovery-demo/runs.db
```

The demo prints its run ID and journal path. To inspect one run, use `reconcile JOURNAL --run-id RUN_ID`. Without a run ID, all recorded runs are checked. A missing journal or unknown run returns an error and does not create a new database.

Run states are `started`, `prepared`, `completed`, `reconciled`, and `unresolved`. Operation states are `prepared`, `applied`, `stale`, and `unresolved`. Preparing another operation changes the run back to `prepared`. The run is `completed` only after the interpreter reaches a terminal outcome and records it. A completed no-winner run can have zero operations.

## Reconciliation

Stop the original worker before reconciling an interrupted run. The command reads the target through a read-only SQLite connection. It checks target identity, recorded intent, commit identity, snapshot digest, receipt status, and receipt revision before accepting a result. It updates only the local journal, never reapplies patches, and reports `target_writes: 0`.

An interrupted run becomes `reconciled` when all its recorded operations have matching terminal target receipts. This does not imply that remaining source statements executed. A previously completed run stays completed when its evidence remains consistent. An interrupted run with no prepared operations is unresolved.

Missing receipts, unavailable targets, replaced databases, corrupt intent evidence, and inconsistent receipts produce `unresolved`. Absence of a receipt does not prove a safe retry: a worker could still be running, a target could be unavailable, or evidence could have been changed. The command does not automatically restart a decision or reconstruct a full execution report. Exit code 2 indicates unresolved evidence; 0 indicates all selected runs have resolved states; 1 indicates a command or journal error.

## Controlled crash exercise

Use a separate workspace for each exercise:

```bash
python3 -m foresee demo examples/repair.fore --workspace build/crash-after --fault after_commit
python3 -m foresee reconcile build/crash-after/runs.db
```

The explicit `--fault` option terminates the process with exit code 86 via `os._exit`, without Python cleanup. Supported boundaries:

| Boundary | Target state after process exit | Reconciliation |
| --- | --- | --- |
| `before_transaction` | Intent journaled; target transaction not started | Unresolved, no receipt |
| `before_commit` | Target writes and receipt were uncommitted | Unresolved, no durable receipt |
| `after_commit` | Target data and receipt committed; caller did not receive result | Applied or stale receipt recovered |

The tests launch independent subprocesses and reconcile repeatedly after termination. Applied operations keep one revision increment and one receipt. Stale receipts recover without applying a patch.

## Identity, retries, and trust

Journaled operations use the explicit operation-ID facility from adapter protocol 2. A fresh demo invocation creates a new run and new operation IDs; it is not a retry of an interrupted operation. Reconciliation reuses recorded identities only for receipt lookup. Low-level runtimes constructed without a journal retain the adapter's deterministic fallback identity and do not acquire crash journaling automatically.

The journal and target must be separate database files. Back up both. The journal includes selected plans and snapshot data and should be treated as application data, not committed source. There is no distributed transaction between these two databases: writing intent first and consulting the target receipt closes the post-commit acknowledgement gap conservatively. A crash before durable intent may leave only a started run or no run record.

These guarantees assume functioning local SQLite durability and trusted schema/ledger contents. Checksums and target UUIDs are consistency checks, not cryptographic authentication. A copied database retains its UUID. Manual ledger edits, arbitrary triggers, malicious Python callers, and storage failures outside SQLite's durability model are not addressed. Reconciliation reads recorded outcomes rather than proving current domain data still matches an old applied receipt.
