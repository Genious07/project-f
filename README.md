# Project F

An experimental decision language for AI systems that propose alternatives, test them against snapshots, and apply a selected change through an explicit commit boundary. The language's working name is Foresee.

Start with the [ten-day development plan](docs/development-plan.md) for daily implementation work, acceptance checks, and release scope.

## Bootstrap prototype

The current prototype is a Python standard-library reference implementation. It validates the first language slice before a production Rust port:

- resource and model declarations
- declared effects
- immutable snapshots
- fixture-backed plan proposals
- isolated candidate exploration
- domain checks and integer metrics
- complete-set selection
- transactional commit with a target receipt ledger
- stale-state rejection and offline report verification

Requires Python 3.11 or newer. Run these commands from the repository root. No model API key is needed.

Run the demo:

```bash
python3 -m foresee demo examples/repair.fore
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Build inspectable IR:

```bash
python3 -m foresee build examples/repair.fore -o build/repair.fir.json
```

Verify a completed run without opening the database or invoking a model:

```bash
python3 -m foresee replay build/demo/run-report.json
```

The [bootstrap language contract](docs/bootstrap-language.md) describes the grammar, phase model, transaction protocol, replay evidence, and Rust production path. This is a bootstrap subset, not the complete language described in the design handbook.

## Current limits

This is an early reference implementation for one SQLite catalog demo. It includes signature validation, explicit runtime dispatch, [typed IR](docs/typed-ir.md), static snapshot lineage, and formatting-independent program digests. Day 3 adds [single-use selections and isolated branches](docs/selection-ownership.md). Concurrent commit correctness and crash recovery remain unfinished. The runtime is not a security sandbox. The replay command currently verifies a report checksum and displays recorded results; it does not independently re-execute the decision or authenticate the report's author. The development plan addresses these gaps before an alpha release.

See the [development progress log](docs/progress.md) for completed milestones and validation evidence.
