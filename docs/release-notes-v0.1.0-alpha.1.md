# Foresee v0.1.0-alpha.1

Foresee is an experimental decision language for AI-assisted changes that need explicit boundaries, deterministic evaluation, safe retries, and inspectable evidence. This first developer alpha proves the model in one intentionally narrow domain: selecting and committing catalog repairs to SQLite.

## What is included

- A compiler for the supported Foresee source subset with typed IR 0.0.3.
- Static resource and snapshot lineage checks.
- Single-use selections and isolated candidate simulation.
- Deterministic complete-set selection and structured no-winner outcomes.
- Transactional SQLite effects with freshness checks and durable receipts.
- Idempotent retry behavior for the documented adapter protocol.
- Durable run journals, crash injection, and read-only reconciliation.
- Evidence report 0.0.2 with semantic offline replay.
- Project initialization and operation on user-prepared catalogs and candidate files.
- An installable Python CLI, source distribution, and container entry point.
- A Rust lexer and parser checked against 28 shared syntax fixtures.

## Install

Download the wheel attached to this release, then install it in a Python 3.11 or newer virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install project_f_bootstrap-0.1.0a1-py3-none-any.whl
.venv/bin/foresee init my-catalog --demo-data
.venv/bin/foresee run --project my-catalog/foresee.json
```

The source archive and `SHA256SUMS` file are attached for inspection and verification.

## Release validation

- 80 Python tests passed on Python 3.14.
- Four Rust unit tests passed.
- All 28 shared syntax fixtures matched across Python and Rust.
- A clean wheel installation completed the full CLI workflow and cold backup/restore outside the source checkout.
- Seven separate network-disabled containers shared one persistent project without duplicating its applied effect.
- The GitHub Verify workflow passed across the supported Python, Rust, macOS, Linux, and container jobs for the release commit.

The suite includes successful commit, stale-state rejection, invalid input before target access, deterministic no-winner behavior, concurrent retry, crashes at transaction boundaries, lost commit acknowledgement, reconciliation, and semantic replay tamper detection.

## Trust boundary

This alpha is a local developer tool for the documented SQLite catalog domain. It is not a security sandbox, hosted service, or general-purpose workflow language. Offline replay checks recorded decisions but does not authenticate report origin or independently prove the live target effect. The fixture provider is deterministic; a real model provider is not included in this release.

Python 3.11 through 3.14 on Ubuntu and Python 3.14 on macOS are covered by hosted CI. Windows is not yet supported. The Rust component provides syntax parsing only in this release.

## Next milestone

The next 15 development days focus on a native Rust semantic checker, typed IR lowering, canonical program identities, differential conformance, compiler hardening, and a minimal language server. See `docs/next-15-days.md` for daily deliverables and acceptance gates.
