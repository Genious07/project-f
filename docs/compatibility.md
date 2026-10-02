# Foresee alpha compatibility contract

This document defines the supported surface of `v0.1.0-alpha.1`. A behavior outside this matrix may be useful for experimentation, but it is not an alpha compatibility promise. Defect reports should identify the exact release or commit because schemas and guarantees may change before 1.0.

## Installation and platforms

| Surface | Supported | Boundary |
| --- | --- | --- |
| Python package | CPython 3.11, 3.12, 3.13, and 3.14 on Ubuntu | Tested by the hosted matrix from a built wheel |
| macOS package | CPython 3.14 on the current hosted macOS runner | Tested from a built wheel |
| Container | Pinned Python 3.14 slim image on Linux containers | Network-disabled execution with a persistent bind mount is tested |
| Rust frontend | Rust 1.98.1 on hosted Ubuntu and macOS runners | Lexer and parser only |
| Windows | Unsupported in this alpha | No installation, path, locking, or crash-recovery claim |
| Package registries | Unsupported | Artifacts are distributed through GitHub Releases, not PyPI or a container registry |

The Python wheel is the supported execution artifact. The source archive is provided for inspection and rebuilding. The Rust binary is built from source and is not attached as a release artifact in this version.

## Versioned interfaces

| Interface | Version | Compatibility rule |
| --- | --- | --- |
| Package | `0.1.0a1` | Pre-1.0 alpha, with no forward-compatibility promise |
| Rust syntax tree | 1 | Shared fixtures compare token values, AST values, and source spans |
| Typed IR | 0.0.3 | The runtime rejects missing, older, and newer schemas |
| Report | 0.0.2 | Full semantic replay; report 0.0.1 remains checksum-only |
| Evidence stream | 1 | Required events must be complete and ordered |
| Project configuration | 1 | Unknown and missing fields are rejected |
| SQLite adapter protocol | 2 | Older receipts are preserved but not migrated or matched automatically |

Rebuild typed IR from source when the IR schema changes. Do not use rebuilt artifacts as transparent retries of operations created by an older adapter protocol.

## Exact language surface

A supported executable program contains exactly:

- one resource declaration with type `Catalog`;
- one model declaration with type `Planner`;
- one parameterless decision;
- an optional decision return annotation of `DecisionResult`;
- one final outcome return;
- declared effects that cover every used operation.

The supported effects are `Snapshot(resource)`, `Infer(model)`, `Explore(resource)`, and `Commit(resource)`. The compiler rejects unknown effects and undeclared use.

The executable expression and statement surface is:

- immutable `snapshot` creation;
- fixture-backed `propose` of `Patch` candidates, using a string prompt and literal limit from one to four;
- `explore` over every candidate with exactly one `simulate resource.apply(plan)` per branch;
- Boolean `check` statements;
- integer `measure` statements with unique metric names;
- deterministic `select ... minimize metric` with candidate-ID tie breaking;
- one-time `commit` of a runtime-issued selection;
- checked local bindings and supported type annotations;
- string and nonnegative ASCII integer literals;
- one outcome return after execution statements.

Only these catalog methods are callable:

- `source_fields_unchanged(state, state) -> Bool`
- `valid_unit_arithmetic(state) -> Bool`
- `unresolved_units(state) -> Int`

Exploration cannot read a new live snapshot, invoke a proposal provider, nest exploration, select, commit, or return. Resource lineage and snapshot lineage must match across proposals, simulations, checks, metrics, selection, and commit. A selected value is affine: aliases refer to the same capability, and the first commit consumes it.

## Resource and provider surface

The only executable resource adapter is the prepared SQLite catalog created by `foresee init`. Its domain rows contain `id`, `title`, `pack_price_cents`, `units_per_pack`, and `unit_price_cents`. A plan may write only `unit_price_cents`. Source fields are immutable, row identity must already exist, and unit arithmetic is rechecked inside the commit transaction.

The built-in model paths are deterministic fixture candidates and user-supplied candidate JSON. There is no remote model call, credential handling, arbitrary plugin loader, or model-generated live request in this alpha.

The supported commands are:

| Command | Supported role |
| --- | --- |
| `foresee init` | Create a new prepared project without overwriting a path |
| `foresee check` | Parse and semantically validate source without opening a target |
| `foresee build` | Emit typed IR 0.0.3 |
| `foresee run` | Execute a configured project against an existing prepared catalog |
| `foresee inspect` | Read recorded candidate checks, metrics, selection, and outcome |
| `foresee replay` | Reproduce a recorded decision without a target or model provider |
| `foresee reconcile` | Resolve journal state from target receipts without reapplying an operation |
| `foresee demo` | Run the explicit seeded catalog example |
| `foresee-syntax lex` | Emit Rust token output for supported syntax |
| `foresee-syntax parse` | Emit Rust syntax AST for supported syntax |

## Tested guarantees

Within the documented SQLite protocol and supported writer model:

- compile and preflight failures occur before target access;
- every candidate is evaluated before deterministic selection;
- invalid, stale, rejected, evaluation-failed, and no-winner outcomes do not apply a domain patch;
- a successful domain patch, revision advance, and receipt are stored in one transaction;
- concurrent retries of one operation and intent return one terminal receipt and do not duplicate the effect;
- a conflicting intent cannot reuse the same explicit operation ID;
- crashes before the transaction, before commit, and after commit before acknowledgement can be reconciled from durable evidence;
- replay recomputes checks, metrics, eligibility, and selection from recorded inputs without live provider or database access;
- incomplete or inconsistent evidence fails instead of silently falling back to checksum-only verification.

These guarantees do not make the Python process a security sandbox. Replay does not authenticate the report author and does not independently query the live target to prove its state.

## Bounded inputs

| Input | Limit |
| --- | --- |
| Foresee source | 1,000,000 bytes |
| Project configuration | 65,536 bytes |
| Candidate JSON | 2,000,000 bytes |
| Candidate count | Configured maximum from one to four; an empty supplied set is valid |
| Patches per candidate | 1,000 |
| Evidence budget | Configured from 16,384 to 2,000,000 bytes for IR and event payload |
| Rust expression nesting | 128 levels |

The evidence budget is not a bound on total report size, database size, or process memory. Offline replay is not a hostile-file sandbox.

## Explicitly unsupported

- multiple resources, models, decisions, or decision parameters;
- general-purpose control flow, user-defined functions, loops, imports, modules, or concurrency;
- arbitrary schemas, SQL statements, HTTP effects, queues, cloud services, or external APIs;
- remote model providers and model credentials;
- authenticated evidence signatures or independently verified target effects;
- automatic receipt, IR, report, or journal migration;
- relocating a retained journal to a different absolute target path;
- a native Rust type checker, typed IR generator, runtime, replay engine, or adapter;
- a hosted multi-tenant service, web interface, editor extension, or language server;
- Windows execution and deployment.

## Defect reproduction contract

Compiler and runtime defect forms require:

1. exact Foresee version or commit;
2. operating system, architecture, and language runtime versions;
3. minimal complete Foresee source;
4. sanitized configuration and candidates when execution is involved;
5. expected result;
6. actual result with diagnostic, exit code, or structured outcome;
7. an explicit statement of whether a live effect occurred;
8. exact reproduction commands;
9. the available report, journal, receipt, and backup evidence for runtime defects.

No product defect remained open from the `v0.1.0-alpha.1` acceptance run. The release-machine default interpreter was Python 3.9, outside the supported matrix, and correctly refused the package. Repeating artifact verification with supported Python 3.14 passed. This was an environment selection issue and did not justify a language or runtime regression fixture.
