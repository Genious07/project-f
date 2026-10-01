# Foresee: next 15 development days

## Objective

The next milestone turns the Rust syntax frontend into a native semantic compiler for the supported Foresee subset. At the end of day 15, a user should be able to check a Foresee program with a standalone Rust binary and receive typed IR or precise diagnostics without invoking Python. Python remains the execution reference until native runtime parity is demonstrated.

These are development days, not unattended calendar runs. Each day ends with a reviewable commit after its acceptance checks pass. A failed gate is fixed or recorded before work advances. New syntax is deferred during this milestone so the semantic core can stabilize.

## Day 1: alpha feedback baseline

- Create issue templates for compiler defects, runtime defects, adapter requests, and language proposals.
- Record the alpha compatibility matrix and the exact supported language surface.
- Convert any release acceptance failures into reproducible fixtures.

Acceptance: a report includes version, platform, minimal source, expected result, actual result, and whether a live effect occurred.

## Day 2: Rust semantic architecture

- Define compiler phases, semantic data structures, error ownership, and module boundaries.
- Represent symbols, declared effects, resource identities, source spans, and inferred types without Python objects.
- Document how syntax version 1 lowers toward typed IR 0.0.3.

Acceptance: the architecture document maps every supported Python semantic rule to one Rust phase and one conformance fixture group.

## Day 3: declarations and symbol tables

- Check resource, model, and decision declarations natively.
- Detect duplicate names, missing entry points, unsupported types, and ambiguous programs.
- Preserve source spans in diagnostics while excluding them from semantic identity.

Acceptance: Rust and Python agree on all declaration fixtures and diagnostic locations.

## Day 4: expression type inference

- Infer scalar, snapshot, plan-set, trials, selection, and outcome types.
- Check method receivers, argument counts, argument types, annotations, and return types.
- Emit stable diagnostic codes for each failure class.

Acceptance: every expression in every accepted fixture has an inferred type, and invalid expressions fail before IR emission.

## Day 5: effect checking

- Validate declared read, propose, simulate, and commit effects.
- Reject undeclared capabilities and effects in forbidden branch contexts.
- Keep method dispatch tied to the compiler signature registry.

Acceptance: the Rust checker matches the reference effect decisions for the full negative fixture set.

## Day 6: resource and snapshot lineage

- Attach resource identity and snapshot lineage to resource-bearing values.
- Reject cross-resource proposals, simulations, metrics, and selections.
- Make lineage visible in semantic debug output.

Acceptance: mixed-lineage programs cannot produce typed IR, while valid aliases retain their origin.

## Day 7: ownership and branch rules

- Track a selected value through aliases and consume it on commit.
- Reject double use and forged selection paths.
- Enforce exactly one simulation per branch and immutable branch inputs.

Acceptance: ownership and branch fixtures match Python behavior, including the location of the first invalid use.

## Day 8: native typed IR lowering

- Emit every supported declaration, statement, expression type, effect, and lineage record.
- Keep source-only annotations and spans outside executable identity.
- Validate generated documents against typed IR schema 0.0.3.

Acceptance: accepted shared programs produce structurally equivalent Python and Rust typed IR after canonical normalization.

## Day 9: canonical identity

- Implement canonical serialization and program digest generation in Rust.
- Test formatting, comment, line-ending, map-order, and effect-order stability.
- Document which semantic edits must change identity.

Acceptance: Rust and Python generate identical digests for every shared valid program.

## Day 10: differential compiler harness

- Run both compilers over the shared corpus and compare acceptance, diagnostics, types, IR, and digests.
- Store minimized regressions as permanent fixtures.
- Add deterministic randomized programs within the supported grammar.

Acceptance: the harness reports zero unexplained differences and runs in hosted CI without external services.

## Day 11: hostile input hardening

- Bound file size, nesting, collection growth, diagnostic count, and serialization depth.
- Fuzz lexer, parser, semantic checker, and IR serializer.
- Ensure malformed input cannot panic the compiler process.

Acceptance: the bounded fuzz campaign completes without a crash, unbounded allocation, or invalid IR output.

## Day 12: compiler command-line experience

- Add native `check` and `build` commands to the Rust binary.
- Support human-readable and JSON diagnostics.
- Define stable exit codes suitable for editors and CI.

Acceptance: a clean machine can check and build the sample program without Python or a model credential.

## Day 13: language server foundation

- Create a minimal Language Server Protocol process around the Rust checker.
- Publish diagnostics on open and change.
- Add document symbols and hover information for inferred types.

Acceptance: an editor integration test opens a document, receives diagnostics, fixes the source, and observes the diagnostics clear.

## Day 14: distribution preview

- Produce native compiler archives for supported macOS and Linux targets.
- Generate checksums and a software bill of materials.
- Verify archives outside the source checkout.

Acceptance: every archive checks the example program and emits matching typed IR on its target platform.

## Day 15: v0.2 compiler preview gate

- Run the full Python, Rust, conformance, fuzz-smoke, packaging, and editor integration suites.
- Publish the final parity table and remaining semantic differences.
- Prepare a versioned compiler preview only if all correctness gates pass.

Acceptance: native syntax, semantic checking, typed IR, and program identity agree with the reference subset. Any missing parity remains an explicit blocker rather than a release-ready claim.

## Work immediately after this milestone

The following milestone will add a bounded real-model provider, a resource adapter conformance kit, authenticated evidence, and the first additional transactional adapter. Native effect execution will begin only after the compiler parity gate, preserving the Python runtime as a tested behavioral oracle during the transition.

## Daily GitHub discipline

- Keep one coherent milestone per commit and include its acceptance evidence in the progress log.
- Use no co-author trailer and no em dash in commit subjects or release text.
- Push only after relevant checks pass and confirm the remote commit.
- Keep credentials, local databases, generated environments, and private inputs outside the repository.
