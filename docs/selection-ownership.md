# Selection ownership and isolated exploration

## Single-use selections

A selection is affine: it may be used for at most one commit. Assigning it to another binding preserves the same ownership identity. Committing through either name invalidates subsequent uses through every alias. The compiler reports `F3400` on reuse, including taking a new alias after consumption. Unused selections are permitted. Selecting again from completed trials creates a distinct selection; this rule constrains each selection, not the number of selections a program may request.

The runtime returns an opaque `Selected` identity. Its internal registry owns a copied plan and snapshot payload and the nominal target resource. Commit requires an issued, unconsumed identity from the same runtime with the matching target. Ordinary dictionaries, manually constructed tokens, tokens from another runtime, and consumed tokens fail before adapter invocation.

Consumption happens before calling the adapter, including when the adapter raises. A receipt retry is separate from reuse of a language selection. Durable recovery and reconciliation are Day 5 work. The low-level Catalog adapter remains a trusted internal API that accepts validated commit payloads; it does not itself authenticate language tokens. Python reflection or direct access to private registries is outside this trust model.

## Exploration isolation

Every branch must contain exactly one simulation expression. The compiler rejects zero or multiple simulations with `F3401`. The interpreter counts actual simulations independently and marks a branch failed if it violates the rule.

Snapshots contain copied read-only rows with immutable scalar fields. JSON exports copy rows rather than exposing internal mappings. Candidate sets, branch plans, and captured mutable variables are copied so one branch cannot change another branch's inputs. The committed plan comes from the runtime's retained candidate evidence, not a mutable branch-local dictionary.

All supplied candidates finish evaluation before a `TrialSet` token is issued. Selection accepts only issued completed trial sets. Plans require string IDs and patch arrays, and IDs must be unique. Ranking minimizes the declared integer metric, then compares the candidate ID lexicographically. Reordering candidates therefore preserves the winner, including ties.

## Outcomes

Each evaluated candidate records one of `eligible`, `rejected` (a failed check), or `evaluation_failed` (an exception or invalid simulation count). A failed branch does not stop evaluation of the remaining candidates. Details, checks, and metrics remain in the report.

If no candidate is eligible, the run ends with `no_eligible_candidate` and performs no commit. A structurally invalid candidate set or duplicate IDs ends with `invalid_plans`. These are decision outcomes, not successful writes. The CLI's zero exit code means a report was produced; automation must inspect `outcome.status` for the decision result. Fatal compiler/runtime errors still return a nonzero exit code.

This milestone does not provide a sandbox, crash recovery, or semantic offline replay. Day 4 adds concurrent receipt handling under the [SQLite transaction contract](sqlite-transactions.md).
