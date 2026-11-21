# PostgreSQL deployment pilot

Status: prepared on 21 November 2026. No hosted environment has been selected or deployed by this work. The isolated fault harness is a verification gate, not evidence of real workload performance.

## Target and workload

Use a fresh staging database and schema with synthetic or approved non-production catalog rows. Keep the owner account separate from the runtime role and use the [provisioning example](../examples/postgres/provision.sql). Configure the runtime DSN through the environment and keep the project journal on persistent local storage. Record the exact Git commit, PostgreSQL version, host resources, row count, candidate count, and network placement without recording credentials.

Start with one worker and a known catalog whose derived prices can be checked independently. Review candidates before execution. Capture the CLI output, report, and journal for each run. Verify changes from a separate connection and reproduce the report offline. Reconcile twice and confirm that neither revision nor receipts change. A fresh run creates a new operation identity; do not use repeated `run` commands as a substitute for receipt recovery.

## Acceptance record

| Exercise | Required observation |
| --- | --- |
| Ordinary repair | Expected rows, one revision increment, one receipt, reproducible report |
| Stale proposal | Terminal stale receipt, no derived-price changes from that operation |
| Restricted runtime role | Commit succeeds; source edits, receipt deletion, and identity edits fail |
| Worker termination before commit | No durable effect/receipt; recovery remains unresolved |
| Worker termination after commit | One durable effect/receipt; recovery confirms it without retry |
| Server termination and restart | Same boundary behavior in a disposable test target |
| Commit acknowledgement loss | Runtime reports unresolved; recovery finds the durable receipt |
| Missing configuration or replaced target | Recovery refuses to infer success |
| Backup restore | Recorded target identity and receipts survive; recovery does not manufacture missing evidence |

Server/transport fault injection must only target the harness-owned disposable container, never an existing staging or shared database. The harness does not accept an external DSN or container ID.

## Measurements before expanding use

Record snapshot time, commit time, end-to-end time, lock timeouts, errors, and receipt/revision counts. Measure serial operation first, then concurrent workers with separate connections and deliberately conflicting snapshots. Distinguish idempotent retries from fresh operations. Report median and tail latency alongside row count, candidate count, and run count; do not infer throughput from unit-test duration. Define acceptable latency and error thresholds against the intended workload before calling the pilot successful.

The current adapter uses a table write lock and reads the complete catalog for snapshots. The pilot should identify its useful workload size before proposing finer-grained locking or pagination. Such changes must preserve snapshot, receipt, and replay semantics.

## Operational handoff

Retain reports and journals with access controls and a retention policy appropriate for the catalog data. Back up target and journal, test restoring them, and document who handles unresolved operations. Keep credentials local and rotate them through the deployment platform. On interruption, stop the worker, restore connectivity, and reconcile the original journal. Absence of a receipt is not permission for an automatic retry. Escalate unresolved outcomes for inspection.

The public alpha release has not been replaced by these development commits. Deploy a reviewed exact commit or a separately verified wheel. Hosted endpoint setup, authentication/TLS, budget, workload selection, and performance thresholds must be supplied for a hosted pilot.
