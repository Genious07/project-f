# Opt-in OpenAI proposal adapter

Implemented on 21 October 2026. Foresee can obtain proposals through the OpenAI Responses API while retaining the bounded proposal contract, simulation checks, transactional commit path, and offline replay.

The adapter is available through the Python API. Existing project files, CLI commands, and fixture defaults remain unchanged. Importing or constructing it does not contact a service. A live proposal requires an explicit model, token ceilings, configured price ceilings, a reservation budget, and `OPENAI_API_KEY` in the worker environment.

## API contract

The worker sends the snapshot and prompt to `https://api.openai.com/v1/responses/input_tokens` first. If the count exceeds the configured input-token cap, generation is not attempted. The generation request uses the same model, instructions, input, and JSON schema, with `max_output_tokens`, `store: false`, nonstreaming output, and the default service tier. No tools, conversation history, automatic retries, or model fallback are enabled. See OpenAI's [token-counting guide](https://developers.openai.com/api/docs/guides/token-counting).

The model must support Responses, input-token counting, and strict structured output. Unsupported combinations fail explicitly; there is no default model or automatic model substitution. The adapter requests a `plans` object through `text.format`, checks response completion and usage, rejects refusals, and passes the result through Foresee's existing strict candidate validation. See [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Only the official HTTPS endpoint is supported. There is no configurable base URL. Redirects and environment proxies are disabled, and Python's default TLS certificate verification remains enabled. HTTP bodies are capped at 2 MB before JSON decoding. A subprocess enforces the overall local deadline across token counting and generation. The worker reads credentials from the environment; keys are not placed in command arguments, job JSON, runtime evidence, or error messages.

## Cost reservations

`OpenAIConfig` requires these fields:

| Field | Meaning |
| --- | --- |
| `model` | Explicit supported model ID, preferably a pinned version |
| `max_input_tokens` | Maximum input accepted by preflight, 1 to 1,000,000 |
| `max_output_tokens` | Generation cap, 1 to 100,000; the selected model may impose stricter limits |
| `input_price_micro_usd_per_million` | User-supplied upper price for one million input tokens, in micro-USD |
| `output_price_micro_usd_per_million` | User-supplied upper price for one million output tokens, in micro-USD |
| `max_reserved_micro_usd` | Maximum cumulative local reservation for this transport instance |

One USD is 1,000,000 micro-USD. Before starting a worker, the adapter reserves:

```text
ceil((max_input_tokens * input_price_micro_usd_per_million
    + max_output_tokens * output_price_micro_usd_per_million) / 1,000,000)
```

Arithmetic uses integers. Insufficient budget prevents the worker from starting. Reservations are never refunded, including missing credentials, rejected preflight, refusals, HTTP failures, or timeouts. This is intentionally conservative. The transport's `reserved_micro_usd` property exposes its current reservation total. One instance owns an in-memory ledger; sharing that instance shares the ledger. Creating a new instance or restarting the process starts a new budget.

This is a configured generation-cost estimate, not a billing-system or account-wide hard cap. It depends on your supplied rates covering the actual selected model and input tier. It does not account for taxes, unrelated usage, or any separate service fees. Check the [current pricing](https://developers.openai.com/api/docs/pricing) before setting the ceilings. There are no embedded price quotes or assumed discounts. Reported usage above a configured token cap rejects the result, but rejection cannot undo a charge already incurred.

Killing the worker stops local waiting and closes its connection; it does not guarantee server-side cancellation or zero charges. Keeping the full reservation after failure avoids treating uncertain attempts as free. Persistent cross-process accounting and provider-side cancellation are future work.

## Explicit usage

Prepare a local `model-budget.json` containing the six fields above, using your chosen model and verified price ceilings. Keep the credential in your environment or secret manager, outside that file and source control. The following replaces only the provider construction from the [bounded-provider example](model-provider-contract.md):

```python
import json
from pathlib import Path
from foresee.model_provider import ProposalBudget
from foresee.openai_provider import OpenAIConfig, openai_provider

config = OpenAIConfig(**json.loads(Path("model-budget.json").read_text()))
provider = openai_provider(
    config,
    ProposalBudget(max_calls=1, timeout_seconds=30, max_response_bytes=262144),
)
# Pass model_provider=provider to Runtime(...).
# Runtime.run() can send the snapshot/prompt and commit a validated repair.
```

The full snapshot and prompt leave the machine during token preflight, even if generation is later refused by a token limit. Use a catalog you intend to share with the provider. `store: false` is a request setting, not a claim about account-wide data retention. The shipped CI tests never send this data to a live service.

## Failure and replay behavior

In addition to the bounded provider's existing errors, the adapter reports `spend_limit`, `missing_credentials`, `authentication_error`, `rate_limit`, `http_error`, `input_token_limit`, `usage_limit`, `model_refusal`, and `incomplete_response`. API error bodies and raw exception messages are not surfaced. There are no automatic retries, including on rate limits.

The adapter computes the proposal request digest locally. The model does not supply a trusted digest or authorize a patch. Wrong types, duplicate IDs, excessive plans/patches, extra patch fields, and out-of-range prices still fail in `BoundedModelProvider`. Accepted candidates still undergo runtime simulation and checks. Provider failure marks evidence incomplete and prevents that proposal from reaching commit.

Existing evidence records the logical model binding, prompt, snapshot identity, and validated plans. Offline replay consumes those plans without API calls. It does not reproduce nondeterministic model generation, authenticate the model, or record API usage as a billing receipt. The transport reservation is an operational counter rather than authenticated execution evidence.

## Verification and limits

Thirteen new offline tests cover shared preflight/generation inputs, token limits, strict response/refusal handling, integer cost accounting, budget exhaustion, no refunds, HTTP bounds/errors, endpoint restrictions, credential handling, runtime validation, and replay with live access disabled. An actual worker process is tested with an explicitly empty API key. Clean-wheel verification also launches the installed worker outside the checkout without credentials.

No paid/live API call was made during this milestone. Compatibility with a particular account and model remains to be verified by an explicitly configured live smoke test. Linux and macOS use the existing POSIX process boundary; Windows remains unsupported for this transport. A selected model can impose limits beyond these local bounds.

Implemented on 22 October: the [resource-adapter conformance kit](adapter-conformance.md), covering isolation, stale snapshots, atomic commit, injected failures, and replay. The existing SQLite process-crash tests remain separate. Next is the authenticated-evidence threat model and verification contract.
