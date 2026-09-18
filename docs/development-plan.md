# Project F: ten-day development plan

## Goal and scope

Build a usable developer alpha of Foresee, the working name for Project F's decision language. A developer should be able to install it, write a small decision program, explore fixture-proposed catalog repairs, inspect why a candidate won, commit safely to their own SQLite catalog, and verify the recorded execution offline.

The first ten days focus on trustworthy semantics and an independently usable CLI. The Python implementation remains the execution reference. A Rust compiler frontend starts after the reference semantics stabilize. A complete Rust runtime, distributed execution, arbitrary external API writes, a general-purpose language, and a hosted service are outside this release.

Day 1 means the next implementation session after this plan is published. These are ten planned development days, not ten automatic scheduled runs. Publishing this plan does not schedule unattended work. Each day has a reviewable commit and GitHub push after its acceptance checks pass. If a check fails, fix it or record the blocker before advancing. Do not label unfinished work complete to fit the calendar.

## Starting point

The baseline has a lexer, parser, basic effect checker, JSON IR, fixture proposals, candidate exploration, a SQLite repair demo, receipt storage, and report checksums. Eight tests passed at the baseline milestone. This is evidence for the covered paths only.

Known gaps drive the order below: incomplete typing and effect validation, unrestricted method dispatch, reusable selections, non-atomic snapshot reads, receipt lookup outside the write transaction, weak patch validation, and report verification that does not reproduce decisions. A checksum alone provides no protection against someone editing a report and recomputing its checksum.

## Day 1: define and enforce the executable subset

Work:
- Define supported declaration types, effect kinds, method names, argument counts, and return types in one compiler signature registry.
- Reject unknown methods, malformed proposals, invalid effects, empty programs, ambiguous entry points, and unsupported syntax with source diagnostics.
- Replace runtime `getattr` dispatch with explicit allowed operations. Prevent snapshots, proposals, nested exploration, and live effects inside branches unless their semantics are explicitly supported.
- Correct documentation where the current implementation promises more than it enforces.

Deliverable: a precise subset contract and compiler/runtime validation boundary.

Acceptance: negative fixtures demonstrate each forbidden path is rejected before database mutation; the existing repair example still runs. Commit and push the contract, implementation, and regression tests.

## Day 2: typed IR and resource identity

Work:
- Introduce explicit types for `Snapshot<R>`, `Plan<R>`, plan sets, `Trials<R, M>`, `Selected<R>`, scalar values, and outcomes.
- Bind plans, simulations, checks, and selections to the same declared resource and snapshot lineage.
- Validate Boolean checks, integer metrics, unique metric names, annotations, and decision return types.
- Version the IR and define canonical serialization independently of source locations so formatting edits do not change semantic identity.

Deliverable: inspectable typed IR with deterministic digests and documented version rules.

Acceptance: cross-resource and cross-snapshot combinations, incorrect annotations, duplicate metrics, and invalid arguments fail compilation. Equivalent source formatting produces the same semantic digest. Commit and push the typed pipeline.

## Day 3: single-use selections and deterministic branches

Work:
- Track ownership of `Selected<R>` through aliases and consume it on commit. Reject subsequent use.
- Represent runtime selections as internal capability objects with provenance rather than ordinary dictionaries accepted as proof.
- Enforce the initial one-simulation-per-branch rule, immutable branch inputs, complete candidate evaluation, and deterministic tie breaking.
- Define structured outcomes for no eligible candidate, rejected plans, and branch evaluation failure.

Deliverable: enforceable selection ownership and a documented deterministic exploration model.

Acceptance: double commit, alias reuse, forged selection through supported runtime entry points, and branch state leakage are rejected. Candidate order changes preserve the winner under the specified tie policy. Commit and push ownership and isolation tests with the implementation.

## Day 4: SQLite transaction correctness

Work:
- Read each snapshot within one consistent database transaction.
- Move receipt lookup inside the commit transaction so concurrent retries observe the same durable result.
- Validate patch structure, row identity, duplicate patches, field allowlists, integer values, and arithmetic invariants at the commit boundary.
- Recheck freshness and permitted postconditions in the transaction that writes both data and receipt.
- Define stable operation identity separately from the intent digest and document the supported writer model.

Deliverable: a catalog adapter with documented atomicity, freshness, and retry behavior.

Acceptance: independent connections racing the same operation create one effect and one receipt; conflicting intents fail; stale or invalid plans leave domain rows unchanged; a failed receipt insert rolls back domain writes. Commit and push the hardened adapter.

## Day 5: crash recovery and reconciliation

Work:
- Introduce explicit run and operation states with durable identifiers.
- Add controlled fault injection before transaction start, before commit, and after commit but before the caller receives the result.
- Add a reconciliation command that reads target receipts and resolves interrupted runs without blindly reapplying changes.
- Document the boundary of the guarantee: it applies to this SQLite transaction protocol, not arbitrary APIs.

