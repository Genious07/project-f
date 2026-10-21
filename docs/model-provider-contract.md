# Bounded model-provider contract

Implemented on 18 October 2026. This milestone adds an opt-in Python API for obtaining proposals through a bounded JSON exchange. It includes a trusted subprocess transport and an offline example worker. No external model service, network request, credential discovery, paid inference, or project configuration change is enabled by default.

## Design

A provider proposes data. It does not select a candidate, grant permission, mutate a catalog, or bypass the language's checks. The runtime still simulates each accepted candidate, evaluates checks and metrics, selects a valid result, and uses the existing transactional commit protocol.

`BoundedModelProvider` implements the existing `ModelProvider.propose(base, prompt, limit)` interface. One provider instance owns one call budget; create a new instance for a new execution budget. Calls that reach the transport consume budget even if they fail. Invalid or oversized requests do not call the transport. There are no retries, fixture fallbacks, or silent candidate truncation. Concurrent/reentrant calls are rejected as busy.

| Limit | Default | Allowed configuration |
| --- | --- | --- |
| Calls per provider instance | 1 | 1 to 100 |
| Candidates per proposal | 4 | 1 to 4, also bounded by the program's requested limit |
| Patches per candidate | 1,000 | 1 to 1,000 |
| Serialized request bytes | 262,144 | 1 to 2,000,000 |
| Response bytes | 262,144 | 1 to 2,000,000 |
| Exchange deadline | 10 seconds | Positive finite value up to 120 seconds |

These are calls, bytes, and wall-clock limits. They are not model token limits, monetary budgets, or an operating-system memory quota. A future paid provider must separately implement token and spend controls.

## Wire protocol version 1

The request is UTF-8 JSON encoded with sorted keys, compact separators, ASCII escapes, and finite numbers only:

```json
{
  "version": 1,
  "snapshot": {"revision": 0, "digest": "snapshot-content-digest", "rows": []},
  "prompt": "Fill derived unit prices",
  "limit": 4
}
```

Rows contain the full snapshot data. Explicitly choosing a transport therefore also chooses where this data is sent. The current transport sends it only to the configured local command. Request size is checked before launching the transport.

The response has exactly these three fields:

```json
{
  "version": 1,
  "request_digest": "sha256-of-the-exact-request-bytes",
  "plans": [{"id": "repair", "patches": [{"id": "coffee", "unit_price_cents": 150}]}]
}
```

The digest binds the reply to the request; it does not authenticate the provider. Responses must be UTF-8 bytes within budget. Invalid JSON, duplicate keys at any depth, non-finite JSON constants, extra envelope fields, incorrect versions, wrong request digests, excessive counts, duplicate plan IDs, and invalid patch structures are rejected. Booleans are not integer versions or prices. Prices must fit a nonnegative SQLite integer. Empty candidate lists are allowed and follow the existing no-eligible-candidate path.

A plan contains only `id` and `patches`. A patch contains only `id` and `unit_price_cents`; row IDs cannot repeat within a plan. Arithmetic correctness, existing-row membership, selection, and commit still belong to simulation and the resource adapter. Schema acceptance is not permission to apply a patch.

## Process transport

`ProcessTransport` launches an explicit argument vector without a shell. The worker reads the bounded request from stdin and returns a single JSON response on stdout, then exits successfully. Stderr is discarded to keep worker secrets out of runtime reports. Nonzero exit is an error even if stdout contains valid JSON.

Input is supplied through a temporary file, preventing a worker that ignores stdin from blocking the parent in a pipe write. The parent reads stdout incrementally, stops at the output cap, checks a monotonic deadline, and terminates/reaps the worker's process group on completion or failure. A descendant keeping stdout open cannot extend the deadline. Process creation itself depends on the operating system; the deadline is checked after creation returns.

This implementation supports POSIX systems, tested on Linux and macOS. It is not a sandbox: a configured command runs with the user's permissions and inherited environment, and could access files or the network. Only use trusted commands. Deliberately detached subprocesses are outside process-group cleanup. Resource-limited or untrusted model workers need a separate sandbox design.

A custom `ProposalTransport.exchange` must itself enforce deadlines and bounded streaming. The wrapper rejects late or oversized results defensively, but cannot interrupt an arbitrary Python transport that blocks forever. The supplied process transport provides the concrete termination boundary.

## Use the offline example

From a checkout, the following Python API runs the example worker with an existing catalog:

```python
import sys
from pathlib import Path
from foresee.catalog import Catalog
from foresee.compiler import compile_source
from foresee.model_provider import BoundedModelProvider, ProcessTransport, ProposalBudget
from foresee.runtime import Runtime, save_report

ir = compile_source(Path("examples/repair.fore").read_text())
provider = BoundedModelProvider(
    ProcessTransport([sys.executable, str(Path("examples/proposal_worker.py").resolve())]),
    ProposalBudget(max_calls=1, timeout_seconds=10),
)
catalog = Catalog(Path("catalog.db"), existing=True)
try:
    report = Runtime(ir, catalog, model_provider=provider).run()
    save_report(report, Path("proposal-report.json"))
finally:
    catalog.close()
```

This runs a decision and can commit the selected repair to the existing catalog. The example worker deterministically proposes derived unit prices; it is not a model implementation or a production pricing policy. The existing CLI/project file format and default fixture provider remain unchanged. The example is included in source distributions; the provider module is included in the Python wheel.

## Errors and replay

Stable provider codes are `invalid_request`, `request_limit`, `call_limit`, `busy`, `timeout`, `transport_error`, `response_limit`, and `invalid_response`. Runtime failures use outcome status `provider_error` with an additional `provider_code`. Raw transport exceptions and stderr are excluded. Failure prevents exploration and commit for that proposal and marks execution evidence incomplete. Earlier runtime events remain available for diagnosis; failed runs do not claim reproducible complete evidence.

Accepted proposals are recorded by the existing proposal event with model name, snapshot digest, prompt, requested limit, and validated plans. Offline replay uses those records and reruns decision logic without invoking the transport or opening the target. Replay does not regenerate model output or authenticate its origin. Raw model responses and transport credentials are not added to the report.

Thirteen new tests cover request/response budgets, call exhaustion, strict schemas, error sanitization, timeout and descendant cleanup, actual process integration, no commit on provider failure, and offline replay. All tests use local data without credentials.

## Next step

Implemented on 21 October: the [opt-in OpenAI adapter](openai-provider.md) adds explicit model selection, a fixed official endpoint, token preflight, cost reservations, bounded HTTP reads, and local process termination. It remains disabled by default; tests remain credential-free. Local termination does not guarantee server-side cancellation. Next is the resource-adapter conformance kit. The v0.2 license/publication decision remains separate.
