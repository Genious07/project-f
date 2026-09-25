# Reproducible offline evidence

Day 6 reports use report version 0.0.2 and evidence version 1. They contain the checked IR and an ordered event stream with snapshots, proposal inputs and candidates, exploration results, selections, and commit payloads and receipt references. Every exploration and selection is recorded, including programs with multiple operations. The report's top-level summary still describes its final exploration, selection, and outcome.

```bash
python3 -m foresee demo examples/repair.fore --workspace build/replay-demo
python3 -m foresee replay build/replay-demo/run-report.json
```

## What replay does

1. Verify the outer report checksum.
2. Reconstruct source from the recorded IR and run the current compiler's checks. Compare the entire normalized typed IR and program identity with the recorded values.
3. Supply recorded snapshots and proposal results to an offline interpreter. No model provider is called, and no target database or run journal is opened.
4. Re-execute simulation, domain checks, integer metrics, candidate eligibility, and selection. The policy minimizes the declared metric and breaks ties by lexicographic candidate ID, as specified by IR semantics 0.0.3.
5. Compare every exploration and selection event, validate that each recorded commit payload matches the reproduced selection, and check its receipt reference against the recorded operation identity.
6. Require exact event consumption and compare the final decision summary and outcome.

Missing, reordered, or trailing events are rejected. Wrong program identity, incorrect inferred types, altered metrics/checks/winners, and mismatched receipt references fail even if the outer checksum was recomputed. Empty candidate sets and stale outcomes can also be reproduced. Provider generation itself is not rerun; recorded proposals are inputs to the reproduced decision.

## Interpreting the result

| Field | Meaning |
| --- | --- |
| `checksum_valid` | The report matches its supplied checksum |
| `decision_reproduced` | Recorded inputs reproduce the checked program's decisions |
| `origin_authenticated` | Always false until authenticated evidence is implemented |
| `target_effect_verified` | Always false for offline replay |
| `live_calls` | Zero |

`verified` is retained for CLI compatibility and means the checks applicable to that report version passed. Check `decision_reproduced` when automation requires actual reproduction. Version 0.0.1 reports remain readable but only receive checksum verification. Unknown versions fail. Deleting required evidence from a version 0.0.2 report fails rather than silently falling back.

A self-consistent rewritten report is not proof of authenticity. An editor who replaces the inputs, program, outputs, and checksums coherently can construct a different reproducible report. Offline replay cannot establish who ran it, when it ran, whether the inputs came from the claimed database, or whether a live effect actually happened. Commit outcomes are recorded external observations, not effects performed by replay. Use receipt reconciliation for local target evidence; origin authentication remains future work.

## Data handling and retention

Evidence includes catalog rows, prompts, candidate patches, program details, and receipt references. Journaled reports also contain a local journal path and run ID. The default is local storage; nothing is uploaded by the CLI. Generated workspaces and databases remain git-ignored. Reports are retained until the operator removes them; there is no automatic expiration or cleanup.

Keep the original evidence with the target and journal backups for the required audit period. Create a separate redacted copy for sharing and set `evidence.redacted` to true. Replay rejects explicitly redacted evidence because it cannot reproduce a complete decision from omitted inputs. Do not claim replayability for a redacted copy, and do not overwrite the only original with it. Even metadata can reveal local paths or prompts; review the whole artifact before sharing it.

There is no automatic field redaction in this release. A replayable sanitized fixture must be generated and run as a new decision with sanitized inputs, not presented as proof about the original data. Retention and access control are deployment responsibilities.

## Scope

The offline interpreter uses the same deterministic domain functions as live exploration, so this checks recorded results against executable semantics rather than providing an independent implementation proof. It has no live adapter, but it is not a resource-limited sandbox for arbitrarily large hostile files. Crash recovery does not reconstruct missing full reports from journals. Those are separate capabilities.
