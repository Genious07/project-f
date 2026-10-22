# Resource-adapter conformance kit

Implemented on 22 October 2026. The kit provides reusable behavioral checks for storage adapters implementing Foresee's current Catalog/Patch domain. It ships in the Python package and runs against SQLite in ordinary tests and from a clean wheel installation outside the repository.

```sh
python -m foresee.conformance
```

This creates fresh temporary databases, runs twelve contract checks, cleans them up, and exits nonzero on failure. It accepts no existing target path. No model credentials or network services are used.

## Contract coverage

| Check | Required behavior |
| --- | --- |
| Snapshot isolation | Returned rows are immutable and retain their content after an external mutation; reopened connections retain target identity |
| Simulation | A valid plan changes simulated rows without changing persisted rows, revision, or receipts |
| Durable commit | Expected rows, one revision increment, and one matching receipt are visible through a fresh connection |
| Idempotent retry | Reopening and retrying the same operation returns the original commit identity without another effect |
| Conflicting intent | Reusing an operation ID for a changed plan is rejected without additional writes |
| Invalid plan | Rejection leaves rows, revision, and receipt inventory unchanged |
| Stale snapshot | Stale rejection is durable and remains terminal on retry, with no proposal patches applied |
| Precommit failures | Injected failures before the transaction and before commit roll back writes; another connection cannot observe uncommitted changes |
| Receipt failure | Failed receipt creation rolls back the data effect, and the target remains usable afterward |
| Lost acknowledgment | Failure after commit leaves one durable effect/receipt; reopening and retrying recovers it without duplication |
| Concurrent retry | Four independent connections racing the same operation produce one effect, one receipt, and three replay outcomes |
| Offline evidence | The normal runtime can execute the fixture's plan and reproduce its report through the offline replay engine |

Three deliberately broken fixtures verify that the kit rejects missing receipts, simulation writes, and ignored fault hooks. The existing SQLite-specific tests still cover actual process termination, repeated journal reconciliation, receipt corruption, replacement targets, triggers, and interleaved snapshot reads. This kit complements those tests rather than replacing them.

## Implement a fixture for another adapter

Export a factory accepting a fresh temporary directory and returning an object conforming to `foresee.conformance.AdapterFixture`. The factory must initialize a disposable populated target with no receipts. Its valid plan must change at least one row and pass the existing catalog arithmetic checks.

| Fixture method | Responsibility |
| --- | --- |
| `connect()` | Open an independent adapter with `target_id`, `snapshot`, `commit`, and `close`; threads open their connections inside the thread |
| `valid_plan(base)` | Return a valid changing plan in the current Catalog/Patch schema |
| `invalid_plan(base)` | Return a plan the adapter must reject without persisting changes |
| `simulate(base, plan)` | Exercise the adapter's simulation behavior, returning a snapshot |
| `mutate()` | Persist an independent external mutation so an earlier snapshot becomes stale |
| `receipts()` | Read persisted receipts in stable order, including at least `commit_id` and `status` |
| `fail_receipt_write()` | Context manager that forces receipt creation to fail, then removes the injected fault |

Receipt and mutation helpers must inspect or alter the disposable backing store directly. Do not implement the adapter's commit behavior in fixture helpers or fabricate receipts from returned outcomes. `CatalogFixture` in `foresee/catalog_conformance.py` is the SQLite reference driver; SQL-specific setup and fault injection stay there, outside the shared contract tests.

The adapter must support `commit(selection, program_digest, operation_id=..., fault_hook=...)`. Fault hooks expose `before_transaction`, `before_commit`, and `after_commit`. Selection contains a serialized base snapshot and a plan. The commit result includes `status`, `commit_id`, `revision`, and `idempotent_replay`. Changed intent must raise `ValueError` or `RuntimeError`; receipt persistence can raise the backing store's own exception.

Register your fixture in unittest:

```python
from foresee.conformance import adapter_suite
from my_adapter_tests import MyAdapterFixture

def load_tests(loader, tests, pattern):
    tests.addTests(adapter_suite(MyAdapterFixture, 'MyAdapter'))
    return tests
```

Each contract case gets its own directory and target. The fixture must keep all state inside that directory or allocate an equivalently isolated test resource whose cleanup it owns. It must never resolve to a production store. Connection closure precedes directory cleanup. Run external adapters under a process timeout: the kit cannot interrupt an arbitrary adapter that blocks forever.

## Scope and limits

The current profile assumes Foresee snapshots, a monotonic revision, durable receipts, operation identities, and the Catalog/Patch plan schema. It does not certify arbitrary resource domains or expose a generic adapter plugin registry. Runtime simulation/check methods and journal recovery still contain SQLite/catalog-specific behavior. A future adapter must be integrated into those paths before it can be used as a runtime replacement.

Injected exceptions are not equivalent to abrupt process loss or power failure. The SQLite process-crash tests remain necessary; every additional persistent adapter must provide its own process-kill/reopen tests, durability evidence, and reconciliation integration. The concurrent test exercises four retries of one operation, not all interleavings or a proof of serializability.

Offline replay verifies the recorded decision from captured inputs and proposals. It does not authenticate the evidence's origin or independently prove a target effect occurred. The fixture's storage inspection is trusted test instrumentation, not an attestation mechanism.

## Current acceptance

SQLite passes all twelve contract checks. The Python suite has 151 passing tests, including the three broken-fixture probes and the existing transaction/recovery/replay tests. Hosted Python jobs run the suite across supported Python versions, then install the wheel in a new environment and run the kit again outside the checkout.

The previous OpenAI-adapter CI run also passed after retrying GitHub's artifact-upload failure. Live API compatibility remains unverified, and the compiler release still awaits the project license choice.

Next: define the authenticated-evidence threat model and key/verification contract, followed by a second transactional adapter with its own recovery integration and crash tests.
