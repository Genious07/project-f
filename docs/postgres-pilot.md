# PostgreSQL deployment pilot

Status: the owner selected a disposable local Docker pilot on 21 November 2026. The first synthetic pilot completed successfully. No hosted environment is selected or deployed. These local measurements are not evidence of production workload performance.

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

## Reproduce the local pilot

```sh
python tools/run_postgres_pilot.py --image postgres:18.4 --output build/local-pilot/report.json
```

Use the optional `--image` argument to select an official PostgreSQL 18 minor tag already cached locally; the default is `postgres:18`. The server version and image tag are recorded. Docker must be running. The runner owns its fresh container, schema, and restricted login role; it accepts no existing DSN. It removes the database and container after completion but retains a JSON summary and ten report/journal pairs beside it. Offline report replay remains possible; live reconciliation after target removal is expected to be unresolved.

Five trials each repair 100 and 500 synthetic rows using one candidate. Every trial verifies a single revision/receipt, correct arithmetic, denied source/receipt/identity changes under the runtime login, offline reproduction, and two read-only reconciliations. A separate four-worker contest uses the same base snapshot with distinct operation IDs, requiring one applied result and three stale receipts. Four subsequent retries of the winner must be idempotent, retaining one revision increment and four total receipts.

Timing records separate snapshot, CLI run, and CLI replay durations and preserve each raw sample. CLI timings include Python startup. The reported p95 is the nearest-rank statistic; with only five samples it is the maximum, not a reliable production tail estimate. Passing means the functional checks succeeded. No latency SLA was chosen or certified. Source commit, dirty-worktree status, host architecture, Python/Docker/server versions, and cleanup completion are captured for review.
