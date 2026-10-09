# Native resource and snapshot lineage validation

Milestone day 6 adds `foresee-semantics lineage SOURCE` and the `check_lineage(&str)` library entry point. It includes declaration, type, and effect checks, and then enforces nominal resource and static snapshot origins. Earlier stage commands retain their previous behavior.

```bash
cargo build --workspace --locked
target/debug/foresee-semantics lineage examples/repair.fore
python3 tools/check_lineage.py
```

## Origin rules

Each snapshot expression gets a new static identity in traversal order. These identities are not live database revisions or data hashes. Even if two observations would return identical data, they remain different origins. Aliases preserve the original resource and snapshot identity.

Proposals inherit the origin of their snapshot argument. Exploration requires the proposal set and base snapshot to share an origin. Candidate plans, simulations, trials, selections, and commit outcomes preserve that origin in expression inspection output.

The lineage stage enforces:

- F3301 when exploration inputs belong to different resources or snapshots.
- F3104 when a simulation receiver does not match the exploration resource.
- F3301 when a simulation's plan argument differs from the branch base origin.
- F3301 when catalog method arguments differ from the receiver resource, from each other, or from the active branch base.

Method origin checks apply outside exploration too: two state arguments must share an origin. Inside exploration, two arguments that agree with each other still fail if they refer to another snapshot. Scalar results have no origin and cannot be passed as state arguments.

The checker retains the effective branch resource separately from the inferred base type. This preserves Python's diagnostic recovery when malformed exploration inputs create an error resource. Nested exploration remains forbidden, but recovery restores both the outer base and the outer resource before checking subsequent statements.

The public declaration gate still permits only one Catalog resource. A second resource fails that gate before body checking. An internal Rust unit test independently checks nominal resource comparison; this does not introduce multi-resource execution support.

## Inspection and stage boundary

Successful output contains `checked_phase: "lineage"`, `executable: false`, and an expression inspection array with resource names and `snapshot:N` identities. Rejected programs return diagnostics without an expression report. Existing exit codes and source size limits apply. No database or model access occurs.

Only selection consumption (F3400) and exactly-one-simulation (F3401) remain deferred in the supported semantic traversal. This milestone does not emit executable IR, authenticate evidence, or provide the runtime capabilities needed for a commit. Use Python for complete checking and execution until native parity and lowering are complete.

## Validation

Thirty new shared cases cover complete origin chains on first and second snapshots, aliases of snapshots/plans/trials/selections, mismatched exploration inputs, unrelated checks and metrics, comparisons inside and outside branches, invalid simulation receivers, malformed-input recovery, nested branch restoration, and Unicode/CRLF diagnostic positions.

The lineage comparison also reruns all 35 effect and 66 type fixtures under the stronger stage. It filters only the two pending ownership diagnostics after the declaration gate. Rejected cases compare diagnostic codes, counts, order, and spans; accepted cases compare all inspected types, including resource names and lineage. A Python test validates fixture expectations even when Rust is unavailable.

Four Rust unit tests cover alias propagation through outcomes, independent snapshot rejection, unrelated metric rejection despite valid scalar type, and distinct nominal resources with equal snapshot IDs. Both hosted Rust jobs run the lineage comparison.

This is a source development milestone, not a new published release. Day 7 implements affine selection consumption and branch simulation-count rules.

The subsequent [ownership stage](rust-ownership.md) adds single-use selection and simulation-count checks while preserving this command’s narrower scope.
