from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import Catalog, Snapshot, fixture_plans, stable_digest


def snapshot_json(snapshot: Snapshot) -> dict[str, Any]:
    return {"revision": snapshot.revision, "rows": list(snapshot.rows), "digest": snapshot.digest}


def snapshot_from_json(value: dict[str, Any]) -> Snapshot:
    return Snapshot(value["revision"], tuple(value["rows"]), value["digest"])


class Runtime:
    def __init__(self, ir: dict[str, Any], catalog: Catalog, simulate_stale: bool = False):
        self.ir = ir
        self.catalog = catalog
        self.simulate_stale = simulate_stale
        self.exploration: list[dict[str, Any]] = []
        self.selection: dict[str, Any] | None = None

    def run(self) -> dict[str, Any]:
        decision = self.ir["decisions"][0]
        env: dict[str, Any] = {}
        outcome: dict[str, Any] | None = None
        for statement in decision["body"]:
            value = self.exec_statement(statement, env, branch=False)
            if statement["statement"] == "return":
                outcome = value
        report = {
            "report_version": "0.0.1",
            "program_digest": self.ir["program_digest"],
            "decision": decision["name"],
            "exploration": self.exploration,
            "selection": self.selection,
            "outcome": outcome,
        }
        report["report_digest"] = stable_digest(report)
        return report

    def exec_statement(self, statement: dict[str, Any], env: dict[str, Any], branch: bool) -> Any:
        kind = statement["statement"]
        if kind == "let":
            value = self.eval_expr(statement["value"], env, branch)
            env[statement["name"]] = value
            return value
        if kind == "return":
            return self.eval_expr(statement["value"], env, branch)
        if kind == "check":
            passed = bool(self.eval_expr(statement["condition"], env, branch))
            env.setdefault("__checks__", []).append({"passed": passed, "message": statement["message"]})
            return passed
        if kind == "measure":
            value = self.eval_expr(statement["value"], env, branch)
            env.setdefault("__metrics__", {})[statement["name"]] = value
            return value
        raise RuntimeError(f"unknown statement {kind}")

    def eval_expr(self, expr: dict[str, Any], env: dict[str, Any], branch: bool) -> Any:
        op = expr["op"]
        if op in {"string", "int"}:
            return expr["value"]
        if op == "var":
            return env[expr["name"]]
        if op == "snapshot":
            return self.catalog.snapshot()
        if op == "propose":
            args = [self.eval_expr(arg, env, branch) for arg in expr["args"]]
            base = args[0]
            limit = int(args[-1])
            return fixture_plans(base, limit)
        if op == "simulate":
            args = [self.eval_expr(arg, env, branch) for arg in expr["args"]]
            return Catalog.apply_to_snapshot(env.get("__base__"), args[0])
        if op == "call":
            args = [self.eval_expr(arg, env, branch) for arg in expr["args"]]
            method = getattr(Catalog, expr["method"])
            return method(*args)
        if op == "explore":
            plans = self.eval_expr(expr["plans"], env, branch)
            base = self.eval_expr(expr["base"], env, branch)
            trials: list[dict[str, Any]] = []
            for plan in plans:
                local = dict(env)
                local[expr["item"]] = plan
                local["__base__"] = base
                local["__checks__"] = []
                local["__metrics__"] = {}
                error = None
                try:
                    for statement in expr["body"]:
                        self.exec_statement(statement, local, branch=True)
                except Exception as exc:
                    error = str(exc)
                trial = {
                    "plan": plan,
                    "checks": local["__checks__"],
                    "metrics": local["__metrics__"],
                    "eligible": error is None and all(item["passed"] for item in local["__checks__"]),
                    "error": error,
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
                }
                for trial in trials
            ]
            return trials
        if op == "select":
            trials = self.eval_expr(expr["trials"], env, branch)
            eligible = [trial for trial in trials if trial["eligible"]]
            if not eligible:
                raise RuntimeError("no eligible candidate")
            chosen = min(eligible, key=lambda item: (item["metrics"][expr["metric"]], item["plan"]["id"]))
            selection = {"plan": chosen["plan"], "base": chosen["base"], "metric": expr["metric"], "score": chosen["metrics"][expr["metric"]]}
            self.selection = {"plan_id": chosen["plan"]["id"], "metric": expr["metric"], "score": selection["score"]}
            return selection
        if op == "commit":
            selected = self.eval_expr(expr["selected"], env, branch)
            if self.simulate_stale:
                self.catalog.mutate_for_stale_test()
                self.simulate_stale = False
            return self.catalog.commit(selected, self.ir["program_digest"])
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
