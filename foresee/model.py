from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    span: Span


@dataclass(frozen=True)
class ResourceDecl:
    name: str
    type_name: str
    span: Span


@dataclass(frozen=True)
class ModelDecl:
    name: str
    type_name: str
    span: Span


@dataclass(frozen=True)
class Expr:
    kind: str
    data: dict[str, Any]
    span: Span


@dataclass(frozen=True)
class Statement:
    kind: str
    data: dict[str, Any]
    span: Span


@dataclass(frozen=True)
class DecisionDecl:
    name: str
    effects: tuple[tuple[str, str], ...]
    body: tuple[Statement, ...]
    span: Span


@dataclass(frozen=True)
class Program:
    resources: tuple[ResourceDecl, ...]
    models: tuple[ModelDecl, ...]
    decisions: tuple[DecisionDecl, ...]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    span: Span
    note: str | None = None

    def render(self, source_name: str) -> str:
        at = f"{source_name}:{self.span.line}:{self.span.column}"
        suffix = f"\n  note: {self.note}" if self.note else ""
        return f"{self.code}: {self.message}\n  --> {at}{suffix}"


class CompileFailure(Exception):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("compilation failed")


@dataclass
class Binding:
    kind: str
    resource: str | None = None
    metric_names: tuple[str, ...] = field(default_factory=tuple)
