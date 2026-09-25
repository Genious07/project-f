# Typed IR contract, schema 0.0.3

Each expression contains `inferred_type` with four fields:

- `kind`: `int`, `string`, `bool`, `snapshot`, `plan`, `plans`, `simulated`, `trials`, `selected`, or `outcome`.
- `resource`: the nominal resource declaration name for resource-bearing values, otherwise null.
- `lineage`: the originating snapshot expression's identity, otherwise null.
- `metric_names`: measured names for trials, otherwise an empty array in JSON.

The compiler uses immutable type records. Inferred types are emitted only after checking succeeds. `error` is an internal recovery type and is never emitted by a successful build.

## Snapshot identity

Snapshot expressions receive deterministic identities `snapshot:1`, `snapshot:2`, and so on in compiler traversal order. These are static identities, not live database hashes or revision numbers. Two separate snapshots have different identities even if the database contents happen to match. Aliasing a snapshot preserves its identity.

Proposals inherit the input snapshot's resource and lineage. Exploration requires its proposal set and base snapshot to match. Each candidate plan and simulated state inherits that origin. Catalog calls inside exploration must read states from that branch's origin. Comparisons cannot mix states from different snapshots. Trials, selections, and commit outcomes preserve the same origin.

This release still supports one resource per executable program. The checker additionally validates receiver/resource identity, but multi-resource runtime support is not shipped. IR types describe compiler-checked source; editing JSON types does not create a trustworthy capability. Runtime-issued selection tokens enforce the commit boundary. Arbitrary hostile IR is outside the runtime trust model.

## Annotations

Supported scalar annotations are `Int`, `String`, and `Bool`. Resource-bearing annotations are `Snapshot<R>`, `Plan<R>`, `Plans<R>`, `Simulated<R>`, `Trials<R>`, and `Selected<R>`, where `R` is the declared resource name. `DecisionResult` annotates an outcome; its resource and lineage are inferred. Trial metric names and snapshot identity are always inferred rather than written in annotations.

```text
let base: Snapshot<catalog> = snapshot catalog;
let plans: Plans<catalog> = propose planner<Patch>(base, "Repair prices", 4);
```

Annotations assert the inferred kind and nominal resource. They cannot cast or erase lineage. A mismatched annotation produces `F3300`; a resource or snapshot mismatch produces `F3301`. Checks remain Boolean, metrics remain `Int`, duplicate metric names are rejected, and decision returns must be outcomes.

## Canonical program identity

The program digest is SHA-256 over UTF-8 JSON with sorted object keys and compact separators, before adding `program_digest`. Source locations are retained for compiler diagnostics but excluded from IR. Declaration spans, comments, whitespace, and checked let annotations do not affect executable identity. Effects are deduplicated and sorted. Expression types and deterministic lineage identifiers are included.

This is a structural semantic identity, not an equivalence proof. Renaming bindings or rearranging executable statements can change the digest. Changing a proposal prompt or candidate limit changes it. Separate compiler processes must produce the same digest for identical normalized programs.

## Version policy

Schema 0.0.2 added expression types and removed source spans from emitted declarations. Schema 0.0.3 tightens execution semantics: selections are consumed on commit, and branches execute exactly one simulation. The runtime requires exactly 0.0.3 and rejects missing, older, or newer versions with a rebuild instruction. Rebuild earlier IR from source. Day 6 introduces independent report format 0.0.2 with reproducible execution evidence; old report 0.0.1 remains checksum-only.

Schema versions must change when IR shape or interpretation changes. The new program digest changes commit intent identity relative to earlier versions. Do not use a rebuilt artifact as a transparent retry of an older interrupted commit; inspect the old target receipt first. Automatic migration and cross-version recovery are not yet implemented.
