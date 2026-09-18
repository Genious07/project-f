# Bootstrap language contract

This prototype tests one claim: an AI-assisted decision should be expressed as a bounded experiment whose live effect is explicit, reviewable, and safe to retry.

## Execution phases

1. `snapshot` captures a revisioned, immutable view of a resource.
2. `propose` obtains typed candidate plans. The bootstrap uses a deterministic fixture provider so tests and replay do not depend on a model API.
3. `explore` runs every candidate against isolated in-memory state.
4. `check` records a mandatory condition for candidate eligibility.
5. `measure` records an integer objective.
6. `select` chooses from the complete eligible set with deterministic tie breaking.
7. `commit` consumes the selected capability and opens one target transaction.

The compiler records used effects and rejects any effect absent from the decision declaration. `simulate`, `check`, and `measure` are restricted to exploration. A live `commit` inside exploration produces diagnostic `F3102`.

## Bootstrap grammar

```ebnf
program       = { resource | model | decision } ;
resource      = "resource" name ":" type ";" ;
model         = "model" name ":" type ";" ;
decision      = "decision" name "(" ")" [ "->" type ]
                "!" "{" effect { "," effect } "}" block ;
effect        = name "(" name ")" ;
block         = "{" { statement } "}" ;
statement     = "let" name [ ":" type ] "=" expression ";"
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
```

## Commit protocol

The SQLite adapter stores the domain rows, monotonic resource revision, and receipt ledger in the same database. A commit:

1. derives an intent digest and stable commit ID from the program, snapshot, resource, and selected plan;
2. opens `BEGIN IMMEDIATE`;
3. returns the existing receipt when the same intent was already handled;
4. compares the live snapshot digest with the selected snapshot;
5. records a terminal `stale` receipt without applying patches when they differ;
6. validates the patch field allowlist;
7. applies the derived-field patch, advances the revision, and stores the `applied` receipt in one transaction.

The first domain permits writes only to `unit_price_cents`. Source fields remain immutable even if a proposed candidate tries to modify them.

## Replay contract

Each run report contains the program digest, all candidate check results and metrics, the selected plan ID, commit outcome, and a digest over the report. Replay verifies this evidence from a file. It opens no target database and makes no model call.

## Production path

The reference implementation deliberately keeps the language surface small. The next compiler stages are:

1. replace ad hoc bindings with a typed intermediate representation;
2. add nominal `Snapshot<R>`, `Plan<R>`, `Trials<R, M>`, and affine `Selected<R>` types;
3. introduce provider traits for models, resources, journals, policy, and clocks;
4. port the lexer, parser, type checker, and IR serializer to Rust;
5. add signed provider evidence, crash recovery, and conformance fixtures shared by the Python and Rust implementations;
6. add adapters only after their transaction and receipt semantics pass the conformance suite.

The Python bootstrap remains the executable semantic oracle during that port.
