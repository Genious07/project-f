# Native Rust semantic compiler architecture

Status: design accepted for milestone day 2, 3 October 2026. This document specifies the implementation for days 3 through 12. The native semantic checker and the modules below are not implemented yet. The alpha still executes through Python.

## Goal and boundary

Compile the supported language from source into typed IR 0.0.3 without Python. Preserve source acceptance, semantic diagnostics, expression types, snapshot lineage, selection ownership, and program digests within the shared subset. Python's `foresee/compiler.py`, `model.py`, `signatures.py`, and `parser.py` are the executable reference at commit `8f2afc5`.

Compilation must be pure with respect to external systems: no database, provider, journal, environment-derived policy, network call, or clock is involved. Static checking does not establish receipt authenticity, runtime token provenance, or target transaction correctness. Those remain runtime responsibilities.

## Pipeline and module ownership

```text
UTF-8 source
    -> foresee-syntax lexer/parser (syntax version 1)
    -> ast: validated Rust syntax nodes and deterministic node IDs
    -> declarations: top-level symbols and decision shape
    -> checker: ordered statement/expression traversal
         -> signatures and effects
         -> types and lineage
         -> ownership and branch context
    -> CheckedProgram (only when diagnostics are empty)
    -> ir: typed IR 0.0.3
    -> canonical: canonical bytes and SHA-256 digest
```

Create a `foresee-semantics` library crate that depends on `foresee-syntax`; the syntax crate must not depend on semantics. Initially keep the existing syntax CLI stable. A compiler CLI will call this library in day 12, and a language server will reuse it in day 13.

| Proposed module | Owns | Output and restriction |
| --- | --- | --- |
| `ast` | Conversion from existing `serde_json::Value` syntax to owned enums; node IDs and spans | Validate every required field, node kind, and integer representation; malformed AST input is an API error, never a panic |
| `symbols` | Resource, model, decision, and local identities | Names remain available for diagnostics and wire serialization |
| `declarations` | Program cardinality, declaration types, effect declarations, return shape | May accumulate errors, but cannot construct checked output |
| `signatures` | Frozen Catalog/Planner types, effects, methods, argument rules | No arbitrary method dispatch or adapter registration |
| `types` | Inferred kinds, nominal resource identity, lineage, ordered trial metrics | No Python object identity or JSON dictionaries in semantic operations |
| `checker` | Reference-order traversal and expression/statement inference | Calls effect, lineage, and ownership helpers at the original evaluation point |
| `ownership` | Selection capability allocation, aliasing, and consumption | Selection IDs are compile-local; never serialize as runtime authority |
| `diagnostics` | Codes, spans, messages, optional notes, recovery behavior | Retain reference codes; do not emit executable IR on errors |
| `ir` | Successful lowering and schema version | Excludes annotations, spans, node IDs, and selection IDs |
| `canonical` | Python-compatible JSON serialization and digest | Deterministic bytes; digest excludes its own field |
| `lib` | Compilation entry points | Returns checked artifacts or diagnostics, never a partially successful build |

Effects, types, lineage, and ownership are logical phases implemented as cooperating helpers in one ordered traversal. Running independent whole-program passes would change error order and selection consumption behavior. Refactoring the internal organization must preserve that observable traversal.

## Native data model

The following Rust sketches define the model to implement, not a new public API shipped with this commit:

```rust
struct NodeId(u32);
struct ResourceId(u32);
struct ModelId(u32);
struct SymbolId(u32);
struct SnapshotId(u32);
struct SelectionId(u32);

enum TypeKind {
    Int, String, Bool, Snapshot, Plan, Plans,
    Simulated, Trials, Selected, Outcome, Error,
}
struct InferredType {
    kind: TypeKind,
    resource: Option<ResourceId>,
    lineage: Option<SnapshotId>,
    metric_names: Vec<String>,
}
struct Binding {
    ty: InferredType,
    selection: Option<SelectionId>,
}
struct BranchContext {
    resource: ResourceId,
    base: InferredType,
}
```

Use owned `Program`, `Declaration`, `Statement`, and `Expr` enums/structs rather than dynamic maps after AST conversion. Every expression gets a `NodeId` in deterministic preorder. Store `NodeId -> InferredType` in a vector-backed table and retain source spans on syntax nodes. IDs are checked integer indices, not pointers. Allocation overflow is a compiler resource error, not wraparound.

