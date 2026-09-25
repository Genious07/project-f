"""Pure decision reproduction from recorded inputs, with no live adapter."""
import json
from copy import deepcopy

from .catalog import commit_identity, stable_digest
from .compiler import compile_source
from .model import CompileFailure
from .runtime import Runtime, snapshot_from_json


def source_from_ir(ir):
    """Round-trip through the checker before interpreting evidence-supplied IR."""
    def expr(node):
        op = node["op"]
        if op == "string":
            return json.dumps(node["value"], ensure_ascii=False)
        if op == "int":
            return str(node["value"])
        if op == "var":
            return node["name"]
        if op == "snapshot":
            return "snapshot " + node["resource"]
        if op in {"propose", "simulate", "call"}:
            args = "(" + ", ".join(expr(a) for a in node["args"]) + ")"
            if op == "propose":
                return f"propose {node['model']}<{node['plan_type']}>" + args
            target = node["resource"] if op == "simulate" else node["target"]
            return ("simulate " if op == "simulate" else "") + target + "." + node["method"] + args
        if op == "explore":
            return f"explore {node['item']} in {expr(node['plans'])} from {expr(node['base'])} " + block(node["body"])
        if op == "select":
            return f"select {expr(node['trials'])} minimize {node['metric']}"
        if op == "commit":
            return f"commit {expr(node['selected'])} to {node['resource']}"
        raise ValueError("unsupported evidence expression")

    def block(statements):
        lines = []
        for s in statements:
            kind = s["statement"]
            if kind == "let":
                lines.append(f"let {s['name']} = {expr(s['value'])};")
            elif kind == "return":
                lines.append(f"return {expr(s['value'])};")
            elif kind == "measure":
                lines.append(f"measure {s['name']}: {s['type']} = {expr(s['value'])};")
            elif kind == "check":
                lines.append(f"check {expr(s['condition'])} else {json.dumps(s['message'], ensure_ascii=False)};")
            else:
                raise ValueError("unsupported evidence statement")
        return "{\n" + "\n".join(lines) + "\n}"

    declarations = [f"resource {r['name']}: {r['type_name']};" for r in ir["resources"]]
    declarations += [f"model {m['name']}: {m['type_name']};" for m in ir["models"]]
    for d in ir["decisions"]:
        effects = ", ".join(f"{e['kind']}({e['target']})" for e in d["effects"])
        declarations.append(f"decision {d['name']}() ! {{ {effects} }} " + block(d["body"]))
    return "\n".join(declarations)


class OfflineRuntime(Runtime):
    def __init__(self, ir, events):
        super().__init__(ir, None)
        self.recorded = deepcopy(events)
        self.cursor = 0

    def expected(self, kind):
        if self.cursor >= len(self.recorded) or self.recorded[self.cursor]["kind"] != kind:
            raise ValueError(f"missing or out-of-order {kind} evidence")
        return self.recorded[self.cursor]["data"]

    def observe(self, kind, data):
        if stable_digest(data) != stable_digest(self.expected(kind)):
            raise ValueError(f"reproduced {kind} differs from recorded evidence")
        self.cursor += 1
        super().observe(kind, data)

    def read_snapshot(self, resource):
        data = self.expected("snapshot")
        value = data["snapshot"]
        if stable_digest({"revision": value["revision"], "rows": value["rows"]}) != value["digest"]:
            raise ValueError("snapshot content digest mismatch")
        return snapshot_from_json(value)

    def propose_plans(self, model, base, prompt, limit):
        return deepcopy(self.expected("proposal")["plans"])

    def apply_selection(self, payload):
        data = self.expected("commit")
        if stable_digest(data["payload"]) != stable_digest(payload):
            raise ValueError("commit payload differs from reproduced selection")
        outcome = data["outcome"]
        commit_id, _ = commit_identity(payload, self.ir["program_digest"], data["operation_id"])
        if (outcome["commit_id"] != commit_id or outcome["status"] not in {"applied", "stale"}
                or type(outcome["revision"]) is not int or outcome["revision"] < 0):
            raise ValueError("recorded receipt reference is inconsistent")
        if outcome["status"] == "applied" and outcome["revision"] != payload["base"]["revision"] + 1:
            raise ValueError("applied receipt revision is inconsistent")
        self.observe("commit", {"payload": payload, "operation_id": data["operation_id"], "outcome": outcome})
        return deepcopy(outcome)


def reproduce(report):
    if report.get("report_version") == "0.0.1":
        return False  # Explicit compatibility: old reports have checksums only.
    if report.get("report_version") != "0.0.2":
        raise ValueError("unsupported report version")
    try:
        evidence = report["evidence"]
        if evidence.get("redacted", False):
            raise ValueError("redacted evidence cannot reproduce a decision")
        if evidence["version"] != 1:
            raise ValueError("unsupported evidence version")
        ir = evidence["ir"]
        checked = compile_source(source_from_ir(ir))
        if stable_digest(checked) != stable_digest(ir) or checked["program_digest"] != report["program_digest"]:
            raise ValueError("program identity or typed IR mismatch")
        runtime = OfflineRuntime(checked, evidence["events"])
        result = runtime.run()
        if runtime.cursor != len(evidence["events"]):
            raise ValueError("unexpected trailing evidence")
        for field in ("decision", "exploration", "selection", "outcome"):
            if stable_digest(result[field]) != stable_digest(report[field]):
                raise ValueError(f"reproduced {field} differs from report")
        return True
    except (KeyError, TypeError, IndexError, CompileFailure, RuntimeError) as error:
        raise ValueError(f"incomplete or invalid execution evidence: {error}") from error
