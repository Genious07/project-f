# Development progress

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