`Expr` variants cover `String`, `Int`, `Var`, `Snapshot`, `Propose`, `Explore`, `Simulate`, `Call`, `Select`, and `Commit`. `Statement` variants cover `Let`, `Check`, `Measure`, and `Return`. Preserve declaration order, statement order, argument order, trial metric order, and expression nesting. AST conversion must not evaluate expressions or allocate snapshot/selection IDs.

The Rust parser currently exposes syntax as JSON. Convert its local output through the typed AST boundary first; a future typed syntax API can replace this conversion without changing checker rules or wire format. Do not advertise arbitrary external JSON AST ingestion as supported or safe.

Keep arbitrary-size nonnegative integer syntax values as validated decimal digits or an arbitrary-precision number representation. Do not narrow them to `i64` merely because catalog patches use signed-64-bit integers. Proposal counts are independently constrained to literal values 1 through 4. Source integer syntax has no unary minus.

Resources and models use separate identity types. Invalid source references need a recovery representation carrying the original unresolved name, so an undeclared identifier can generate the reference diagnostic without indexing a nonexistent symbol. Recovery values cannot enter `CheckedProgram`.

## Symbol environments and branch state

Top-level resources/models/decisions share the uniqueness rule. Validate their types and cardinalities before walking decision bodies. Resolve effects against the appropriate resource or model namespace.

A decision starts with an empty local environment. A `let` diagnoses reserved or duplicate names, checks its initializer against the previous environment, and then replaces/inserts the binding, matching Python's recovery behavior. An annotation checks inferred kind and nominal resource; it cannot cast a value or erase lineage.

Exploration clones the outer local environment and adds its candidate binding. The candidate name cannot shadow an existing local, resource/model name, or reserved name beginning with `__`. Branch-local definitions do not escape. Resource and model names cannot be shadowed by ordinary lets; do not introduce an additional decision-name reservation absent from the reference.

Carry branch context explicitly and restore the previous context after checking an exploration body, including when invalid nested exploration is encountered during error recovery. Effects used by the branch propagate into the decision's used-effect set. The snapshot counter and consumed-selection set belong to the checker, not to a cloned branch environment.

## Snapshot lineage and selection ownership

Allocate `SnapshotId` only when the checker visits a snapshot expression, starting at one. Serialize it as `snapshot:N`. An alias copies its origin unchanged; identical database state does not make separately observed snapshots interchangeable.

Plans inherit snapshot origin. Exploration compares plan-set and base origin, then assigns that origin to the candidate plan, simulation, and trials. Resource method arguments must match the receiver, each other, and the current branch base. Selection and commit outcomes inherit the trials' origin.

Each evaluated static `select` expression allocates one new `SelectionId`. Aliasing copies this ID. Looking up a consumed selected binding reports `F3400`. A commit first checks its selected expression, then consumes the ID when its kind is selected, then checks the target/type rule, and records the Commit effect. Preserve consumption even when the source is already invalid; the overall compilation fails and emits no IR.

Equal selected types are not equal capabilities. Two independent `select` expressions from the same trials must receive different IDs. Snapshot IDs and selection IDs are compile-local semantic identities, not live receipt IDs or runtime tokens.

## Diagnostics and error ownership

Syntax owns F1xxx/F2xxx errors, including the parser's `DecisionResult` return-annotation restriction and empty parameter-list grammar. Semantics owns the F3xxx rules in the table below. A syntax failure stops semantic checking. Semantic errors accumulate in the reference traversal order; do not sort all diagnostics by source offset afterward.

Retain zero-based character offsets and one-based line/column locations from the syntax crate. Top-level cardinality and duplicate-name diagnostics use the existing synthetic span `(0, 0, 1, 1)`. Keep UTF-8 byte offsets and future LSP UTF-16 positions as separate conversions.

Expression checking records a type even while accumulating errors. `Error` is an internal recovery kind; successful IR can never contain it. An unknown method returns Error without visiting its arguments, matching the current checker. Other argument checking visits all arguments before emitting an arity/type error. Do not add blanket cascade suppression that changes the reference diagnostic sequence.

Invalid declared effects are currently iterated from a Python set. Compare those diagnostics as a multiset of `(code, span)` until reference ordering is explicitly stabilized in a separately reviewed change. Missing effects and unknown targets already use sorted order. Preserve duplicate diagnostics, including the two F3102 emissions possible for a branch commit. Wording may improve independently; codes, counts, and spans remain the initial comparison target.