Deliverable: recoverable local runs and a user-facing reconciliation workflow.

Acceptance: subprocess termination at each fault point followed by restart produces a correct recorded outcome without duplicate writes. Missing or inconsistent evidence returns an explicit unresolved result. Commit and push recovery code and fault tests.

## Day 6: reproducible offline evidence

Work:
- Version an evidence bundle containing the relevant snapshot, plans, typed program identity, checks, metrics, selection policy, and receipt reference.
- Add deterministic offline re-evaluation of checks, metrics, and selection using recorded inputs.
- Distinguish checksum integrity, reproduced decision results, and authenticated origin in CLI output. Do not describe checksums as signatures.
- Define redaction and retention rules and reject incomplete evidence when reproduction requires omitted data.

Deliverable: a replay command that can explain and reproduce a recorded choice without a live provider or database.

Acceptance: replay succeeds with providers unavailable; changed scores, missing inputs, mismatched program identity, and inconsistent selection are detected. Recomputed checksums do not bypass semantic verification. Origin authentication remains explicitly unsupported until implemented. Commit and push the evidence format and replay engine.

## Day 7: provider interfaces and a usable CLI

Work:
- Extract model, resource, journal, and clock interfaces with the fixture provider as the default.
- Add project initialization, explicit configuration, entry-point selection, and clear commands for check, build, run, inspect, replay, and reconcile.
- Accept a documented user-supplied SQLite catalog schema and user-supplied candidate fixtures. Keep demo seeding an explicit demo operation.
- Define bounds for candidate count and evidence size. Normalize provider errors into structured outcomes.

Deliverable: someone outside this repository can run a decision on their own prepared data.

Acceptance: a temporary clean project completes the documented workflow without source edits or API keys; malformed fixtures fail before writes; ordinary runs do not seed or silently replace user data. Commit and push CLI and provider contracts.

## Day 8: Rust frontend and shared conformance fixtures

Work:
- Establish a Rust workspace and port lexer, parser, source spans, and diagnostics for the frozen subset.
- Share valid and invalid language fixtures with Python and define the typed IR interchange contract.
- Begin lowering the accepted syntax to the shared IR. Keep Python responsible for runtime execution during this milestone.

Deliverable: a Rust frontend with measured compatibility against the reference implementation.

Acceptance: all supported syntax fixtures have matching acceptance and normalized syntax output; unsupported features are explicitly rejected. Publish an honest parity table. If frontend parity takes longer, defer Rust IR lowering and preserve the Python alpha schedule. Commit and push the Rust workspace and conformance results.

## Day 9: packaging, CI, and installation

Work:
- Add reproducible Python packaging, a container entry point, and a supported-version test matrix.
- Run compiler, adapter, recovery, replay, and cross-language conformance checks in GitHub Actions without model credentials.
- Document installation, persistent database/evidence volumes, backup and restore, and the limits of the local trust model.
- Test built artifacts outside the source checkout and record exact version requirements.

Deliverable: installable CLI artifacts and repeatable self-hosted execution.

Acceptance: a fresh virtual environment and container both complete the sample workflow from published instructions; files persist across container restarts; CI passes. Commit and push packaging, workflows, and operating instructions.

## Day 10: alpha acceptance and release

Work:
- Run the full user journey on a fresh sample catalog: install, initialize, check, build, explore, inspect, commit, replay, and reconcile.
- Run stale-state, invalid-plan, retry, crash, and no-winner demonstrations and record actual outcomes.
- Review compiler/runtime claims against tests and list remaining limitations.
- Publish a versioned alpha release with source, installable artifacts, checksums, release notes, and the next milestone backlog.

Deliverable: a public developer alpha that another person can install and use independently for the supported SQLite domain.

Acceptance: all release gates above pass and documentation agrees with shipped behavior. Commit and push release preparation, then tag and publish only when the gate is met. If a correctness gate fails, publish progress and the blocker instead of a release-ready claim.

## Daily GitHub discipline

- Inspect changes and run the day's meaningful acceptance checks.
- Record implemented behavior, results, and remaining gaps in release notes or a progress log.
- Commit with a descriptive message and no AI co-author trailer or em dash.
- Push the verified commit and confirm the remote commit matches the local commit.
- Publish only project material. Exclude credentials, local databases, private datasets, and unrelated workspace files.

## Later milestones

After alpha feedback, prioritize a complete Rust type checker/runtime, an editor language server, authenticated evidence, additional resource adapters with conformance tests, and optional real model providers. Model access must remain explicit and bounded. Add a visual inspector only when the CLI evidence schema is stable enough to support it.
