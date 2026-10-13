# Native compiler limits and fuzz smoke checks

The native frontend now rejects oversized inputs before constructing an unbounded syntax tree. Limits apply to library entry points as well as the CLI. The Python reference has not acquired these same limits; inputs outside native budgets are intentionally outside conformance parity.

| Budget | Native limit |
| --- | ---: |
| Source UTF-8 bytes | 1,000,000 |
| Tokens, excluding EOF | 8,192 |
| Identifier bytes | 128 |
| Integer literal digits, including leading zeros | 4,096 |
| Decoded string UTF-8 bytes | 65,536 |
| Top-level declarations in total | 128 |
| Effects per decision | 128 |
| Statements per block | 128 |
| Arguments per call | 128 |
| Active nested expressions | 16 |
| Returned diagnostics | 64 |
| Canonical JSON edge depth from root | 128 |

Constants live in `foresee-syntax::limits`. The source limit is checked before allocating the character vector. Both command-line readers consume at most 1,000,001 bytes, so a large file is rejected without loading the rest. The lexer bounds tokens and token values; the parser checks collection sizes before growing them. The global token budget also bounds the number of AST nodes. Combined identifier, collection, and expression budgets bound copied metric metadata and branch environments.

Expression depth was reduced from 128 to 16. This conservative budget constrains recursive parsing, AST decoding, checking, lowering, and JSON serialization together. The canonical encoder additionally rejects recursion beyond its explicit JSON depth budget. A nested scalar leaf counts as an expression, so 15 nested calls around a variable use the entire expression budget.

Limit failures use F0001. F2002 remains the expression-depth diagnostic. F0002 marks a diagnostic cap; remaining errors can be omitted. Lexing stops at its diagnostic cap, while semantic checking retains bounded recovery and caps its output. Declaration errors are similarly truncated. These diagnostics do not produce successful IR. The CLI returns 2 for unreadable files, invalid UTF-8, or oversized input before lexing; library source-size rejection is a diagnostic. Other source-limit rejections return 1. An internal serialization invariant failure remains a contract error, not successful output.

## Reproducible smoke campaign

```sh
cargo build --workspace --locked
python tools/fuzz_compiler.py
python tools/fuzz_compiler.py --seed 913 --count 1024 --output target/fuzz-extended
```

The default campaign runs 256 byte-mutation cases, 32 generated valid/invalid programs, and 25 explicit boundary or stress inputs through `lex`, `parse`, `ownership`, and `identity`: 1,252 native invocations. The expanded command runs 4,324 invocations. Both completed without failure at this milestone.

Boundary inputs include invalid UTF-8, oversized files, maximum-sized valid source/string/integer inputs, token floods, large metric metadata, declaration/effect/argument/statement floods, invalid escapes, diagnostic floods, and deeply nested calls and explorations. Mutations use a fixed seed and operate on both arbitrary bytes and valid example source.

Each native subprocess has a five-second wall-clock timeout, a three-second CPU limit, and a 16 MiB limit on each output file. Linux additionally sets a 512 MiB virtual address-space limit. macOS uses the CPU/time/output limits without an address-space cap. Output is captured in temporary files and checked before reading into memory. These are smoke-test process limits, not limits installed by the compiler when run normally.

The runner rejects crashes, unexpected exit statuses, internal errors for bounded valid UTF-8 input, malformed responses, excessive diagnostics, and artifacts leaked on rejection. Successful identity output must pass structural IR validation, match its canonical preimage and SHA-256 digest, and equal Python-generated IR. The campaign does not demand Python parity for rejection at a native resource boundary.

Summaries and failing raw source bytes go under ignored `target/fuzz-smoke/`. Reproduce a campaign with its seed and mutation count, or invoke the recorded stage directly against the saved `.fore` file. Linux and macOS CI run the default campaign and upload its artifacts alongside differential reports.

## Evidence and limits of the evidence

Seven added Rust tests cover exact source/token/value boundaries, collections and nesting, lexical and semantic diagnostic floods, direct library entry points, and canonical recursion. Three Python tests exercise seeded input reproducibility and the smoke runner's handling of crashes, internal errors, invalid identity, and artifacts on failure.

The existing 354-case conformance run and all earlier comparison runners still pass within these budgets. Successful in-budget source retains its existing IR and digest. This milestone changes native acceptance limits, not the IR schema or runtime behavior.

This is a bounded mutation smoke suite, not a coverage-guided fuzzer or a proof that every hostile input is safe. Linux process limits provide a campaign memory ceiling; macOS results do not measure or prove a peak-memory ceiling. The source and collection budgets constrain growth by construction, but allocator behavior and future compiler changes still warrant monitoring and additional fuzzing. No runtime security sandbox is introduced.
