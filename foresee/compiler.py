from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .lexer import lex
from .model import Binding, CompileFailure, Diagnostic, Expr, Program, Span, Statement
from .parser import parse
from .signatures import (BRANCH_FORBIDDEN, EFFECTS, METHODS, MODEL_TYPE, PLAN_TYPE,
                         PROPOSE_ARGS, RESOURCE_TYPE, SIMULATE_ARGS, accepts)


def _expr_json(expr: Expr) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in expr.data.items():
        if isinstance(value, Expr):
            data[key] = _expr_json(value)
        elif isinstance(value, tuple) and (not value or isinstance(value[0], Expr)):
            data[key] = [_expr_json(item) for item in value]
        elif isinstance(value, (list, tuple)) and (not value or isinstance(value[0], Statement)):
            data[key] = [_statement_json(item) for item in value]
        else:
            data[key] = value
    return {"op": expr.kind, **data}


def _statement_json(statement: Statement) -> dict[str, Any]:
    data = {}
    for key, value in statement.data.items():
        data[key] = _expr_json(value) if isinstance(value, Expr) else value
    return {"statement": statement.kind, **data}


class Checker:
    def __init__(self, program: Program):
        self.program = program
        self.resources = {item.name for item in program.resources}
        self.models = {item.name for item in program.models}
        self.diagnostics: list[Diagnostic] = []

    def error(self, code: str, message: str, span: Span, note: str | None = None) -> None:
        self.diagnostics.append(Diagnostic(code, message, span, note))

    def check(self) -> None:
        if len(self.program.decisions) != 1 or len(self.program.resources) != 1 or len(self.program.models) != 1:
            self.error("F3200", "bootstrap requires exactly one resource, model, and decision", Span(0, 0, 1, 1))
        for item in self.program.resources:
            if item.type_name != RESOURCE_TYPE:
                self.error("F3201", "unsupported resource type", item.span)
        for item in self.program.models:
            if item.type_name != MODEL_TYPE:
                self.error("F3201", "unsupported model type", item.span)
        names = [item.name for item in (*self.program.resources, *self.program.models, *self.program.decisions)]
        if len(set(names)) != len(names):
            self.error("F3000", "top-level names must be unique", Span(0, 0, 1, 1))
        for decision in self.program.decisions:
            declared = set(decision.effects)
            for kind, target in declared:
                targets = self.models if EFFECTS.get(kind) == "model" else self.resources
                if kind not in EFFECTS or target not in targets:
                    self.error("F3202", f"invalid effect {kind}({target})", decision.span)
            returns = [i for i, s in enumerate(decision.body) if s.kind == "return"]
            if returns != [len(decision.body) - 1]:
                self.error("F3203", "decision must end with exactly one return", decision.span)
            env: dict[str, Binding] = {}
            used: set[tuple[str, str]] = set()
            for statement in decision.body:
                self.check_statement(statement, env, used, branch_resource=None)
            missing = used - declared
            for effect in sorted(missing):
                self.error("F3001", f"effect {effect[0]}({effect[1]}) is used but not declared", decision.span)
            unknown = {target for _, target in declared if target not in self.resources | self.models}
            for target in sorted(unknown):
                self.error("F3002", f"unknown effect target {target!r}", decision.span)
        if self.diagnostics:
            raise CompileFailure(self.diagnostics)

    def check_statement(
        self,
        statement: Statement,
        env: dict[str, Binding],
        used: set[tuple[str, str]],
        branch_resource: str | None,
    ) -> None:
        if statement.kind == "let":
            name = statement.data["name"]
            if name.startswith("__") or name in self.resources | self.models:
                self.error("F3204", "reserved binding name", statement.span)
            if name in env:
                self.error("F3003", f"binding {name!r} already exists", statement.span)
            env[name] = self.check_expr(statement.data["value"], env, used, branch_resource)
        elif statement.kind == "return":
            result = self.check_expr(statement.data["value"], env, used, branch_resource)
            if branch_resource is not None or result.kind != "outcome":
                self.error("F3203", "return requires a decision outcome outside exploration", statement.span)
        elif statement.kind in {"check", "measure"}:
            if branch_resource is None:
                self.error("F3100", f"{statement.kind} is only valid inside explore", statement.span)
            result = self.check_expr(statement.data.get("condition", statement.data.get("value")), env, used, branch_resource)
            expected = "bool" if statement.kind == "check" else "int"
            if result.kind != expected or (statement.kind == "measure" and statement.data["type"] != "Int"):
                self.error("F3205", f"{statement.kind} requires {expected}", statement.span)

    def arguments(self, expr, expected, env, used, branch_resource):
        args = [self.check_expr(arg, env, used, branch_resource) for arg in expr.data["args"]]
        if len(args) != len(expected) or any(not accepts(want, got.kind) for want, got in zip(expected, args)):
            self.error("F3206", f"expected arguments {expected}", expr.span)
        return args

    def check_expr(
        self,
        expr: Expr,
        env: dict[str, Binding],
        used: set[tuple[str, str]],
        branch_resource: str | None,
    ) -> Binding:
        kind = expr.kind
        if branch_resource is not None and kind in BRANCH_FORBIDDEN:
            self.error("F3102" if kind == "commit" else "F3207", f"{kind} is forbidden inside explore", expr.span)
        if kind in {"string", "int"}:
            return Binding(kind)
        if kind == "var":
            name = expr.data["name"]
            if name not in env:
                self.error("F3004", f"unknown binding {name!r}", expr.span)
                return Binding("error")
            return env[name]
        if kind == "snapshot":
            resource = expr.data["resource"]
            if resource not in self.resources:
                self.error("F3005", f"unknown resource {resource!r}", expr.span)
            used.add(("Snapshot", resource))
            return Binding("snapshot", resource)
        if kind == "propose":
            model = expr.data["model"]
            if model not in self.models:
                self.error("F3006", f"unknown model {model!r}", expr.span)
            used.add(("Infer", model))
            self.arguments(expr, PROPOSE_ARGS, env, used, branch_resource)
            args = expr.data["args"]
            if expr.data["plan_type"] != PLAN_TYPE:
                self.error("F3208", "only Patch proposals are supported", expr.span)
            if len(args) == 3 and (args[2].kind != "int" or not 1 <= args[2].data["value"] <= 4):
                self.error("F3208", "fixture proposal count must be a literal from 1 to 4", expr.span)
            return Binding("plans")
        if kind == "explore":
            plans = self.check_expr(expr.data["plans"], env, used, branch_resource)
            base = self.check_expr(expr.data["base"], env, used, branch_resource)
            resource = base.resource
            if plans.kind != "plans" or base.kind != "snapshot" or resource is None:
                self.error("F3101", "explore requires a plan set and a snapshot", expr.span)
                resource = "<error>"
            used.add(("Explore", resource))
            local = dict(env)
            if expr.data["item"] in local or expr.data["item"].startswith("__") or expr.data["item"] in self.resources | self.models:
                self.error("F3204", "exploration binding shadows an existing or reserved name", expr.span)
            local[expr.data["item"]] = Binding("plan", resource)
            metrics: list[str] = []
            for statement in expr.data["body"]:
                self.check_statement(statement, local, used, branch_resource=resource)
                if statement.kind == "measure":
                    if statement.data["name"] in metrics:
                        self.error("F3209", "duplicate metric name", statement.span)
                    metrics.append(statement.data["name"])
            return Binding("trials", resource, tuple(metrics))
        if kind == "simulate":
            resource = expr.data["resource"]
            if branch_resource is None:
                self.error("F3103", "simulate is only valid inside explore", expr.span)
            elif resource != branch_resource:
                self.error("F3104", "simulation resource must match the explore snapshot", expr.span)
            if expr.data["method"] != "apply" or resource not in self.resources:
                self.error("F3210", "simulate supports only a declared resource's apply method", expr.span)
            self.arguments(expr, SIMULATE_ARGS, env, used, branch_resource)
            return Binding("simulated", resource)
        if kind == "call":
            signature = METHODS.get(expr.data["method"])
            if signature is None or expr.data["target"] not in self.resources:
                self.error("F3210", "unknown resource method", expr.span)
                return Binding("error")
            self.arguments(expr, signature[0], env, used, branch_resource)
            return Binding(signature[1])
        if kind == "select":
            trials = self.check_expr(expr.data["trials"], env, used, branch_resource)
            metric = expr.data["metric"]
            if trials.kind != "trials":
                self.error("F3105", "select requires exploration trials", expr.span)
            elif metric not in trials.metric_names:
                self.error("F3106", f"metric {metric!r} is not measured by these trials", expr.span)
            return Binding("selected", trials.resource)
        if kind == "commit":
            resource = expr.data["resource"]
            if branch_resource is not None:
                self.error("F3102", "live commit is forbidden inside explore", expr.span)
            selected = self.check_expr(expr.data["selected"], env, used, branch_resource)
            if selected.kind != "selected" or selected.resource != resource:
                self.error("F3107", "commit requires Selected data for the same resource", expr.span)
            used.add(("Commit", resource))
            return Binding("outcome", resource)
        self.error("F3999", f"unsupported expression {kind}", expr.span)
        return Binding("error")


def compile_source(source: str, source_name: str = "<memory>") -> dict[str, Any]:
    del source_name
    program = parse(lex(source))
    Checker(program).check()
    ir: dict[str, Any] = {
        "schema_version": "0.0.1",
        "resources": [asdict(item) | {"span": asdict(item.span)} for item in program.resources],
        "models": [asdict(item) | {"span": asdict(item.span)} for item in program.models],
        "decisions": [
            {
                "name": item.name,
                "effects": [{"kind": kind, "target": target} for kind, target in item.effects],
                "body": [_statement_json(statement) for statement in item.body],
            }
            for item in program.decisions
        ],
    }
    canonical = json.dumps(ir, sort_keys=True, separators=(",", ":")).encode()
    ir["program_digest"] = hashlib.sha256(canonical).hexdigest()
    return ir
