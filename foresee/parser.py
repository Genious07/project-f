from __future__ import annotations

from .model import (
    CompileFailure,
    DecisionDecl,
    Diagnostic,
    Expr,
    ModelDecl,
    Program,
    ResourceDecl,
    Span,
    Statement,
    Token,
)
from .signatures import RETURN_TYPE


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current()
        if token.kind != "EOF":
            self.index += 1
        return token

    def is_value(self, value: str) -> bool:
        return self.current().value == value

    def match(self, value: str) -> Token | None:
        if self.is_value(value):
            return self.advance()
        return None

    def fail(self, message: str, code: str = "F2001") -> None:
        raise CompileFailure([Diagnostic(code, message, self.current().span)])

    def expect(self, value: str) -> Token:
        if not self.is_value(value):
            self.fail(f"expected {value!r}, found {self.current().value!r}")
        return self.advance()

    def expect_kind(self, kind: str) -> Token:
        if self.current().kind != kind:
            self.fail(f"expected {kind.lower()}, found {self.current().value!r}")
        return self.advance()

    def parse(self) -> Program:
        resources: list[ResourceDecl] = []
        models: list[ModelDecl] = []
        decisions: list[DecisionDecl] = []
        while self.current().kind != "EOF":
            if self.is_value("resource"):
                start = self.advance().span
                name = self.expect_kind("IDENT")
                self.expect(":")
                type_name = self.expect_kind("IDENT")
                self.expect(";")
                resources.append(ResourceDecl(name.value, type_name.value, start))
            elif self.is_value("model"):
                start = self.advance().span
                name = self.expect_kind("IDENT")
                self.expect(":")
                type_name = self.expect_kind("IDENT")
                self.expect(";")
                models.append(ModelDecl(name.value, type_name.value, start))
            elif self.is_value("decision"):
                decisions.append(self.parse_decision())
            else:
                self.fail("expected resource, model, or decision declaration")
        return Program(tuple(resources), tuple(models), tuple(decisions))

    def parse_decision(self) -> DecisionDecl:
        start = self.expect("decision").span
        name = self.expect_kind("IDENT").value
        self.expect("(")
        self.expect(")")
        if self.match("->"):
            if not self.is_value(RETURN_TYPE):
                self.fail(f"only {RETURN_TYPE} returns are supported")
            self.advance()
        self.expect("!")
        self.expect("{")
        effects: list[tuple[str, str]] = []
        while not self.is_value("}"):
            kind = self.expect_kind("IDENT").value
            self.expect("(")
            target = self.expect_kind("IDENT").value
            self.expect(")")
            effects.append((kind, target))
            if not self.match(","):
                break
        self.expect("}")
        body = self.parse_block()
        return DecisionDecl(name, tuple(effects), tuple(body), start)

    def parse_block(self) -> list[Statement]:
        self.expect("{")
        statements: list[Statement] = []
        while not self.is_value("}"):
            if self.current().kind == "EOF":
                self.fail("unterminated block")
            statements.append(self.parse_statement())
        self.expect("}")
        return statements

    def parse_statement(self) -> Statement:
        start = self.current().span
        if self.match("let"):
            name = self.expect_kind("IDENT").value
            if self.match(":"):
                self.fail("let type annotations are not supported yet")
            self.expect("=")
            value = self.parse_expr()
            self.expect(";")
            return Statement("let", {"name": name, "value": value}, start)
        if self.match("return"):
            value = self.parse_expr()
            self.expect(";")
            return Statement("return", {"value": value}, start)
        if self.match("check"):
            condition = self.parse_expr()
            self.expect("else")
            message = self.expect_kind("STRING").value
            self.expect(";")
            return Statement("check", {"condition": condition, "message": message}, start)
        if self.match("measure"):
            name = self.expect_kind("IDENT").value
            self.expect(":")
            type_name = self.expect_kind("IDENT").value
            self.expect("=")
            value = self.parse_expr()
            self.expect(";")
            return Statement("measure", {"name": name, "type": type_name, "value": value}, start)
        self.fail("expected let, check, measure, or return statement")
        raise AssertionError("unreachable")

    def parse_expr(self) -> Expr:
        start = self.current().span
        if self.match("snapshot"):
            return Expr("snapshot", {"resource": self.expect_kind("IDENT").value}, start)
        if self.match("propose"):
            model = self.expect_kind("IDENT").value
            self.expect("<")
            plan_type = self.expect_kind("IDENT").value
            self.expect(">")
            args = self.parse_args()
            return Expr("propose", {"model": model, "plan_type": plan_type, "args": args}, start)
        if self.match("explore"):
            item = self.expect_kind("IDENT").value
            self.expect("in")
            plans = self.parse_expr()
            self.expect("from")
            base = self.parse_expr()
            body = self.parse_block()
            return Expr("explore", {"item": item, "plans": plans, "base": base, "body": body}, start)
        if self.match("simulate"):
            resource = self.expect_kind("IDENT").value
            self.expect(".")
            method = self.expect_kind("IDENT").value
            args = self.parse_args()
            return Expr("simulate", {"resource": resource, "method": method, "args": args}, start)
        if self.match("select"):
            trials = self.parse_expr()
            self.expect("minimize")
            metric = self.expect_kind("IDENT").value
            return Expr("select", {"trials": trials, "metric": metric}, start)
        if self.match("commit"):
            selected = self.parse_expr()
            self.expect("to")
            resource = self.expect_kind("IDENT").value
            return Expr("commit", {"selected": selected, "resource": resource}, start)
        if self.current().kind == "STRING":
            return Expr("string", {"value": self.advance().value}, start)
        if self.current().kind == "INT":
            return Expr("int", {"value": int(self.advance().value)}, start)
        if self.current().kind == "IDENT":
            name = self.advance().value
            if self.match("."):
                method = self.expect_kind("IDENT").value
                return Expr("call", {"target": name, "method": method, "args": self.parse_args()}, start)
            return Expr("var", {"name": name}, start)
        self.fail("expected expression")
        raise AssertionError("unreachable")

    def parse_args(self) -> tuple[Expr, ...]:
        self.expect("(")
        args: list[Expr] = []
        if not self.is_value(")"):
            while True:
                args.append(self.parse_expr())
                if not self.match(","):
                    break
        self.expect(")")
        return tuple(args)


def parse(tokens: list[Token]) -> Program:
    return Parser(tokens).parse()
