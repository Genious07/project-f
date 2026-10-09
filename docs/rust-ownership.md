# Native selection ownership and branch validation

The Rust `ownership` stage adds the remaining static ownership rules to declaration, type, effect, and lineage validation for the current shared language subset.

```sh
cargo run -p foresee-semantics -- ownership examples/repair.fore
python tools/check_ownership.py
```

A successful result contains `checked_phase: "ownership"`, expression types, and `executable: false`. Errors contain diagnostics without an expression report. Exit codes remain 0 for success, 1 for rejected source, and 2 for invocation or input failures.

## Single-use selections

Every `select` expression creates a fresh internal selection identity. Binding aliases copy that identity. A commit consumes it, and any later read through the original binding or an alias produces F3400 at the read location. Copying a consumed selection cannot restore its validity.

```text
let chosen = select trials minimize unresolved;
let alias = chosen;
let result = commit alias to catalog;
return commit chosen to catalog; // F3400 at chosen
```

Two separate selections over the same trials have distinct identities. Unused selections are allowed, as are aliases of an already computed outcome. Selection identities stay internal and do not change the expression-report schema.

The checker consumes a selected identity even when the commit target is invalid, matching Python error recovery. Branch environments clone bindings but share consumption state, so an illegal branch commit cannot hide subsequent use of the same selection.

## Exploration contract

Each exploration body must contain exactly one simulation expression or receives F3401 at the exploration span. This is a syntactic count: nested arguments, nested explorations, and unknown method calls still contribute. Counting happens before body checking so diagnostic order agrees with the reference. This does not make otherwise forbidden nested operations valid.

Existing checks reject binding redefinition, candidate shadowing, forbidden branch effects, and mismatched snapshot origins. Exploration locals do not escape their branch environment.

## Evidence and boundaries

The shared corpus adds 28 ownership cases and rechecks 131 type, effect, and lineage cases. The harness compares rejection codes, order, and exact spans, or every expression report on success. Four Rust unit tests additionally protect identity behavior, stage isolation, and syntactic simulation counting.

The earlier `types`, `effects`, and `lineage` commands preserve their narrower checks. Declaration failures still stop body analysis. Parity is established for the tested shared subset, not all possible source text; native identifier support remains as documented by the syntax frontend.

Static selection identities are compiler bookkeeping, not runtime authorization tokens. Python remains responsible for typed IR, execution, durable receipts, and transactional selection consumption. Day 8 adds native typed IR lowering; no runtime or release transition is implied by this milestone.
