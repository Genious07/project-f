from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .catalog import Catalog, Snapshot, fixture_plans, stable_digest
from .signatures import BRANCH_FORBIDDEN, METHODS


CATALOG_METHODS = {
    "source_fields_unchanged": Catalog.source_fields_unchanged,
    "valid_unit_arithmetic": Catalog.valid_unit_arithmetic,
    "unresolved_units": Catalog.unresolved_units,
}


def snapshot_json(snapshot: Snapshot) -> dict[str, Any]:
    return {"revision": snapshot.revision, "rows": [dict(row) for row in snapshot.rows], "digest": snapshot.digest}


class DecisionStop(Exception):
    def __init__(self, status, detail):
        self.outcome = {"status": status, "detail": detail}


class Selected:
    """Opaque identity. Only the issuing runtime owns the commit payload."""
    __slots__ = ()


class TrialSet:
    """Opaque identity for a completed exploration."""
    __slots__ = ()


def snapshot_from_json(value: dict[str, Any]) -> Snapshot:
    return Snapshot(value["revision"], tuple(value["rows"]), value["digest"])


class Runtime:
    def __init__(self, ir: dict[str, Any], catalog: Catalog, simulate_stale: bool = False, *, journal=None, fault_hook=None):
        if ir.get("schema_version") != "0.0.3":
            raise RuntimeError("unsupported IR schema; rebuild source with the current compiler")
        self.ir = ir
        self.catalog = catalog
        self.simulate_stale = simulate_stale
        self.exploration: list[dict[str, Any]] = []
        self.selection: dict[str, Any] | None = None
        self._selections: dict[Selected, tuple[str, dict]] = {}
        self._trials: dict[TrialSet, list] = {}
        self.journal = journal
        self.run_id = None
        self.fault_hook = fault_hook
        self._ran = False

    def run(self) -> dict[str, Any]:
        if self._ran:
            raise RuntimeError("create a new runtime for each run")
        self._ran = True
        if self.journal:
            self.run_id = self.journal.start()
        if len(self.ir["decisions"]) != 1:
            raise RuntimeError("runtime requires exactly one decision")
        decision = self.ir["decisions"][0]
        env: dict[str, Any] = {}
        outcome: dict[str, Any] | None = None
        for statement in decision["body"]:
            try:
                value = self.exec_statement(statement, env, branch=False)
            except DecisionStop as stop:
                outcome = stop.outcome
                break
            if statement["statement"] == "return":
                outcome = value
                break
        report = {
            "report_version": "0.0.1",
            "program_digest": self.ir["program_digest"],
            "decision": decision["name"],
            "exploration": self.exploration,
            "selection": self.selection,
            "outcome": outcome,
        }
        if self.journal:
            self.journal.complete(self.run_id, outcome)
            report["run_id"] = self.run_id
            report["journal"] = str(self.journal.path)
        report["report_digest"] = stable_digest(report)
        return report

    def exec_statement(self, statement: dict[str, Any], env: dict[str, Any], branch: bool) -> Any:
        kind = statement["statement"]
        if branch and kind == "return":
            raise RuntimeError("return is forbidden inside explore")
        if not branch and kind in {"check", "measure"}:
            raise RuntimeError(f"{kind} requires exploration")
        if kind == "let":
            value = self.eval_expr(statement["value"], env, branch)
            env[statement["name"]] = value
            return value
        if kind == "return":
            return self.eval_expr(statement["value"], env, branch)
        if kind == "check":
            passed = self.eval_expr(statement["condition"], env, branch)
            if type(passed) is not bool:
                raise RuntimeError("check requires a Boolean")
            env.setdefault("__checks__", []).append({"passed": passed, "message": statement["message"]})
            return passed
        if kind == "measure":
            value = self.eval_expr(statement["value"], env, branch)
            if type(value) is not int:
                raise RuntimeError("measure requires an integer")
            env.setdefault("__metrics__", {})[statement["name"]] = value
            return value
        raise RuntimeError(f"unknown statement {kind}")

    def eval_expr(self, expr: dict[str, Any], env: dict[str, Any], branch: bool) -> Any:
        op = expr["op"]
        if branch and op in BRANCH_FORBIDDEN:
            raise RuntimeError(f"{op} is forbidden inside explore")
        if op in {"string", "int"}:
            return expr["value"]
        if op == "var":
            return env[expr["name"]]
        if op == "snapshot":
            return self.catalog.snapshot()
        if op == "propose":
            args = [self.eval_expr(arg, env, branch) for arg in expr["args"]]
            if len(args) != 3 or not isinstance(args[0], Snapshot) or not isinstance(args[1], str) or type(args[2]) is not int or not 1 <= args[2] <= 4:
                raise RuntimeError("invalid fixture proposal arguments")
            base = args[0]
            limit = args[2]
            return fixture_plans(base, limit)
        if op == "simulate":
            if not branch or expr["method"] != "apply":
                raise RuntimeError("simulate requires explore and the apply method")
            args = [self.eval_expr(arg, env, branch) for arg in expr["args"]]
            env["__simulations__"] = env.get("__simulations__", 0) + 1
            if env["__simulations__"] != 1:
                raise RuntimeError("only one simulation is permitted per branch")
            return Catalog.apply_to_snapshot(env.get("__base__"), args[0])
        if op == "call":
            name = expr["method"]
            if name not in CATALOG_METHODS or expr["target"] not in {r["name"] for r in self.ir["resources"]}:
                raise RuntimeError("unknown resource method")
            args = [self.eval_expr(arg, env, branch) for arg in expr["args"]]
            if len(args) != len(METHODS[name][0]) or not all(isinstance(arg, Snapshot) for arg in args):
                raise RuntimeError("invalid resource method arguments")
            return CATALOG_METHODS[name](*args)
        if op == "explore":
            plans = deepcopy(self.eval_expr(expr["plans"], env, branch))
            base = self.eval_expr(expr["base"], env, branch)
            if not isinstance(plans, list) or any(not isinstance(p, dict) or not isinstance(p.get("id"), str) or not isinstance(p.get("patches"), list) for p in plans):
                raise DecisionStop("invalid_plans", "candidate set has invalid structure")
            if len({p["id"] for p in plans}) != len(plans):
                raise DecisionStop("invalid_plans", "candidate IDs must be unique")
            trials: list[dict[str, Any]] = []
            for plan in plans:
                local = deepcopy(env)
                local[expr["item"]] = deepcopy(plan)
                local["__base__"] = base
                local["__checks__"] = []
                local["__metrics__"] = {}
                local["__simulations__"] = 0
                error = None
                try:
                    for statement in expr["body"]:
                        self.exec_statement(statement, local, branch=True)
                    if local["__simulations__"] != 1:
                        raise RuntimeError("branch must execute one simulation")
                except Exception as exc:
                    error = str(exc)
                trial = {
                    "plan": plan,
                    "checks": local["__checks__"],
                    "metrics": local["__metrics__"],
                    "eligible": error is None and all(item["passed"] for item in local["__checks__"]),
                    "error": error,
                    "status": "evaluation_failed" if error else ("eligible" if all(c["passed"] for c in local["__checks__"]) else "rejected"),
                    "base": snapshot_json(base),
                }
                trials.append(trial)
            self.exploration = [
                {
                    "plan_id": trial["plan"]["id"],
                    "eligible": trial["eligible"],
                    "checks": trial["checks"],
                    "metrics": trial["metrics"],
                    "error": trial["error"],
                    "status": trial["status"],
                }
                for trial in trials
            ]
            token = TrialSet()
            self._trials[token] = trials
            return token
        if op == "select":
            token = self.eval_expr(expr["trials"], env, branch)
            if type(token) is not TrialSet or token not in self._trials:
                raise RuntimeError("selection requires a completed exploration from this runtime")
            trials = self._trials[token]
            eligible = [trial for trial in trials if trial["eligible"]]
            if not eligible:
                raise DecisionStop("no_eligible_candidate", "complete exploration produced no eligible candidate")
            chosen = min(eligible, key=lambda item: (item["metrics"][expr["metric"]], item["plan"]["id"]))
            selection = {"plan": chosen["plan"], "base": chosen["base"], "metric": expr["metric"], "score": chosen["metrics"][expr["metric"]]}
            self.selection = {"plan_id": chosen["plan"]["id"], "metric": expr["metric"], "score": selection["score"]}
            capability = Selected()
            self._selections[capability] = (self.ir["resources"][0]["name"], deepcopy(selection))
            return capability
        if op == "commit":
            selected = self.eval_expr(expr["selected"], env, branch)
            if type(selected) is not Selected or selected not in self._selections:
                raise RuntimeError("selection is forged, foreign, or already consumed")
            resource, payload = self._selections[selected]
            if resource != expr["resource"]:
                raise RuntimeError("selection belongs to a different resource")
            del self._selections[selected]
            operation_id = None
            if self.journal:
                if self.run_id is None:
                    raise RuntimeError("journaled operations require run()")
                operation_id = self.journal.prepare(self.run_id, self.catalog, self.ir["program_digest"], payload)
            if self.simulate_stale:
                self.catalog.mutate_for_stale_test()
                self.simulate_stale = False
            outcome = self.catalog.commit(payload, self.ir["program_digest"], operation_id=operation_id, fault_hook=self.fault_hook)
            if self.journal:
                self.journal.record(operation_id, outcome)
            return outcome
        raise RuntimeError(f"unknown expression {op}")


def save_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def replay_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    claimed = report.pop("report_digest", None)
    actual = stable_digest(report)
    if claimed != actual:
        raise ValueError("report digest mismatch")
    return {
        "verified": True,
        "report_digest": claimed,
        "program_digest": report["program_digest"],
        "decision": report["decision"],
        "selected_plan": (report.get("selection") or {}).get("plan_id"),
        "outcome": report.get("outcome"),
        "live_calls": 0,
    }
