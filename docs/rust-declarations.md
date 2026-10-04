# Native Rust declaration checker

Milestone day 3 adds the `foresee-semantics` library and a development command for declaration checks. It runs entirely in Rust. This is one stage of the [semantic compiler architecture](rust-semantic-architecture.md), not a complete native compiler.

## Use

```bash
cargo build --workspace --locked
target/debug/foresee-semantics declarations examples/repair.fore
python3 tools/check_declarations.py
```

Successful JSON output contains `checked_phase: "declarations"`, `executable: false`, and a symbol table. Exit 0 means only that parsing and declaration checks passed. An empty decision body, unknown effect, or undefined variable in a body can still pass this stage. Continue using the Python `foresee check` command for full semantic validation.

Exit 1 returns syntax or declaration diagnostics. Exit 2 indicates invalid command usage, missing/unreadable input, invalid UTF-8, input over 1,000,000 bytes, or an internal frontend contract error. The CLI reads at most 1,000,001 bytes before rejecting oversized input.

## Implemented rules

- Exactly one resource, model, and decision: F3200.
- Resource type `Catalog` and model type `Planner`: F3201.
- Unique names across all three declaration kinds: F3000.
- Syntax failures, including decision parameters and unsupported return annotations, propagate from the existing Rust frontend.

Diagnostics preserve the Python declaration-check order: cardinality, resource types, model types, then duplicate names. Cardinality and duplicate-name errors retain the synthetic span `(0, 0, 1, 1)`. Type errors use declaration source spans. Offsets count Unicode characters, not UTF-8 bytes. A failed check returns no symbol table.

## Library boundary and symbols

`check_declarations(&str)` returns `Result<DeclarationSymbols, DeclarationFailure>`. Resource, model, and decision identifiers are distinct Rust types with private constructors. `SymbolId` identifies the namespace. `DeclarationSymbols::lookup` returns a read-only symbol, and `symbols()` preserves resource, model, then decision order, with source order inside each group. IDs are zero-based within each namespace.

The symbol table retains names and spans for later diagnostics; it is not executable IR and has no program digest. Private serde structures decode declaration headers from locally generated syntax version 1. Effects and bodies remain uninterpreted here. The owned expression AST, local bindings, inference, and checked-program wrapper belong to subsequent milestones. No arbitrary external AST loader is exposed.

## Evidence

`fixtures/declarations/cases.json` supplies 28 shared cases: a complete valid example, missing and extra declarations, unsupported types, collisions within and across namespaces, combined errors, declaration reordering, renamed symbols, Unicode comments, CRLF/tab positions, syntax failures, and intentionally deferred body/effect failures.

`tools/check_declarations.py` compares Rust diagnostics against Python, including exact codes, counts, order, and spans. For successful declaration checks it compares the entire symbol output. It filters the Python checker to F3200/F3201/F3000 after syntax succeeds; this is deliberately declaration parity, not a claim of complete semantic acceptance. Five additional CLI failure checks cover usage, unsupported mode, missing files, invalid UTF-8, and oversized input.

Four Rust unit tests cover namespace lookup, absence of a success table on errors, stable symbols and spans, and the limited meaning of declaration success. A Python test validates the reference corpus even without Rust. Hosted Rust jobs on Ubuntu and macOS run the native differential check after building the workspace.

## Next

Day 4 introduces typed expression nodes and inference. Effects, lineage, ownership, native typed IR lowering, and canonical digests remain later work. The Python runtime, SQLite adapter, and offline replay are unchanged.
