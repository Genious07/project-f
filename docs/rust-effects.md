# Native Rust effect checking

The subsequent [lineage stage](rust-lineage.md) adds resource and snapshot validation. The `effects` command retains the boundary below.

Milestone day 5 adds `foresee-semantics effects SOURCE` and `check_effects(&str)`. This combines declaration and type analysis with effect declarations, permission coverage, and exploration restrictions. The older `declarations` and `types` commands retain their narrower contracts.

```bash
cargo build --workspace --locked
target/debug/foresee-semantics effects examples/repair.fore
python3 tools/check_effects.py
```

## Enforced rules

The closed native signature registry maps `Snapshot`, `Explore`, and `Commit` to resource declarations, and `Infer` to model declarations. Unknown effect kinds, unknown targets, and wrong target namespaces fail with F3202. Unknown declared targets additionally receive F3002, including a decision name used as a resource.

The checker records operations as it visits expressions and reports missing permissions with F3001 after walking the decision body. Snapshot contributes Snapshot, propose contributes Infer, explore contributes Explore, and commit contributes Commit. Branch operations contribute to the same used-effect set. Duplicate declarations are deduplicated, declarations may appear in any order, and unused valid permissions do not create a new error.

Inside exploration, snapshot, propose, nested exploration, and select produce F3207. Commit produces F3102. As in Python, invalid expressions continue through diagnostic recovery; a branch commit emits F3102 at both the context guard and commit rule. This is static checking: no effect is executed during recovery. An unknown method still stops before checking its arguments, matching the reference checker.

Catalog method signatures and forbidden branch operations now live in `signatures.rs`. Expression checking uses this registry rather than an independently maintained method table. The allowlist remains limited to `source_fields_unchanged`, `valid_unit_arithmetic`, and `unresolved_units`; simulation supports only the declared resource's `apply` method.

## Output and boundary

Successful JSON contains `checked_phase: "effects"`, `ok: true`, `executable: false`, and the expression inspection types. Exit 1 returns diagnostics without an expression report; exit 2 retains the existing command/file/UTF-8/size/internal-contract error behavior.

Success does not authorize execution. Cross-snapshot origin checks (F3301), simulation/branch receiver alignment (F3104), selection consumption (F3400), and exactly-one-simulation (F3401) remain deferred. Continue using Python for complete validation and runtime execution. Native IR generation is also still pending.

Declared effects use a deterministic sorted set in Rust. Python iterates invalid declared effects from a set, so their message order can differ. These diagnostics share the same decision span and code; the comparison preserves code/span multiplicity without requiring identical message ordering. Missing permissions and unknown target names are reported in sorted order in both implementations.

## Evidence

The 35 new effect fixtures cover each omitted permission, duplicate declarations, wrong namespaces, unknown targets, unknown kinds, empty/reordered effect sets, unused declarations, all five forbidden exploration operations, nested argument effects, restored branch context, unknown-method recovery, and Unicode/CRLF locations. Explicit cases retain the staged boundary for lineage and ownership.

The differential runner compares those cases and all 66 existing type cases against Python. Rejected programs must match diagnostic codes, counts, order, and spans; accepted programs must match every inspected expression type. The runner filters only the four pending lineage/ownership diagnostics listed above, after applying the shared declaration gate.

Four Rust tests independently check omitted permission identities, wrong namespaces, branch-commit diagnostic multiplicity, and type invariance under effect deduplication/reordering. A Python test validates fixture expectations without Rust. Both hosted Rust jobs run the full comparison.

This milestone is available from the repository source and does not create a new release. Next is day 6: enforcing resource and snapshot lineage in the native checker.
