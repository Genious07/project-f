# Development progress

## Evidence milestone: Ed25519 signatures and explicit trust policy

Implemented on 25 October 2026.

- Added optional maintained cryptography backend and a low-level DSSE statement-signing primitive that verifies the caller-owned key fingerprint.
- Added bounded, strict local trust-policy parsing and exact-byte signature verification with explicit issuer, audience, clock, maximum lifetime, validity, rotation, and revocation checks.
- Kept authenticated origin separate from semantic replay and target-effect verification. Existing unsigned replay remains unchanged; the new authentication API does not access live targets or providers.
- Added fourteen tests covering a published RFC vector, tampering even after checksum recomputation, protocol binding, wrong keys, policy rejection, time boundaries, key rotation/revocation, missing dependency, and a real report with live access disabled. CI also runs them against the installed optional extra outside the checkout.

Local validation: 174 Python tests pass. The full hosted compiler, package, container, and archive gates remain required. Next: bounded semantic replay, then key custody and no-overwrite signing CLI integration. These primitives are experimental and do not complete the authenticated-report workflow. The v0.2 prerelease remains pending the license choice.

## Evidence milestone: authentication design and format scaffolding

Implemented on 24 October 2026.

- Defined the threat model and separate checksum, replay, signature, trusted-origin, and target-effect claims. Documented operator-owned keys, explicit trust policy, rotation/revocation, audience/time rules, and remaining limitations.
- Proposed a single-signature DSSE/Ed25519 profile that binds exact report bytes and signed issuer/audience/key metadata. Private-key handling and cryptographic verification are explicit subsequent gates.
- Added bounded JSON/base64 parsing, report checksum/eligibility checks, DSSE framing, key fingerprints, envelope serialization, and immutable inspection results. Inspection never claims signature verification or authenticated origin.
- Added nine format tests covering framing, byte preservation, malformed input, bounds, checksums, metadata, and real runtime reports. Existing replay behavior and package dependencies remain unchanged.

Local validation: all 160 Python tests pass. This is design and format groundwork, not a signature implementation or security certification. No signing keys were generated, no reports were signed, and no new release was published. Next: maintained Ed25519 backend, trusted-key policy validation, isolated replay, and installed signing/verification workflows. The project license decision remains open.

## Runtime milestone: resource-adapter conformance kit

Implemented on 22 October 2026.

- Added a reusable twelve-case adapter contract suite with disposable fixtures and a SQLite driver separated from the shared behavioral checks.
- Covered immutable snapshots, simulation isolation, durable/idempotent commits, changed intents, invalid plans, stale receipts, precommit rollback/visibility, receipt-write failures, lost acknowledgments, concurrent retries, and offline report replay.
- Added three broken-fixture probes to demonstrate that missing receipts, simulation writes, and ignored fault hooks fail the contract.
- Added an installed entry point (`python -m foresee.conformance`) and clean-wheel verification outside the checkout. Existing SQLite process-crash and journal tests remain mandatory.

Local validation: all 151 Python tests pass, including twelve SQLite contract cases and three kit probes. The previous OpenAI-adapter CI run is now green after retrying the artifact-upload failure. This profile covers Catalog/Patch-compatible stores; generic runtime dispatch, new resource domains, and power-loss guarantees remain outside scope. Next: authenticated-evidence threat model and key/verification contract. The compiler release remains pending the project license choice.

## Runtime milestone: opt-in OpenAI proposal adapter

Implemented on 21 October 2026.

- Added an explicit Responses adapter with no default model, token preflight, strict structured output, output-token limits, and no automatic retries or tools.
- Added integer cost reservations from caller-supplied price ceilings. Failed or uncertain attempts retain their full reservation; budget is scoped to one transport instance and is not an account-wide billing cap.
- Isolated HTTP in the existing bounded worker process, pinned the official HTTPS endpoint, disabled redirects/proxies, capped response reads, and sanitized failures. Local termination does not guarantee remote cancellation.
- Added thirteen offline tests and a clean-wheel worker smoke check. Accepted proposals retain existing simulation, transactional commit, and offline replay behavior.

Local validation: 136 Python tests pass. API responses are mocked, and the actual-worker test explicitly clears credentials. No paid or live API request was made; account/model compatibility is not yet verified. Full hosted compiler, package, container, and archive gates remain required. Next: resource-adapter conformance kit. The v0.2 prerelease remains pending the project license choice.

## Runtime milestone: bounded model-provider contract

Implemented on 18 October 2026.

