"""Decode Rust syntax output for the Python checker/lowering stage.

This is a development bridge for locally generated frontend output, not an
untrusted artifact loader. Rust does not yet implement semantic lowering.
"""
from .model import DecisionDecl, Expr, ModelDecl, Program, ResourceDecl, Span, Statement


def program_from_syntax(value):
    def expression(node):
        data = dict(node["data"])
        for key in ("plans", "base", "trials", "selected"):
            if key in data:
                data[key] = expression(data[key])
        if "args" in data:
            data["args"] = tuple(expression(arg) for arg in data["args"])
        if "body" in data:
            data["body"] = [statement(s) for s in data["body"]]
        return Expr(node["kind"], data, Span(**node["span"]))

    def statement(node):
        data = dict(node["data"])
        for key in ("value", "condition"):
            if key in data:
                data[key] = expression(data[key])
        return Statement(node["kind"], data, Span(**node["span"]))

    return Program(
        tuple(ResourceDecl(r["name"], r["type_name"], Span(**r["span"])) for r in value["resources"]),
        tuple(ModelDecl(m["name"], m["type_name"], Span(**m["span"])) for m in value["models"]),
        tuple(DecisionDecl(d["name"], tuple(tuple(e) for e in d["effects"]),
                           tuple(statement(s) for s in d["body"]), Span(**d["span"]))
              for d in value["decisions"]),
    )
