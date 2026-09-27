"""Explicit local project configuration and user-supplied candidates."""
import json
from pathlib import Path

from .catalog import Catalog
from .compiler import compile_source
from .journal import Journal
from .providers import CandidateProvider
from .runtime import Runtime, save_report


SOURCE = '''resource catalog: Catalog;
model planner: Planner;
decision repair_catalog() -> DecisionResult
! { Snapshot(catalog), Infer(planner), Explore(catalog), Commit(catalog) } {
    let base = snapshot catalog;
    let plans = propose planner<Patch>(base, "Fill derived unit prices", 4);
    let trials = explore plan in plans from base {
        let after = simulate catalog.apply(plan);
        check catalog.source_fields_unchanged(after, base) else "Source fields changed";
        check catalog.valid_unit_arithmetic(after) else "Invalid unit arithmetic";
        measure unresolved: Int = catalog.unresolved_units(after);
    };
    let chosen = select trials minimize unresolved;
    return commit chosen to catalog;
}
'''


def read_json(path, limit=2_000_000):
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"input exceeds {limit} bytes: {path}")
    return json.loads(data)


def init_project(path, demo_data=False):
    # A new directory is required: never overwrite a user's files.
    path.mkdir(parents=True, exist_ok=False)
    config = {"version": 1, "source": "decision.fore", "entry": "repair_catalog",
              "target": "catalog.db", "candidates": "plans.json", "output": ".foresee",
              "max_candidates": 4, "max_evidence_bytes": 2_000_000}
    (path / "foresee.json").write_text(json.dumps(config, indent=2) + "\n")
    (path / "decision.fore").write_text(SOURCE)
    (path / ".gitignore").write_text(".foresee/\n*.db\n*.db-journal\n*.db-wal\n*.db-shm\n")
    plans = []
    catalog = Catalog(path / "catalog.db")
    try:
        if demo_data:
            catalog.seed()
            plans = [{"id": "repair-unit-prices", "patches": [
                {"id": "coffee", "unit_price_cents": 150},
                {"id": "filters", "unit_price_cents": 100}]}]
    finally:
        catalog.close()
    (path / "plans.json").write_text(json.dumps(plans, indent=2) + "\n")
    return path / "foresee.json"


def run_project(config_path, entry=None):
    config_path = config_path.resolve()
    config = read_json(config_path, 65536)
    fields = {"version", "source", "entry", "target", "candidates", "output", "max_candidates", "max_evidence_bytes"}
    if not isinstance(config, dict) or set(config) != fields or config["version"] != 1:
        raise ValueError("unsupported or incomplete project configuration")
    for field in ("source", "entry", "target", "candidates", "output"):
        if not isinstance(config[field], str) or not config[field]:
            raise ValueError(f"configuration {field} must be a nonempty string")
    maximum = config["max_candidates"]
    budget = config["max_evidence_bytes"]
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError("max_candidates must be from 1 to 4")
    if type(budget) is not int or not 16384 <= budget <= 2_000_000:
        raise ValueError("max_evidence_bytes must be from 16384 to 2000000")
    resolve = lambda key: (config_path.parent / config[key]).resolve()
    source, target, candidates, output = (resolve(k) for k in ("source", "target", "candidates", "output"))
    if output / "runs.db" in {source, target, candidates, config_path} or len({source, target, candidates, config_path}) != 4:
        raise ValueError("project input, target, and journal paths must be distinct")
    with source.open("rb") as handle:
        text = handle.read(1_000_001)
    if len(text) > 1_000_000:
        raise ValueError("source exceeds 1000000 bytes")
    ir = compile_source(text.decode("utf-8"), str(source))
    if (entry or config["entry"]) != ir["decisions"][0]["name"]:
        raise ValueError("requested entry is not the program's supported decision")
    plans = read_json(candidates)
    if not isinstance(plans, list) or len(plans) > maximum:
        raise ValueError("candidate count exceeds configuration or is not a list")
    seen = set()
    for plan in plans:
        Catalog._validate_plan(plan)
        if plan["id"] in seen or len(plan["patches"]) > 1000:
            raise ValueError("duplicate candidate ID or more than 1000 patches")
        seen.add(plan["id"])
    # All static inputs are checked before even opening the target.
    catalog = Catalog(target, existing=True)
    journal = None
    try:
        journal = Journal(output / "runs.db")
        runtime = Runtime(ir, catalog, journal=journal, model_provider=CandidateProvider(plans),
                          max_evidence_bytes=budget)
        report = runtime.run()
        path = output / (report["run_id"] + ".json")
        save_report(report, path)
        return {"report": str(path), "run_id": report["run_id"], "journal": report["journal"],
                "selection": report["selection"], "outcome": report["outcome"]}
    finally:
        catalog.close()
        if journal:
            journal.close()


def inspect_report(path):
    from .catalog import stable_digest
    report = read_json(path, 8_000_000)
    digest = report.pop("report_digest", None)
    if stable_digest(report) != digest:
        raise ValueError("report digest mismatch")
    return {"report_version": report.get("report_version"), "checksum_valid": True,
            "decision": report.get("decision"), "selection": report.get("selection"),
            "outcome": report.get("outcome"), "candidates": report.get("exploration"),
            "note": "Recorded summary only; use replay to reproduce the decision."}