- Added an opt-in bounded JSON proposal provider with per-instance call limits, request/response byte caps, candidate/patch limits, strict response validation, and request-digest binding.
- Added a POSIX subprocess transport with incremental output reads, deadlines, process-group cleanup, no shell interpolation, and sanitized errors. It runs explicitly trusted commands; it is not a sandbox.
- Integrated stable provider error codes into runtime reports. Accepted proposals reuse existing offline evidence; provider failures stop before exploration/commit and mark evidence incomplete.
- Added a runnable offline protocol worker, source-distribution inclusion, contract documentation, and thirteen tests including real processes, timeout/pipe cleanup, unchanged targets on failure, and replay with live access disabled.

Validation: 123 Python tests pass locally. Existing native compiler, package installation, archive, and container gates remain mandatory in hosted CI. No network provider or paid inference is enabled. Next: an opt-in real-provider adapter with token/spend controls. The compiler prerelease remains pending the project license choice.

## Rust milestone day 15: compiler preview gate

Implemented on 17 October 2026.

- Added a repeatable 17-step native acceptance gate with source provenance, per-step logs, durations, fail-fast execution, and explicit separation from publication approval.
- Hosted Linux/macOS compiler jobs now include both default and extended conformance/fuzz campaigns and upload their evidence even on failure.
- Published the final compiler parity table, exact acceptance scope, remaining semantic/platform limits, candidate release contents, and next runtime-development sequence in [compiler preview gate](compiler-preview-gate.md).
- Marked older Rust milestone documents as historical and linked them to the current capability report. Added three runner tests for success, command failure, missing tools, and timeout handling.

Local validation: 110 Python tests and 59 Rust tests pass. All 17 native gate steps pass, including 354 default and 738 extended differential cases with zero differences, 258 CLI cases, standalone LSP integration, and 1,252 default plus 4,324 extended fuzz invocations without failures. The rebuilt Apple Silicon preview archive passes independent extraction/check/build/IR/LSP verification. Container and Python wheel installation checks run in hosted CI; the local Docker daemon is unavailable.

Publication remains held pending an explicit project license choice and a versioned candidate passing the full workflow. No v0.2 tag or release was created, and v0.1.0-alpha.1 remains unchanged. Next implementation work is the bounded model-provider contract and adapter conformance kit.

## Rust milestone day 14: distribution preview

Implemented on 16 October 2026.

- Added native release packaging for Linux x86-64 and macOS Apple Silicon, with separate hosted build/verification jobs and downloadable CI artifacts.
- Archives contain compiler and LSP binaries, a sample with Python reference IR, SHA-256 payload hashes, source/toolchain provenance, and an SPDX 2.3 Cargo dependency inventory. Unknown project licensing is explicit.
- Added bounded extraction checks and four regression tests covering archive corruption, missing files, traversal, links, duplicate members, size limits, permissions, and dependency graph/license metadata.
- Verification executes extracted binaries outside the checkout with empty PATH, compares complete IR, and exercises the language server using the archived sample.

Local validation: 107 Python tests pass. The Apple Silicon release archive passes checksums, standalone check/build, reference IR comparison, and the complete LSP session. Hosted jobs repeat artifact verification on Ubuntu 24.04 x86-64 and macOS 14 ARM64. No new release is published; the existing alpha remains unchanged.

Next: day 15 compiler preview gate, final parity report, and release readiness review, including the unresolved project license declaration.

## Rust milestone day 13: language server foundation

Implemented on 15 October 2026.

- Added a standalone `foresee-lsp` stdio process with initialize/shutdown lifecycle and full-document synchronization.
- Publish versioned diagnostics on open/change and clear them on fixes/close. Stale versions are ignored, and oversized edits discard old semantic content.
- Added top-level document symbols with declaration/name ranges and hover for inferred expression types and snapshot lineage. Source offsets convert to UTF-16 editor positions.
- Bounded protocol frames, headers, URI lengths, and open documents; added seven Rust tests, two Python framing tests, and a hosted standalone editor-session test. Existing Cargo run commands retain their default binary.

Local validation: 103 Python tests and 59 Rust unit/integration tests pass. The standalone integration test passes with empty PATH and no source file on disk, including an error after an emoji, corrected diagnostics, hover, symbols, stale edits, close, and clean shutdown. Compiler/CLI comparisons and fuzz smoke checks remain green. This is a synchronous full-sync foundation, not a packaged editor extension.

Next: day 14 native distribution archives, checksums, and software bill of materials.

## Rust milestone day 12: native compiler CLI

Implemented on 14 October 2026.

