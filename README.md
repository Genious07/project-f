# Foresee

Foresee is an experimental decision language for AI systems that propose alternatives, test every candidate against a snapshot, and apply one selected change through an explicit commit boundary.

The project is designed for decisions that need more than a model response. A Foresee run records what was observed, which alternatives were considered, why one was selected, what effect was attempted, and how the result can be recovered and replayed. It can be installed and operated by an individual developer or a small team without a hosted Foresee service.

The first public developer alpha is available in [GitHub Releases](https://github.com/Genious07/project-f/releases). Start with the [project workflow](docs/projects.md), check the exact [alpha compatibility contract](docs/compatibility.md), see the completed [ten-day development plan](docs/development-plan.md), and follow the [next 15 development days](docs/next-15-days.md).

To run on your own prepared catalog, follow the [project workflow](docs/projects.md). It covers `init`, configuration, candidate fixtures, `run`, `inspect`, and offline verification.

The [installation guide](docs/installation.md) covers wheels, containers, persistent storage, backup/restore, and CI. Runtime dependencies are Python's standard library only.

A [Rust syntax frontend](docs/rust-frontend.md) now parses the shared language subset and is checked against Python fixtures. A [native Rust declaration checker](docs/rust-declarations.md) now validates declaration types, cardinality, and names. [Native expression type analysis](docs/rust-types.md) now checks annotations, calls, and outcomes. [Native effect checking](docs/rust-effects.md) enforces declared permissions and branch restrictions. [Native lineage validation](docs/rust-lineage.md) rejects mixed resource and snapshot origins. [Native ownership validation](docs/rust-ownership.md) tracks single-use selections and enforces one simulation per branch. Native checks now cover the current shared semantic subset. [Native typed IR lowering](docs/rust-ir.md) emits the checked IR body; [native canonical identity](docs/rust-identity.md) now produces matching program digests. Execution remains in Python.

## Developer alpha

The alpha is a Python standard-library reference implementation. It validates the first language slice while a production Rust compiler is developed:

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

This is an early reference implementation for one SQLite catalog domain. It includes signature validation, explicit runtime dispatch, [typed IR](docs/typed-ir.md), static snapshot lineage, and formatting-independent program digests. It supports [single-use selections and isolated branches](docs/selection-ownership.md), [transactional concurrent retries](docs/sqlite-transactions.md), durable intent journaling, receipt-based reconciliation, and [reproducible offline decisions](docs/offline-replay.md). Missing evidence remains unresolved rather than triggering a retry. The runtime is not a security sandbox, and offline replay does not authenticate report origin or prove live effects.

See the [development progress log](docs/progress.md) for completed milestones and validation evidence.
