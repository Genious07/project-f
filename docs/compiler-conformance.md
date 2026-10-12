# Differential compiler conformance

Run the current Rust compiler and Python reference together:

```sh
cargo build --workspace --locked
python tools/check_compilers.py
```

The default run checks 226 distinct stored source texts and 64 generated valid/invalid pairs, for 354 total cases. It reports 124 accepted and 230 rejected programs with zero differences at this milestone. Each case runs native `lex`, `parse`, `ownership`, and `identity` commands. The comparison checks acceptance and exit codes, token and AST values and spans, diagnostic codes and order, expression types and lineage, complete typed IR, canonical bytes, and SHA-256 digests.

The runner uses the native binaries directly. No Python semantic bridge substitutes for native checking. Diagnostic prose is excluded from comparison. On declaration errors, the reference adapter applies the existing native early-stop gate; this remains an explicit behavior boundary. Character-level parity is scoped to the supported shared syntax subset.

## Reproducible generation

```sh
python tools/check_compilers.py --seed 451 --count 256 --output target/differential-extended
```

`--count` selects valid/invalid pairs, from zero through 1000. The second-seed run above checks 738 cases and also passes. Seeds control bounded variations in effects, duplicate permissions, aliases, annotations, prompts, large integers, metrics, comments, and line endings. Identifiers remain ASCII; Unicode is exercised inside strings. Each valid program has a paired mutation from one of eight error families: ownership, simulation count, effect namespace, lineage, missing metric, annotation, unknown method, or unknown binding. The harness checks the generator's expected acceptance and error code as well as compiler agreement.

Stored fixtures are deduplicated by exact source text, with every contributing label retained. The earlier stage-specific runners remain in CI because they also protect narrower stage behavior and frozen identity expectations. The new runner tests the complete pipeline across their combined corpus.

## Failure evidence and replay

`target/differential/summary.json` records seed, planned and processed counts, accepted and rejected counts, and failures. A mismatch records the source case, failing stage/category, expected result, native output, exit code, and stderr where available. Source and evidence filenames use a prefix of the original source hash.

```sh
python tools/check_compilers.py --replay target/differential/CASE_HASH.fore
python tools/check_compilers.py --seed 451 --count 256 --minimize
```

Replay reads exact UTF-8 bytes, preserving line endings. The optional reducer attempts up to 40 whole-line deletions while preserving the mismatch stage/category and reference acceptance. It is a local reduction aid, not a proof of a globally minimal input. Infrastructure failures are not reduced. Evidence retains the original source and output alongside the reduced replay source; rerun the latter to obtain its output.

The runner returns zero only when all planned cases pass. It stops after five failures, reports partial counts, and returns one. Native subprocesses have a ten-second timeout. Invalid count arguments are rejected by the CLI. A reference exception, invalid JSON, abnormal exit, timeout, or artifact emitted on rejected source counts as a failure. Generated reports are under ignored `target/`; reviewed regressions belong in `fixtures/regressions/cases.json`.

The initial regression file contains two hand-reduced cases for previously supported rules: reading an alias after consumption, and counting a simulation nested inside an unknown call. These were retained from known edge cases, not discovered as new defects in this run. No compiler changes were needed for this milestone.

## Verification and limits

Seven Python tests check reproducible generation and all eight error families, corpus deduplication, successful protocol comparison, corrupted types and digests, diagnostic location changes, artifact leakage, process failures, malformed JSON, timeouts, reduction, and saved replay evidence. Linux and macOS CI run the default harness and upload its summary and failure files even when the comparison fails. No external runtime service or model credential is required.

This is bounded grammar-based differential testing. It does not exhaust the language, prove compiler correctness, validate runtime transactions, or exercise hostile-input resource limits. Those limits and a bounded fuzz campaign are the next milestone. Python remains the runtime.