All diagnostics are owned data. The library returns them; only the CLI renders text/JSON and chooses exit codes. No module logs diagnostics as a side effect. Malformed AST API inputs and internal invariant violations must be distinguishable from ordinary source errors.

## Rule-to-phase and fixture mapping

Fixture groups below are names for the semantic corpus to add during the relevant implementation day. The evidence column names existing Python tests or identifies coverage still needed. The existing 28 syntax fixtures and bridge do not establish native semantic parity.

| Reference rule / diagnostic | Owning phase | Semantic fixture group | Existing evidence or required addition |
| --- | --- | --- | --- |
| Grammar, empty parameter list, return annotation; F1xxx/F2xxx | Syntax | `syntax` | `fixtures/syntax/cases.json`; subset test `bad return annotation` |
| Exactly one resource/model/decision; F3200 | Declarations | `declarations/cardinality` | `test_subset`: empty and ambiguous entry; add zero/multiple resource/model cases |
| Catalog/Planner declaration types; F3201 | Declarations | `declarations/types` | `test_subset`: unknown resource/model |
| Unique top-level names; F3000 | Declarations | `declarations/names` | Add duplicate names across all declaration kinds |
| Effect kind and namespace; F3202 | Declarations | `effects/declarations` | `test_subset`: unknown effect and wrong effect target |
| Unknown declared effect target; F3002 | Declarations | `effects/targets` | Add missing resource/model target cases |
| Exactly one final return and Outcome result outside branch; F3203 | Declarations/checker | `statements/return` | `test_subset`: bad return, unreachable effects, branch return; `test_types`: non-outcome return |
| Reserved local/candidate names and candidate shadowing; F3204 | Symbols/checker | `bindings/reserved` | `test_subset`: reserved binding; add candidate/namespace shadowing cases |
| Duplicate local; F3003 | Symbols/checker | `bindings/duplicate` | Add duplicate and initializer-reference cases |
| Missing binding; F3004 | Checker | `bindings/lookup` | Add missing local and nonescaping branch-local cases |
| Annotation kind/resource; F3300 | Types | `types/annotations` | `test_invalid_annotations`, `test_valid_annotations_preserve_digest` |
| Check/measure allowed only in exploration; F3100 | Checker | `branches/context` | Add outside-branch check/measure cases |
| Boolean check, Int measure and annotation; F3205 | Types | `types/metrics` | `test_subset`: bad check and metric |
| Argument count/kind; F3206 | Signatures/types | `calls/arguments` | `test_subset`: wrong arity/argument and bad proposal; add simulate arity |
| Branch forbids snapshot/propose/explore/select/commit; F3207/F3102 | Checker/effects | `branches/effects` | `test_subset`: branch snapshot/proposal/nested explore; `test_rejects_live_commit_inside_explore`; add branch select |
| Declared resource for snapshot; F3005 | Symbols/checker | `snapshot/target` | Add unknown snapshot resource |
| Declared model for propose; F3006 | Symbols/checker | `propose/target` | Add unknown proposal model |
| Patch proposal and literal count 1..4; F3208 | Signatures/types | `propose/shape` | `test_subset`: bad proposal type/limit; add bound and nonliteral cases |
| Exactly one recursively counted simulation; F3401 | Checker | `branches/simulation-count` | `test_exactly_one_simulation_is_required` |
| Explore Plans and Snapshot inputs; F3101 | Types | `explore/inputs` | Add wrong plan-set/base kinds |
| Matching nominal resource and snapshot origin; F3301 | Lineage | `lineage/origins` | `test_proposals_cannot_use_a_different_snapshot`, comparison/metric/receiver tests in `test_types` |
| Duplicate metrics; F3209 | Checker | `trials/metrics` | `test_duplicate_metrics_and_non_outcome_returns` |
| Simulation inside exploration; F3103 | Checker | `simulate/context` | Add outside-branch simulation |
| Simulation receiver equals branch resource; F3104 | Lineage | `simulate/receiver` | Add different receiver case, retaining cardinality errors when applicable |
| Declared resource apply and allowlisted method calls; F3210 | Signatures | `calls/dispatch` | `test_subset`: bad simulate, unknown method, wrong target |
| Select Trials input; F3105 | Types | `select/input` | Add non-Trials selection |
| Selected metric exists in trials; F3106 | Types | `select/metric` | Add absent metric and ordered multi-metric cases |
| Commit selected kind and same resource; F3107 | Types/lineage | `commit/target` | Add wrong kind/target cases |
| Alias consumption; F3400 | Ownership | `ownership/selection` | `test_compiler_rejects_double_commit_and_alias_reuse`, `test_alias_can_be_consumed_once`; add two independent selections |
| Used effects covered by declaration; F3001 | Effects finalization | `effects/coverage` | `test_rejects_undeclared_effect`; add each effect omission |
| Unsupported expression; F3999 | Checker/API boundary | `recovery/unknown-node` | Add internal/reference-AST case; Rust conversion rejects unknown variants before checking |
| Every expression typed and origin preserved | Types/IR | `ir/types` | `test_every_expression_has_a_type`, `test_snapshot_alias_preserves_identity` |
| Canonical serialization, metadata exclusion, effect deduplication | IR/canonical | `ir/identity` | `test_compiles_example_to_stable_ir`, annotation/digest tests in `test_types`; add Unicode/control-character golden bytes |