- Added native `check` and `build` commands with help, human-readable source locations, JSON diagnostics, and explicit exit codes.
- Build emits complete typed IR with its digest to a required output path, publishing only a fully written file and rejecting existing destinations.
- Preserved development-stage command behavior and day 11 resource budgets. OS paths are kept as native path values, with lossy text only for display.
- Added one Rust option test, ten standalone process tests, and a hosted 258-case CLI comparison runner using a copied binary, empty PATH, and no model credentials.

Local validation: 101 Python tests and 52 Rust unit/integration tests pass. The new check/build runner matches Python acceptance, diagnostic locations, complete IR, and digests on 258 cases. Earlier stage comparisons, the 354-case differential run, and the 1,252-invocation fuzz smoke campaign remain green. Native execution and binary distribution remain separate milestones.

Next: day 13 language server foundation.

## Rust milestone day 11: hostile input hardening

Implemented on 13 October 2026.

- Enforced the source byte budget for library callers and changed the syntax CLI to read at most the budget plus one byte.
- Bounded token count and values, parser collections, expression nesting, diagnostics, and canonical serialization depth. Native expression depth is now 16 rather than 128.
- Added seven Rust boundary tests and three Python smoke-runner tests, including diagnostic floods, oversized library calls, corrupted output, and identity validation.
- Added a seeded subprocess mutation campaign with CPU, wall-clock, and output limits, plus a Linux address-space cap. CI stores its summaries and failure inputs.

Local validation: 101 Python tests and 41 Rust unit tests pass. The default campaign completed 1,252 native invocations; seed 913 with 1,024 mutations completed 4,324. Neither found a crash, timeout, process budget failure, internal compiler error, or invalid successful IR. The 354-case end-to-end conformance run and all eight earlier comparison runners also pass. These bounded campaigns do not prove absence of all resource-exhaustion bugs.

Next: day 12 native check/build commands and human-readable diagnostics.

## Rust milestone day 10: differential compiler harness

Implemented on 12 October 2026.

- Added one end-to-end runner comparing lexing, parsing, full semantic diagnostics, successful expression types, complete IR, canonical bytes, and digests.
- Deduplicated the shared source corpus while retaining fixture labels, and added seeded bounded generation with eight semantic-error families.
- Added failure evidence, source replay, bounded optional reduction, machine-readable summaries, and hosted result artifacts.
- Added two hand-reduced regressions for known ownership and simulation-count rules, plus seven tests that exercise generation and deliberately broken compiler responses. No new compiler mismatch was found.

Local validation: 98 Python tests and 34 Rust unit tests pass. The default seed checks 354 cases (124 accepted, 230 rejected); seed 451 with 256 generated pairs checks 738 cases (316 accepted, 422 rejected). Both complete with zero differences. The reference comparison retains the documented native declaration gate and shared syntax limits.

Next: day 11 hostile-input limits and fuzz hardening.

## Rust milestone day 9: canonical identity

Implemented on 11 October 2026.

- Added Python-compatible ASCII canonical JSON with recursively sorted keys, preserved array order, control escapes, surrogate pairs, and arbitrary-size integers.
- Added SHA-256 program digests through a locked `sha2` dependency, hashing the checked IR body before inserting the digest.
- Added the `identity` development command and a checked library artifact containing complete IR plus a read-only canonical preimage. Earlier stages remain unchanged.
- Added 27 frozen canonical-byte/digest fixtures, five Rust tests, three Python tests, and hosted identity comparisons across 182 earlier cases.

Local validation: 91 Python tests and 34 Rust unit tests pass, together with all eight comparison runners. Identity comparisons verify exact bytes and complete IR for accepted source, with exact diagnostic codes and spans and no artifact for rejected source. Native execution remains pending.

Next: day 10 consolidated differential compiler harness and deterministic generated programs.

## Rust milestone day 8: native typed IR lowering

Implemented on 10 October 2026.

- Added a private checked-program boundary and native lowering of every supported declaration, statement, and expression into the schema 0.0.3 body.
- Preserved inferred types, snapshot lineage, argument and statement ordering, and arbitrary-size integers. Sorted and deduplicated effects; excluded spans, annotations, and internal identities.
- Added the non-executable `ir` command and a structural wire-contract validator. Rejected source cannot emit IR, and inconsistent internal type tables produce contract errors.
- Added 23 IR fixtures, four Rust tests, three Python tests, and hosted native IR comparisons across 159 earlier cases.

Local validation: 88 Python tests and 29 Rust unit tests pass, together with all seven differential runners. IR comparisons match Python after JSON normalization and removal of its digest field. Canonical bytes, program digests, and native execution are not part of this milestone.

Next: day 9 canonical serialization and program digests.

## Rust milestone day 7: selection ownership and branch rules

Implemented on 9 October 2026.

