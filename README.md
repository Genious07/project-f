# Project F

Private local development workspace for an experimental decision language.

This checkout is intentionally ahead of the public placeholder repository. Do not push it until disclosure is explicitly approved.

## Bootstrap prototype

The current prototype is a Python standard-library reference implementation. It validates the first language slice before a production Rust port:

- resource and model declarations
- declared effects
- immutable snapshots
- fixture-backed typed plan proposals
- isolated candidate exploration
- domain checks and integer metrics
- complete-set selection
- transactional commit with a target receipt ledger
- stale-state rejection and offline replay

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
