# Development progress

## Rust milestone day 1: alpha feedback baseline

Implemented on 2 October 2026.

- Added structured GitHub issue forms for compiler defects, runtime defects, resource adapter requests, and language proposals.
- Required defect reports to identify the version, platform, minimal source, expected behavior, actual behavior, reproduction commands, and whether a live effect occurred.
- Published the exact alpha compatibility contract for platforms, schemas, language constructs, commands, resource and provider boundaries, tested guarantees, input limits, and unsupported capabilities.
- Recorded the release-machine Python 3.9 mismatch as an environment selection issue. The supported Python 3.14 verification passed, so no product regression fixture was invented.

Validation: all issue forms parse as YAML and contain their required reproduction fields; repository checks remain green.

Next: day 2 Rust semantic architecture and rule-to-phase mapping.

## Day 10: developer alpha release

Implemented on 1 October 2026.

- Promoted the package to `0.1.0a1` and prepared the `v0.1.0-alpha.1` release.
- Updated the public project description, installation status, product explanation, release notes, and current limitations.
- Added a gated 15-day plan for the native Rust semantic compiler and initial language server.
- Prepared versioned wheel and source artifacts with SHA-256 checksums.

Local validation: 80 Python tests pass on Python 3.14; four Rust unit tests pass; all 28 shared frontend fixtures agree; clean wheel installation, the complete CLI workflow, cold backup/restore, and seven-run network-disabled container persistence pass. The release commit is also checked by the hosted Verify matrix before publication.

Next: execute the native Rust compiler milestone in `docs/next-15-days.md`.

## Day 9: packaging, installation, and CI

Implemented on 29 September 2026.

- Added pinned Python build backend requirements, wheel/source packaging, and artifact exclusions.
- Added a container with a pinned Python base image and an installed non-root CLI.
- Added verification scripts for clean wheel installation outside the checkout, cold backup/restore, and persistence across seven network-disabled container runs.
- Added GitHub Actions for Python 3.11 through 3.14 on Ubuntu, Python 3.14 on macOS, Rust tests/conformance on both systems, and container verification on Ubuntu.
- Fixed database connection cleanup in tests and verification tools exposed by Python 3.14 warnings.

Local validation: 74 Python tests pass; clean wheel install and full CLI workflow pass; cold backup/restore passes; container persistence passes. Two wheel builds with fixed SOURCE_DATE_EPOCH produced identical SHA-256 hashes. Hosted CI results are recorded in the Verify workflow; no alpha release or package registry publication is made by this milestone.

Next: Day 10 full alpha acceptance, release notes, and release gating.

## Day 8: Rust syntax frontend and conformance

Implemented on 28 September 2026.

- Added a Rust workspace, independent lexer/parser, source spans, structured diagnostics, and JSON syntax CLI.
- Pinned the Rust toolchain and Cargo lockfile; installed the development toolchain locally without changing shell startup configuration.
- Added 28 shared syntax fixtures and a runner comparing complete tokens/ASTs, spans, and diagnostic codes.
- Added a bridge from Rust syntax to the Python semantic checker and typed IR generator, with matching acceptance and IR for the shared fixtures.
- Published an explicit parity table: native Rust semantics/runtime remain unfinished, and Unicode identifiers and extreme nesting differ intentionally.

Validation: 74 Python tests, four Rust unit tests, and 28 shared conformance cases. Rust native typed IR lowering is deferred; the Python-backed bridge is the current checked path. Builds were verified on macOS arm64, with cross-platform CI deferred to Day 9.

Next: Day 9 packaging, CI, clean installation, and container workflow.

## Day 7: projects, provider contracts, and user data

Implemented on 27 September 2026.

- Added model/resource/journal/clock protocols and injectable providers. Project runs use supplied JSON candidates; fixture proposals remain the default for the demo.
- Added `init`, strict JSON configuration, entry selection, `run`, and `inspect`. Initialization seeds example rows only with `--demo-data`.
- Added existing-only catalog opening so ordinary runs do not create, migrate, or seed user targets.
- Validated candidate structure before opening the target and bounded candidates, patch counts, source/configuration sizes, and execution evidence.
- Normalized provider failures and ambiguous commit failures into explicit outcomes, and rejected semantic replay for incomplete evidence.

Validation: all 73 tests pass. Ten new tests cover the complete CLI workflow from a fresh project directory, empty targets without seeding, missing/unprepared targets, malformed fixtures before database access, invalid entry/configuration, overwrite refusal, custom rows and candidates without source edits, provider/clock injection, and evidence exhaustion before writes. Prior replay, crash, concurrency, and compiler coverage remains green.

Next: Day 8 Rust frontend and shared conformance fixtures. Installable artifact and container verification remain Day 9 work.

## Day 6: reproducible offline evidence

Implemented on 25 September 2026.

- Added report 0.0.2 / evidence 1 with checked IR, recorded snapshots and proposals, all exploration/selection events, and commit payloads and receipt references.
- Added a pure offline interpreter that recompiles recorded IR and recomputes checks, metrics, eligibility, and selection without opening a database or invoking a provider.
- Compared ordered evidence and final summaries; rejected inconsistent values even after checksum recomputation.
- Distinguished checksum validity, decision reproduction, unauthenticated origin, and unverified target effects. Legacy reports explicitly remain checksum-only.
- Documented redaction, retention, compatibility, and replay's trust limits.

Validation: all 63 tests pass. Ten new tests cover disabled live access, edited metrics/checks/winners with recomputed checksums, incomplete/reordered/trailing events, program and type mismatches, snapshot/receipt consistency, redacted evidence, legacy reports, and reproduction of no-winner, stale, and multiple-operation runs. Earlier compiler, transaction, and subprocess recovery coverage remains green.