- Added explicit selection identities shared through aliases and consumed by commit.
- Reject subsequent reads through any alias, including during recovery from an invalid commit. Independent selections retain separate identities.
- Count simulation syntax across each exploration body, including nested arguments and invalid calls, and require exactly one simulation.
- Added the non-executable `ownership` command, 28 shared fixtures, four Rust tests, one Python corpus test, and hosted differential checks. Earlier staged checks retain their behavior.

Local validation: 85 Python tests and 25 Rust unit tests pass. Ownership comparisons cover 28 new cases plus 131 earlier cases with matching diagnostic codes, order, source spans, and successful expression reports. Earlier syntax, declaration, type, effect, and lineage comparisons also pass.

Next: day 8 native typed IR lowering. Execution and runtime selection consumption remain in Python.

## Rust milestone day 6: resource and snapshot lineage

Implemented on 8 October 2026.

- Added native origin validation for exploration, simulation, resource method receivers, and branch-local state reads.
- Preserved resource and snapshot identities through aliases, plans, trials, selections, and outcomes.
- Added explicit staged checking and a separate branch resource context for accurate malformed-input recovery.
- Added the non-executable `lineage` command, 30 origin fixtures, four Rust tests, and one Python corpus test.

Local validation: 84 Python tests and 21 Rust unit tests pass. Native lineage comparisons cover 30 new cases plus 101 existing type/effect cases, alongside the earlier syntax and declaration checks. Ownership and simulation-count enforcement remain day 7 work.

Next: day 7 selection ownership and branch rules.

## Rust milestone day 5: effect checking

Implemented on 7 October 2026.

- Added native effect namespace validation, used-permission tracking, missing-effect diagnostics, and forbidden exploration operations.
- Centralized native method signatures, effect target rules, and branch restrictions in a closed signature registry.
- Added the `effects` command while preserving the earlier declaration-only and type-only stages.
- Added 35 effect cases, four Rust tests, one Python corpus test, and hosted effect comparisons against all 66 type regressions.

Local validation: 83 Python tests and 17 Rust unit tests pass, along with syntax, declaration, type, and effect comparisons. Lineage validation and affine ownership remain pending.

Next: day 6 resource and snapshot lineage validation.

## Rust milestone day 4: expression type inference

Implemented on 6 October 2026.

- Added owned Rust expression/statement enums and native inferred kinds with resource IDs, snapshot metadata, and trial metrics.
- Added the `types` development command, covering binding scopes, annotations, method signatures, arguments, proposals, metrics, selections, commit types, and outcome returns.
- Added 66 differential type cases comparing every expression type and source span, with exact error-code/order comparisons for rejected programs.
- Added five Rust tests, one Python corpus test, and hosted comparison steps on Linux and macOS.
- Preserved an explicit non-executable stage boundary: effect, cross-origin, and affine ownership validation remain later milestones.

Local validation: 82 Python tests, 13 Rust unit tests, 66 type fixtures, 28 declaration fixtures, five declaration CLI error paths, and 28 syntax fixtures pass.

Next: day 5 native effect checking.

## Rust milestone day 3: declarations and symbols

Implemented on 4 October 2026.

- Added the native `foresee-semantics` crate with declaration cardinality/type/name checks and distinct resource/model/decision symbol IDs.
- Added an explicitly declaration-only development CLI with bounded source reads and structured diagnostics.
- Added 28 shared declaration cases comparing Python and Rust diagnostic codes, order, locations, and symbol output; added five CLI failure checks.
- Added four Rust unit tests and one Python corpus test, and enabled the native comparison in both hosted Rust jobs.

Local validation: 81 Python tests, eight Rust unit tests, 28 existing syntax fixtures, and 28 new declaration fixtures pass. No native expression checking or executable IR is claimed by this milestone.

Next: day 4 native expression type inference.

## Rust milestone day 2: semantic compiler architecture

Completed on 3 October 2026.

- Defined the proposed native compiler modules, typed AST boundary, symbol and type representations, source spans, snapshot identities, and affine selection identities.
- Mapped every current F3xxx semantic diagnostic to an owning phase and fixture group, distinguishing existing evidence from missing cases.
- Specified traversal and diagnostic recovery compatibility, including alias consumption and unordered declared-effect diagnostics.
- Defined syntax 1 to typed IR 0.0.3 lowering and Python-compatible canonical JSON, including ASCII escapes for Unicode digest parity.
- Kept the native checker and new fixture groups explicitly planned; this milestone ships the architecture, not native semantics.

Validation: audited the mapping against the reference checker and signature registry; checked local document links and diff formatting.

Next: day 3 native Rust declarations and symbol tables.

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
