from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .lexer import lex
from .model import Binding, CompileFailure, Diagnostic, Expr, Program, Span, Statement
from .parser import parse


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
        names = [item.name for item in (*self.program.resources, *self.program.models, *self.program.decisions)]
        if len(set(names)) != len(names):
            self.error("F3000", "top-level names must be unique", Span(0, 0, 1, 1))
        for decision in self.program.decisions:
            declared = set(decision.effects)
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
            if name in env:
                self.error("F3003", f"binding {name!r} already exists", statement.span)
            env[name] = self.check_expr(statement.data["value"], env, used, branch_resource)
        elif statement.kind == "return":
            self.check_expr(statement.data["value"], env, used, branch_resource)
        elif statement.kind in {"check", "measure"}:
            if branch_resource is None:
                self.error("F3100", f"{statement.kind} is only valid inside explore", statement.span)
            self.check_expr(statement.data.get("condition", statement.data.get("value")), env, used, branch_resource)

    def check_expr(
        self,
        expr: Expr,
        env: dict[str, Binding],
        used: set[tuple[str, str]],
        branch_resource: str | None,
    ) -> Binding:
        kind = expr.kind
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
            for arg in expr.data["args"]:
                self.check_expr(arg, env, used, branch_resource)
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
            local[expr.data["item"]] = Binding("plan", resource)
            metrics: list[str] = []
            for statement in expr.data["body"]:
                self.check_statement(statement, local, used, branch_resource=resource)
                if statement.kind == "measure":
                    metrics.append(statement.data["name"])
            return Binding("trials", resource, tuple(metrics))
        if kind == "simulate":
            resource = expr.data["resource"]
            if branch_resource is None:
                self.error("F3103", "simulate is only valid inside explore", expr.span)
            elif resource != branch_resource:
                self.error("F3104", "simulation resource must match the explore snapshot", expr.span)
            for arg in expr.data["args"]:
                self.check_expr(arg, env, used, branch_resource)
            return Binding("simulated", resource)
        if kind == "call":
            for arg in expr.data["args"]:
                self.check_expr(arg, env, used, branch_resource)
            return Binding("value")
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