Next: Day 7 provider interfaces, project initialization, configuration, and running on user-prepared data with a usable CLI.

## Day 5: durable intent and crash reconciliation

Implemented on 24 September 2026.

- Added a durable SQLite run journal with run IDs, per-operation IDs, selected payloads, target identity, and explicit states.
- Persisted intent before invoking the target adapter and recorded terminal acknowledgements afterward.
- Added `reconcile`, which reads target receipts through a read-only connection, validates identity and intent, and updates only the journal.
- Added explicit process-termination fault points before the transaction, before commit, and after commit but before acknowledgement.
- Preserved unresolved states for missing or inconsistent evidence; no automatic operation replay or full report reconstruction.

Validation: all 53 tests pass. Eleven recovery tests cover subprocess crashes at all three boundaries, repeated reconciliation, stale receipt recovery, missing/replaced targets, inconsistent journal/receipt data, completed and started runs, missing journals, multiple operations, and completed no-winner runs. Existing language, ownership, transaction, and concurrency tests remain green.

Next: Day 6 recorded execution evidence and deterministic offline re-evaluation. Current replay remains checksum verification only.

## Day 4: SQLite transaction correctness

Implemented on 23 September 2026.

- Read snapshots in a consistent transaction while preserving caller-owned transactions.
- Moved receipt lookup inside BEGIN IMMEDIATE so concurrent retries return the same terminal result.
- Separated operation identity from intent, with explicit optional operation IDs and conflict rejection.
- Validated patch shapes, scalar bounds, duplicate targets, row existence, and arithmetic before writes; checked resulting rows and revision before storing the applied receipt.
- Documented adapter protocol 2, older receipt compatibility, and the supported writer model.

Validation: all 42 tests pass. Nine new tests cover a four-connection retry race, conflicting intents, default identity independence, a deterministic WAL writer interleaved between snapshot reads, invalid patch cases, receipt-insert rollback, unexpected trigger effects, terminal stale retries, and preservation of caller transactions. Existing language/runtime tests remain green.

Next: Day 5 durable run identities, crash injection, and receipt-based reconciliation. Receipt migration from earlier protocol versions is not automatic.

## Day 3: selection ownership and isolated branches

Implemented on 22 September 2026.

- Enforced selection consumption through aliases at compile time and issued opaque runtime tokens with copied payloads.
- Rejected forged, foreign, and consumed selection tokens before adapter invocation; consumption persists if the adapter raises.
- Enforced exactly one simulation per branch, read-only scalar snapshot rows, and independently copied candidate/branch inputs.
- Issued completed exploration tokens, enforced unique candidate IDs, and preserved deterministic tie breaking.
- Added structured rejected/evaluation-failed candidate statuses and no-winner/invalid-plan-set outcomes with no writes.
- Bumped IR semantics to 0.0.3 and documented ownership, low-level adapter trust, and version compatibility.

Validation: all 33 tests pass. Eleven new tests cover compiler alias reuse, legal single consumption, simulation counts, runtime forgery/reuse/foreign tokens, adapter exceptions, forged trials, snapshot mutation, branch isolation, order-independent ties, no-winner failures, and duplicate IDs. Existing commit, stale-state, type, and report verification tests remain green.

Next: Day 4 consistent snapshot reads, receipt lookup within the write transaction, strict commit-boundary patch checks, and concurrent retry tests. Reconciliation and semantic replay remain later work.

## Day 2: typed IR and static snapshot identity

Implemented on 21 September 2026.

- Added immutable inferred type records and emitted types for every IR expression.
- Propagated resource and snapshot lineage through proposal sets, candidate plans, simulation, trials, selection, and outcomes; rejected mixed-origin exploration and checks.
- Added checked scalar and resource-bearing let annotations.
- Canonicalized effects and removed source positions and annotations from executable identity. Formatting and comments no longer affect program digests.
- Versioned typed IR as 0.0.2; runtime rejects unsupported versions with a rebuild instruction.

Validation: all 22 unittest methods pass. New coverage includes every-expression type emission, lineage propagation, mixed-snapshot proposals/comparisons/metrics, mismatched method receivers, alias identity, valid and invalid annotations, formatting and effect-order stability, semantic digest changes, duplicate metrics, invalid returns, and schema rejection. Existing runtime and Day 1 regression tests still pass.

Scope: one-resource programs remain the executable subset. This milestone enforces static lineage for checked source; it does not authenticate edited IR or prevent selection reuse. Day 3 adds selection ownership and stronger branch isolation.

## Day 1: executable subset validation

Implemented on 20 September 2026.

- Added a shared signature registry for supported types, effects, method arguments and results, and forbidden branch operations.
- Rejected empty or ambiguous programs, unsupported declarations and annotations, malformed proposals, invalid effects, unknown methods, invalid arguments, non-Boolean checks, invalid metrics, reserved bindings, and invalid return placement.
- Restricted the bootstrap to one resource, model, and decision, reflecting its actual runtime scope.
- Replaced unrestricted Python method lookup with an explicit dispatch table. Added runtime guards for branch effects and scalar results, and stopped execution at return.
- Corrected the contract's capability, transaction ordering, and replay claims.

Validation: all 11 unittest methods pass, including 25 invalid-source subcases checked both through the compiler and the CLI. Each rejected CLI case asserts that no database adapter is opened. Existing selection, applied commit, stale rejection, sequential retry, and offline checksum verification tests still pass. Runtime tests independently exercise forbidden branch effects and unknown method dispatch.

Remaining: typed IR and snapshot/resource lineage are Day 2 work. Affine selections, strong immutable branch representations, concurrent transaction correctness, recovery, and reproducible replay remain subsequent milestones. Runtime guards do not validate arbitrary untrusted IR or sandbox Python callers.
