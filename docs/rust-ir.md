# Native typed IR lowering

The Rust compiler now lowers successfully checked source into the body of typed IR schema 0.0.3. It runs declaration, type, effect, lineage, and ownership checks before lowering. Rejected programs return diagnostics without IR.

```sh
cargo run -p foresee-semantics -- ir examples/repair.fore
python tools/check_ir.py
```

The development command returns a JSON envelope with `ok`, `checked_phase: "ir"`, `executable: false`, and `ir`. Its IR body contains `schema_version`, resources, models, and decisions. It deliberately omits `program_digest`: canonical serialization and hashing are day 9 work. This is not yet a complete build artifact for runtime use. The alpha runtime and complete build command remain Python implementations.

## Construction and traversal

`ir::lower_source` is the public library entry point. A private `CheckedProgram` owns the decoded AST and the complete type table only after the ownership stage succeeds. The returned `IrBody` has private contents and supports serialization, with no public deserialization or unchecked construction path.

Lowering walks the owned expression and statement enums. It matches each expression to its deterministic preorder type record and checks its operation, source span, and node ID. Missing, leftover, mismatched, or recovery types are internal contract failures. They cannot produce a partial successful artifact. Explicit traversal order avoids depending on JSON object-key ordering.

All supported statements and expressions retain their operands. Resource and model names remain in declarations. Inferred types retain kind, resource, ordered metric names, and snapshot lineage, including null and empty values. Integer values are not narrowed to machine integers.

Decision effects are deduplicated and sorted by kind and target. Source annotations, spans, node IDs, and selection capability IDs are absent. Comments and formatting do not change the body; changes to actual operands still do.

## Validation evidence

`tools/validate_ir.py` is a dependency-free structural validator for the digest-free 0.0.3 body. It checks exact object fields, operation variants, operand shapes, declaration cardinality, expression type fields, and sorted unique effects. It is a test utility, not a runtime authorization boundary or an arbitrary hostile-input validator.

`tools/check_ir.py` runs the Rust binary and Python reference on 23 new cases and 159 earlier cases. For accepted programs it validates the native body and compares it to Python after JSON normalization and removal of `program_digest`. For rejected programs it checks exit status and exact diagnostic codes, order, and spans, and requires IR to be absent. Declaration failures retain the existing early-stop behavior.

Coverage includes all source expression and statement forms, ordered metrics, multiple explorations and snapshots, symbol renaming, annotations, redundant effects, Unicode and escaped strings, huge integers, leading zeros, and errors from every semantic stage. Rust tests protect the checked boundary and reject inconsistent type tables. Python mutation tests verify that malformed wire documents fail structural validation.

Earlier staged commands remain unchanged. This milestone establishes structural IR parity for the tested shared subset. It does not establish canonical byte or digest parity, execute native effects, or change the published alpha release.
