# Projects, providers, and prepared catalogs

Day 7 adds a project workflow for the supported single-resource SQLite language subset. It requires Python 3.11 or newer and no API key. Day 9 adds [wheel installation and containers](installation.md); the walkthrough below also works directly from a source checkout.

## New project walkthrough

From the repository root, expose the package on Python's import path and create an example project outside the checkout:

```bash
export PYTHONPATH="$PWD"
python3 -m foresee init ../catalog-example --demo-data
cd ../catalog-example
python3 -m foresee check decision.fore
python3 -m foresee build decision.fore -o .foresee/program.json
python3 -m foresee run --entry repair_catalog
```

`run` prints an absolute report path, journal path, run ID, selection, and outcome. Use those returned paths:

```bash
python3 -m foresee inspect .foresee/RUN_ID.json
python3 -m foresee replay .foresee/RUN_ID.json
python3 -m foresee reconcile .foresee/runs.db --run-id RUN_ID
```

Replace `RUN_ID` with the printed identifier. `inspect` displays recorded candidate checks and metrics after checking the checksum; it does not reproduce the decision. Use `replay` for reproduction.

`init` requires a new directory and never overwrites an existing one. It creates source, JSON configuration, a candidate file, a gitignore, and an empty prepared catalog. Only `--demo-data` requests sample rows and matching candidates. The older `demo` command remains an explicit sample-data workflow.

## Configuration

`foresee.json` has this exact schema:

```json
{
  "version": 1,
  "source": "decision.fore",
  "entry": "repair_catalog",
  "target": "catalog.db",
  "candidates": "plans.json",
  "output": ".foresee",
  "max_candidates": 4,
  "max_evidence_bytes": 2000000
}
```

Relative paths resolve against the configuration file, not the calling directory. `run --project /path/to/foresee.json` selects another project. `--entry` overrides the configured entry name; it must match the program's sole supported decision. Multiple decisions and arbitrary resource adapters remain unsupported.

An ordinary `run` opens the target in existing-file mode. It does not create a missing database, add tables, migrate its schema, or seed rows. Configuration, source, entry, and candidate structure are validated before the target is opened. Each run writes a separately named report and appends to the journal. Output must be separate from project input files and the target database.

## Your own catalog and candidates

Initialize without demo data, then load your own rows into the prepared catalog. Its domain table is:

```sql
CREATE TABLE catalog_rows (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  pack_price_cents INTEGER NOT NULL CHECK (pack_price_cents >= 0),
  units_per_pack INTEGER NOT NULL CHECK (units_per_pack > 0),
  unit_price_cents INTEGER
);
```

The prepared database also contains `catalog_meta`, `foresee_receipts`, and `foresee_target`; preserve these tables and their identity. A database containing only arbitrary user tables is rejected rather than modified. Use the schema created by `init`, and follow the [transaction writer contract](sqlite-transactions.md).

For example, import data and advance its revision together:

```sql
BEGIN IMMEDIATE;
INSERT INTO catalog_rows VALUES ('tea', 'Loose leaf tea', 900, 3, NULL);
UPDATE catalog_meta SET revision = revision + 1 WHERE singleton = 1;
COMMIT;
```

Supply `plans.json` as a JSON array:

```json
[
  {
    "id": "repair-tea",
    "patches": [{"id": "tea", "unit_price_cents": 300}]
  }
]
```

Candidate IDs must be unique. Plans contain exactly `id` and `patches`; each patch contains exactly a row `id` and a nonnegative signed-64-bit integer `unit_price_cents`. Duplicate row patches, extra fields, wrong scalar types, and malformed structures fail preflight. Arithmetic and target row existence are evaluated against the target snapshot and validated again at commit. The program's proposal count takes at most that many candidates from the file in file order; selection tie-breaking remains deterministic by candidate ID.

An empty candidate array produces `no_eligible_candidate` without target writes. No source changes are needed to use different rows and candidates in this domain.

## Limits and failures

- Configuration: at most 65,536 bytes, with exactly the documented fields.
- Source: at most 1,000,000 bytes.
- Candidate JSON: at most 2,000,000 bytes, one to four maximum candidates configurable, at most 1,000 patches per candidate. Zero supplied candidates is valid.
- Evidence budget: 16,384 to 2,000,000 bytes for the serialized IR/event payload, including conservative formatting overhead. This is not a strict bound on the whole report, database size, or process memory.

The runtime checks evidence growth and reserves space for a commit event before invoking the adapter. If the budget is exhausted, it produces `evidence_limit` with incomplete evidence. A later failure in a multi-operation program does not undo earlier committed operations; consult its journal. Incomplete execution evidence is inspectable but cannot pass semantic replay.

Model and snapshot provider failures produce `provider_error`. A journaled commit adapter failure produces `commit_unresolved` and leaves the durable operation for reconciliation. It does not imply no write occurred. Source/configuration/fixture errors fail the command before execution.

`run` exits 0 for `applied`, 2 for a non-applied or unresolved outcome, and 1 for a command/preflight error. Inspect the structured `outcome.status`. Existing `demo` retains its report-produced exit convention; it is a demonstration command, not the new automation entry point.

## Provider interfaces

`foresee/providers.py` defines model, resource, journal, and clock protocols. The runtime accepts injected implementations. The built-in deterministic fixture provider remains the default; project runs use a copied candidate-file provider. No remote model provider, credentials, API spend, or arbitrary plugin loading is introduced.

The SQLite resource and run journal implement the corresponding local contracts. The clock supplies report metadata only and does not influence selection; offline reproduction uses a fixed clock. Resource simulation and method signatures remain catalog-specific. Implementing the protocol alone does not establish conformance for a new backend.

Generated project gitignores exclude runtime output and database files. Candidate fixtures and source are ordinary project files and may contain sensitive user data; apply the [evidence retention and sharing policy](offline-replay.md) when deciding what to publish.
