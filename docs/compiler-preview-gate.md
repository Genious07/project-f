# Compiler preview gate: 17 October 2026

The Rust implementation independently checks the supported Foresee subset and emits complete schema 0.0.3 IR with program identity. Python remains the effect runtime. This report is the day 15 acceptance record and the current reference for compiler capabilities; earlier milestone documents describe their narrower development stages.

Publication is held pending an explicit project license choice. The existing `v0.1.0-alpha.1` release remains unchanged. No v0.2 tag, crate version bump, or release-ready claim is implied by passing the compiler tests.

## Final parity table

| Area | Native compiler result | Verification and boundaries |
| --- | --- | --- |
| Lexer and parser | Implemented independently | Tokens, AST, character spans; ASCII identifiers/numeric literals and UTF-8 strings |
| Declarations and types | Implemented | Supported declaration cardinality, signatures, annotations, binding and return types |
| Effects | Implemented | Permission identities, namespaces, resource targets, branch restrictions |
| Snapshot lineage | Implemented | Snapshot/resource provenance, aliases, simulation and receiver alignment |
| Selection ownership | Implemented | Single consumption across aliases, exactly one simulation per branch |
| Typed IR | Complete schema 0.0.3 | Structural equality with Python for accepted cases; rejected programs emit no IR |
| Canonical bytes and identity | Implemented | Exact canonical preimage and SHA-256 comparison; frozen identity fixtures |
| User compiler CLI | Native check/build | 258 comparisons, JSON/human diagnostics, exit codes, safe output creation |
| Language server | Native foundation | Diagnostics, full-document edits, UTF-16 positions, symbols, type/lineage hover |
| Binary distribution | Preview archives | Linux x86-64 and macOS ARM64; extracted binaries checked outside checkout |
| Effect execution and recovery | Python runtime | SQLite transactions, journals, receipts, replay; no native runtime migration |

## Evidence and repeatable gates

```sh
python -m unittest discover -s tests -v
python tools/check_preview.py
python tools/package_native.py
python tools/verify_native.py release-dist/native/*.tar.gz
```

The native gate runs formatting, Rust tests, compilation, every stage-specific comparison, default and extended differential campaigns, CLI/editor integration, and default and extended fuzz campaigns. It fails at the first unsuccessful command. Missing tools and timeouts are failures. `target/preview-gate/summary.json` records source commit, dirty-worktree status, command, duration, status, and log path for every attempted step. A successful report explicitly does not authorize publication. Consult only the report and logs belonging to the intended run, since older unattempted logs may remain in a reused local checkout.

| Gate | Acceptance evidence |
| --- | --- |
| Python | 110 unit/integration tests, including three preview-runner failure-path tests |
| Rust | 59 unit/integration tests plus formatting and a locked workspace build |
| Default differential | 354 cases: 124 accepted, 230 rejected; zero differences required |
| Extended differential | Seed 451, 738 cases: 316 accepted, 422 rejected; zero differences required |
| Native CLI | 258 source cases through check and build |
| Fuzz smoke | 313 cases, 1,252 native invocations; zero failures required |
| Extended fuzz | Seed 913, 1,081 cases, 4,324 native invocations; zero failures required |
| Editor | Standalone stdio session with open, error, fix, hover, symbols, stale edit, close, shutdown |
| Distribution | Release archives, checksums, complete sample IR comparison, archived-sample LSP session |

The Verify workflow runs Python 3.11 through 3.14 on Linux and 3.14 on macOS, builds/installs Python packages outside the checkout, checks the Python container, runs the complete native gate on Linux and macOS, and verifies both native archive targets. It uploads native gate logs and default/extended campaign evidence even after failures. Download archives and evidence from the workflow run for the exact commit being assessed. The local Docker daemon is unavailable on the development machine, so container acceptance is established by the hosted container job.

## Remaining differences and limits

- Unicode identifiers and non-ASCII numeric literals are outside the native shared subset. Python accepts some additional Unicode categories. Unicode strings remain supported.
- Native resource budgets intentionally reject oversized inputs that Python may accept. Expression depth is capped at 16; all budgets are documented in [compiler limits](compiler-limits.md).
- Native declaration failures stop before body checking. The differential reference adapter applies this same boundary. Results do not claim identical cascading diagnostics from an unadapted Python invocation.
- Diagnostic prose is not compared. Invalid effect declarations may have different message ordering because Python uses a set; code/span multiplicity is retained. Full semantic checks have no deferred rule filter within the tested shared subset.
- Earlier development commands such as `types` and `effects` deliberately check only their named stage. Use `foresee-semantics check` or `build` for complete native checking.
- LSP is synchronous, full-document synchronization only. No incremental edits, background cancellation, completion, rename, or packaged editor extension is included.
- Archives are unsigned previews for the documented OS/architecture combinations. They are not static binaries, authenticated releases, or evidence of compatibility with older operating systems. The SBOM covers Cargo dependencies, not system libraries or exact linked code.
- Corpus agreement and bounded fuzzing are evidence, not proof of correctness for all programs. No native effect execution, arbitrary model provider, new resource adapter, or authenticated evidence format is included in this milestone.

## Candidate release scope and publication steps

The proposed v0.2 compiler preview would ship the native compiler and LSP, matching sample IR, dependency inventory, checksums, CLI documentation, and this parity report. Python runtime behavior would remain unchanged.

Before publishing:

1. Resolve the project license choice and apply it consistently to repository/package metadata and archives, including required notices.
2. Select the preview version, update native crate metadata and lockfile, and rerun the full Verify workflow on that exact commit.
3. Require every job to pass, inspect both target archives and source provenance, and retain the final evidence.
4. Create the versioned prerelease from that tested commit and attach those exact archives/checksums. Do not rebuild from a different working tree or overwrite the existing alpha.

## Next development sequence

1. Completed on 18 October: [bounded model-provider contract](model-provider-contract.md), request budget, deadline-aware process transport, strict schema validation, recorded proposals, and explicit provider failures.
2. Implement one opt-in real provider behind that contract while keeping offline tests credential-free.
3. Build the resource-adapter conformance kit around isolation, commit atomicity, stale snapshots, crash recovery, and replay.
4. Specify authenticated evidence with a threat model, key ownership, verification, and rotation before implementing signatures.
5. Add a second transactional adapter only after it passes the conformance kit. Reassess native effect execution after these runtime contracts are stable.
