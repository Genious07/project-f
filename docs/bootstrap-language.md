# Bootstrap language contract

This prototype tests one claim: an AI-assisted decision should be expressed as a bounded experiment whose live effect is explicit, reviewable, and safe to retry.

## Execution phases

1. `snapshot` captures a revisioned, immutable view of a resource.
2. `propose` obtains typed candidate plans. The bootstrap uses a deterministic fixture provider so tests and replay do not depend on a model API.
3. `explore` runs every candidate against isolated in-memory state.
4. `check` records a mandatory condition for candidate eligibility.
5. `measure` records an integer objective.
6. `select` chooses from the complete eligible set with deterministic tie breaking.
7. `commit` consumes a runtime-issued selection and opens one target transaction. See [selection ownership](selection-ownership.md) for alias and retry semantics.

The compiler records used effects and rejects any effect absent from the decision declaration. `simulate`, `check`, and `measure` are restricted to exploration. A live `commit` inside exploration produces diagnostic `F3102`.

## Executable subset after Day 1

Exactly one `Catalog` resource, one `Planner` model, and one decision are supported. Names may be chosen by the author. Decisions have no parameters and must end with exactly one outcome return. An optional return annotation must be `DecisionResult`. Day 2 adds checked let annotations as described in the [typed IR contract](typed-ir.md).

The shared `foresee/signatures.py` registry defines effects and method signatures. `Snapshot`, `Explore`, and `Commit` target the resource; `Infer` targets the model. Proposals take a snapshot, a string prompt, and a literal candidate count from 1 to 4, with plan type `Patch`. Simulation supports only `apply(plan)`. The only callable catalog methods are `source_fields_unchanged(state, state)`, `valid_unit_arithmetic(state)`, and `unresolved_units(state)`.

Checks require Boolean results. Metrics require integer expressions and the `Int` annotation. Duplicate metric names are rejected. Exploration cannot snapshot live state, call a proposal provider, nest exploration, select, commit, or return. Names beginning with `__` are reserved for interpreter state; resource and model names cannot be shadowed by local bindings. Unsupported forms produce compile diagnostics before the CLI opens a database.

Runtime dispatch uses an explicit method table and rejects branch effects independently. This is defense in depth for compiler-produced IR, not a sandbox for hostile Python callers or arbitrary edited IR. Day 2 statically tracks resource and snapshot lineage. Day 3 adds affine selections, runtime-issued tokens, read-only snapshots, isolated branch inputs, and exactly one simulation per branch.

## Bootstrap grammar

```ebnf
program       = { resource | model | decision } ;
resource      = "resource" name ":" type ";" ;
model         = "model" name ":" type ";" ;
decision      = "decision" name "(" ")" [ "->" type ]
                "!" "{" effect { "," effect } "}" block ;
effect        = name "(" name ")" ;
block         = "{" { statement } "}" ;
statement     = "let" name [ ":" annotation ] "=" expression ";"
              | "check" expression "else" string ";"
              | "measure" name ":" type "=" expression ";"
              | "return" expression ";" ;
expression    = "snapshot" name
              | "propose" name "<" type ">" arguments
              | "explore" name "in" expression "from" expression block
              | "simulate" name "." name arguments
              | "select" expression "minimize" name
              | "commit" expression "to" name
              | name [ "." name arguments ]
              | string | integer ;
arguments     = "(" [ expression { "," expression } ] ")" ;
annotation    = type [ "<" name ">" ] ;
```

## Commit protocol

The SQLite adapter stores the domain rows, monotonic resource revision, and receipt ledger in the same database. A commit:

1. derives an intent digest and stable commit ID from the program, snapshot, resource, and selected plan;
2. returns an existing receipt when the same intent was already handled;
3. opens `BEGIN IMMEDIATE` for a new intent;
4. compares the live snapshot digest with the selected snapshot;
5. records a terminal `stale` receipt without applying patches when they differ;
6. validates the patch field allowlist;
7. applies the derived-field patch, advances the revision, and stores the `applied` receipt in one transaction.

The first domain permits writes only to `unit_price_cents`. Source fields remain immutable even if a proposed candidate tries to modify them.

Receipt lookup currently precedes the transaction, so concurrent retry correctness is not established. Snapshot reads and commit-boundary arithmetic validation also need hardening. Day 4 addresses these limitations.

## Replay contract

Each run report contains the program digest, all candidate check results and metrics, the selected plan ID, commit outcome, and a digest over the report. Replay verifies this evidence from a file. It opens no target database and makes no model call.

Currently, verification checks only the report checksum and displays recorded results. It does not reproduce the decision or authenticate the author. A modified report with a recomputed checksum can pass. Reproducible offline evidence is planned for Day 6.

## Production path

The reference implementation deliberately keeps the language surface small. The next compiler stages are:

1. replace ad hoc bindings with a typed intermediate representation;
2. add nominal `Snapshot<R>`, `Plan<R>`, `Trials<R, M>`, and affine `Selected<R>` types;
3. introduce provider traits for models, resources, journals, policy, and clocks;
4. port the lexer, parser, type checker, and IR serializer to Rust;
5. add signed provider evidence, crash recovery, and conformance fixtures shared by the Python and Rust implementations;
6. add adapters only after their transaction and receipt semantics pass the conformance suite.

The Python bootstrap remains the executable semantic oracle during that port.