F3999 is reachable through Python's constructed model API, not supported source syntax. Compare this boundary separately from source parity. Runtime-only ownership, concurrency, crash, and replay tests remain Python gates; they cannot substitute for compiler conformance fixtures.

## Syntax 1 to typed IR 0.0.3

Lower only a private `CheckedProgram` created after all semantic diagnostics are empty. It contains the typed AST, source-name tables, and complete expression type table. Public callers cannot manufacture this success wrapper through deserialization or public fields.

| Syntax/internal input | IR output |
| --- | --- |
| Resource/model declaration with span | `name`, `type_name`; omit span |
| Decision effects in source order | Deduplicated `(kind, target)` pairs sorted lexicographically |
| Statement `kind`, `data`, span | `statement` plus flattened data; omit span and checked let annotation |
| Expression `kind`, `data`, span | `op`, `inferred_type`, and flattened operands; recursively lower child nodes |
| Type and resource ID | `kind`, declaration-name `resource` or null, ordered `metric_names`, and lineage string or null |
| Empty operand or statement sequence | Empty JSON array, never null |
| Node/symbol/selection IDs | Omit; resolve names where required by schema |
| Program | `schema_version: "0.0.3"`, ordered resources/models/decisions, then computed `program_digest` |

`Outcome` still serializes its inferred resource and lineage even though `DecisionResult` annotations take no resource parameter. Scalar types serialize null resource/lineage and empty metrics. Do not drop null or empty fields to reduce output size.

## Canonical bytes and digest

Match `json.dumps(ir, sort_keys=True, separators=(",", ":"))` before inserting `program_digest`. Python defaults to `ensure_ascii=True`: non-ASCII text uses lowercase hexadecimal Unicode escapes, and supplementary characters use UTF-16 surrogate-pair escapes. Escape control characters, quotes, and backslashes exactly as Python does. Default serde_json UTF-8 output alone is insufficient for byte parity.

Sort object keys recursively using Python-compatible Unicode scalar ordering, preserve array order, emit arbitrary-size integers without float conversion, and use compact separators with no extra whitespace. Hash the canonical UTF-8 bytes with SHA-256 and encode lowercase hexadecimal. Human-readable pretty output is separate from identity bytes.

Golden fixtures must include quotes, slashes, backslashes, all supported escaped control characters, non-ASCII BMP characters, supplementary characters, very large integers, zero-prefixed source integers normalized numerically, reordered effects, and redundant checked annotations. A changed prompt must change the digest; formatting and spans must not.

## Incremental implementation and acceptance

Days 3 to 7 implement declarations, inference, effects, lineage, and ownership inside the new library. Each day ports the corresponding fixture groups and records known gaps. Day 8 adds successful lowering, day 9 digest bytes, day 10 the full differential harness, day 11 bounded hostile-input checks, and day 12 user-facing native commands.

The comparison harness must distinguish native checking from the existing Rust-syntax-to-Python bridge. For accepted sources compare complete typed IR and digest. For rejected sources compare diagnostic codes and spans, preserving counts and documented ordering exceptions. Record minimized cases before changing either implementation. Multi-error reference behavior must not be silently replaced by a cleaner Rust interpretation.

The architecture milestone is complete when every semantic diagnostic branch has an owner and fixture group, every supported expression has a native representation and inference path, and the IR conversion/identity rules are specified. It does not claim that the native checker or missing fixtures already exist.
