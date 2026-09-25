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

Reproduce a completed decision offline without opening the database or invoking a model:

```bash
python3 -m foresee replay build/demo/run-report.json
```

Reconcile recorded operations after an interrupted demo:

```bash
python3 -m foresee reconcile build/demo/runs.db
```

See the [recovery guide](docs/recovery.md) for crash exercises, run states, and unresolved outcomes.

The [bootstrap language contract](docs/bootstrap-language.md) describes the grammar, phase model, transaction protocol, replay evidence, and Rust production path. This is a bootstrap subset, not the complete language described in the design handbook.

## Current limits

This is an early reference implementation for one SQLite catalog demo. It includes signature validation, explicit runtime dispatch, [typed IR](docs/typed-ir.md), static snapshot lineage, and formatting-independent program digests. It supports [single-use selections and isolated branches](docs/selection-ownership.md), [transactional concurrent retries](docs/sqlite-transactions.md), durable intent journaling, and receipt-based reconciliation. Day 6 adds [reproducible offline decisions](docs/offline-replay.md). Missing evidence remains unresolved rather than triggering a retry. The runtime is not a security sandbox, and offline replay does not authenticate report origin or prove live effects.

See the [development progress log](docs/progress.md) for completed milestones and validation evidence.
