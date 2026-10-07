# Native Rust expression type analysis

For the subsequent stage that also checks effect permissions and branch restrictions, see [native effect checking](rust-effects.md). The `types` command keeps the day 4 boundary described here.

Milestone day 4 adds the `types` development command and `check_types(&str)` library entry point. They infer types without Python and return an inspection report. This stage does not emit executable typed IR or authorize target access.

```bash
cargo build --workspace --locked
target/debug/foresee-semantics types examples/repair.fore
python3 tools/check_types.py
```

## Implemented behavior

The type analyzer first requires valid declarations, then decodes the local syntax tree into owned Rust expression and statement enums. It checks bindings, annotations, method receivers and signatures, proposal arguments and literal limits, simulation arguments, check/metric types, selection metrics, commit receiver types, and final decision returns.

Every expression in an accepted analysis has a deterministic preorder inspection ID, operation name, source span, and inferred type. Kinds are `int`, `string`, `bool`, `snapshot`, `plan`, `plans`, `simulated`, `trials`, `selected`, and `outcome`. The internal recovery kind `error` is never exposed as a successful result.

Resource-bearing values carry resolved native resource IDs internally. Inspection output resolves these back to declaration names and includes snapshot lineage and ordered trial metric names, matching Python's type descriptions. Aliases preserve these fields. Every new snapshot gets a new traversal-ordered identity. Propagating lineage at this stage does not enforce cross-snapshot compatibility; that is day 6 work.

The native statement environment checks initializers before inserting bindings. Exploration clones the outer environment; branch-local names do not escape. Method calls use the Catalog method allowlist, and unknown methods stop before visiting their arguments, preserving the reference diagnostic behavior. Integer syntax remains arbitrary precision rather than being narrowed to catalog patch integers.

## Output and exit codes

Success contains `ok: true`, `checked_phase: "types"`, `executable: false`, and an `expressions` array. Each entry has `node_id`, `op`, `span`, and `inferred_type`. The latter contains `kind`, `resource`, `metric_names`, and `lineage`.

Exit 0 means this stage passed. Exit 1 returns diagnostics with codes and spans and no expression report. Exit 2 covers command usage, file/UTF-8/size errors, and internal frontend contract failures. The CLI retains the 1,000,000-byte input limit. No database, journal, model provider, or effect adapter is called.

Declaration failures stop before body analysis. After declarations pass, type diagnostics accumulate in reference traversal order. The comparison runner applies that same staged boundary to Python.

## Exact stage boundary

In addition to declaration and syntax errors, this stage checks F3003-F3006, F3100, F3101, F3103, F3105-F3107, F3203-F3206, F3208-F3210, and F3300.

The following Python rules are deliberately deferred and filtered explicitly by the differential runner:

| Codes | Pending capability |
| --- | --- |
| F3202, F3001, F3002 | Effect declaration and coverage checks, day 5 |
| F3207, F3102 | Forbidden branch effects, day 5 |
| F3104, F3301 | Simulation receiver/branch alignment and origin validation, day 6 |
| F3400, F3401 | Selection consumption and exactly-one-simulation rule, day 7 |

A program with missing effects, a reused selected value, or mismatched snapshots can therefore pass `types`. Continue using Python's `foresee check` for complete validation. Native IR generation and canonical digests remain days 8 and 9. Type reports have no program digest and are not accepted as runtime capabilities.

## Validation

`fixtures/types/cases.json` contains 66 cases with explicit stage acceptance and required error-code expectations. `tools/check_types.py` compares native output against Python expression by expression, including operation order, all inferred fields, and source spans. Rejected cases compare exact diagnostic codes, counts, order, and spans, and must not return an expression report.

The corpus includes every current expression form, all annotation families, method argument errors, large integers, scope isolation, proposal bounds, invalid selection/commit/return types, duplicate metrics, Unicode and CRLF positions, and explicit deferred-rule cases. A Python corpus test checks expectations even without Rust.

Five additional Rust tests verify complete expression coverage, snapshot alias versus fresh identity, diagnostic cascade behavior, arbitrary-precision integers, and the limited meaning of stage success. Both Ubuntu and macOS Rust CI jobs run the new differential comparison alongside declaration and syntax checks.

The public alpha compatibility contract continues to describe the immutable v0.1.0-alpha.1 release. This development command is available from the current source checkout and has not been published as a new release.
