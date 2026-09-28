# Rust frontend milestone

Day 8 adds a Rust workspace with the `foresee-syntax` library and CLI. It independently implements lexical analysis, recursive-descent parsing, character-based source spans, and structured diagnostics for the supported syntax. Python remains the semantic compiler and runtime.

## Build and run

With rustup installed, the repository selects Rust 1.98.1 using `rust-toolchain.toml`. Cargo dependency versions and checksums are committed in `Cargo.lock`.

```bash
cargo build --workspace --locked
cargo test --workspace --locked
cargo fmt --all --check
target/debug/foresee-syntax lex examples/repair.fore
target/debug/foresee-syntax parse examples/repair.fore
python3 tools/check_frontends.py
python3 -m unittest discover -s tests -v
```

The CLI prints JSON. Successful lexing returns `tokens`; successful parsing returns `syntax_version: 1` and `syntax`. Failure returns `ok: false` and diagnostics with code, message, and span. Exit codes are 0 for syntax acceptance, 1 for a lexical/parser diagnostic, and 2 for usage or file errors. Source files exceeding 1,000,000 bytes are rejected by the CLI.

Syntax acceptance does not authorize execution. For example, an unknown resource type can parse successfully and still fail the Python semantic checker. Continue using `python3 -m foresee check`, `build`, and `run` for complete supported-language validation and execution.

## Isolated toolchain used for this milestone

The development machine initially lacked Rust. The toolchain was installed inside the ignored `.toolchain` directory, without modifying shell startup files. To use that local installation from this checkout:

```bash
export CARGO_HOME="$PWD/.toolchain/cargo"
export RUSTUP_HOME="$PWD/.toolchain/rustup"
export PATH="$CARGO_HOME/bin:$PATH"
cargo build --workspace --locked
```

These local binaries are not published to GitHub. Other users should use their own Rust installation. Initial toolchain and dependency installation requires network access; subsequent cached builds can use Cargo's offline mode.

## Conformance evidence

`fixtures/syntax/cases.json` defines 28 shared cases. Cases either contain standalone source or a base source path with literal substitutions. They cover the repair program, annotations, comments and CRLF/tab whitespace, Unicode strings, escape sequences, large and zero-prefixed integers, nested expressions, declaration/effect syntax, and malformed or unsupported constructs.

`tools/check_frontends.py` materializes each case and executes both frontends. For accepted cases it compares complete token streams and syntax trees, including source spans. For rejected cases it compares diagnostic codes and spans; exact diagnostic wording is not required to match. It also checks the reference compiler's expected semantic acceptance separately.

Four Rust unit tests cover source coordinates after Unicode strings, malformed declaration location, unsupported identifier characters, and nesting-limit diagnostics. The Python suite checks fixture expectations even when Rust is not installed. Cross-language checks are a separate mandatory command for this milestone, not silently skipped tests.

## Parity table

| Capability | Rust status | Evidence or limit |
| --- | --- | --- |
| ASCII identifiers and numeric literals | Implemented | Shared token parity |
| UTF-8 strings and supported escapes | Implemented | Shared cases plus span unit test |
| Arbitrary-size ASCII integer AST values | Implemented | serde_json arbitrary-precision numbers, shared large integer case |
| Current declarations, statements, expressions | Implemented | Shared AST parity |
| Character offsets and line/column spans | Implemented | Exact fixture comparisons |
| Diagnostic codes and source spans | Matching within shared subset | Message text may differ |
| Unicode identifiers and non-ASCII digits | Explicitly unsupported | Rust F1004; Python accepts some additional Unicode categories |
| Expression nesting over 128 levels | Explicitly rejected | Rust F2002; no claim of matching Python's recursion limit |
| Type, effect, lineage, ownership checking | Python only | Rust parse success is insufficient |
| Typed IR and program digest generation | Python checker via bridge | Native Rust generation deferred |
| SQLite execution, journals, replay | Python only | Existing runtime unchanged |

This table describes tested subset compatibility, not universal grammar equivalence or production readiness. Windows and Linux Rust builds have not yet been validated in this milestone.

## Shared syntax and typed IR bridge

Syntax version 1 matches the reference model's serialized `Program`: resources, models, decisions, statements, expressions, and spans. Expressions and statements carry a `kind`, `data`, and `span`; this format is intentionally distinct from executable typed IR 0.0.3.

`foresee.syntax_bridge.program_from_syntax` converts locally generated Rust output into reference model objects. `foresee.compiler.compile_program` then performs the same semantic checks and lowering used by the Python parser. The conformance runner checks that semantic acceptance agrees and valid fixtures produce identical typed IR and program digests through both frontend paths.

The bridge is for trusted local frontend output, not a general untrusted AST loader. It does not bypass the checker. Native Rust type checking and lowering remain unfinished; the bridge establishes the interchange boundary and executable comparison target for that port. They are deferred beyond this frontend milestone so packaging and alpha acceptance can proceed against the tested Python runtime.
