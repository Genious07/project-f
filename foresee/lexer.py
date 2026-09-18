from __future__ import annotations

from .model import CompileFailure, Diagnostic, Span, Token


PUNCT = set("{}();,:.<>[]!+-*/%")
DOUBLE = {"->", "==", "!=", "<=", ">=", "&&", "||", "=>"}


def lex(source: str) -> list[Token]:
    tokens: list[Token] = []
    diagnostics: list[Diagnostic] = []
    i = 0
    line = 1
    column = 1

    def make_span(start: int, start_line: int, start_column: int) -> Span:
        return Span(start, i, start_line, start_column)

    while i < len(source):
        ch = source[i]
        if ch in " \t\r":
            i += 1
            column += 1
            continue
        if ch == "\n":
            i += 1
            line += 1
            column = 1
            continue
        if source.startswith("//", i):
            while i < len(source) and source[i] != "\n":
                i += 1
                column += 1
            continue
        start, start_line, start_column = i, line, column
        pair = source[i : i + 2]
        if pair in DOUBLE:
            i += 2
            column += 2
            tokens.append(Token(pair, pair, make_span(start, start_line, start_column)))
            continue
        if ch.isalpha() or ch == "_":
            i += 1
            column += 1
            while i < len(source) and (source[i].isalnum() or source[i] == "_"):
                i += 1
                column += 1
            tokens.append(Token("IDENT", source[start:i], make_span(start, start_line, start_column)))
            continue
        if ch.isdigit():
            i += 1
            column += 1
            while i < len(source) and source[i].isdigit():
                i += 1
                column += 1
            tokens.append(Token("INT", source[start:i], make_span(start, start_line, start_column)))
            continue
        if ch == '"':
            i += 1
            column += 1
            chars: list[str] = []
            closed = False
            while i < len(source):
                current = source[i]
                if current == '"':
                    i += 1
                    column += 1
                    closed = True
                    break
                if current == "\n":
                    break
                if current == "\\":
                    i += 1
                    column += 1
                    if i >= len(source):
                        break
                    escaped = source[i]
                    mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
                    if escaped not in mapping:
                        diagnostics.append(Diagnostic("F1003", f"unsupported escape \\{escaped}", make_span(start, start_line, start_column)))
                        i += 1
                        column += 1
                        continue
                    chars.append(mapping[escaped])
                    i += 1
                    column += 1
                    continue
                chars.append(current)
                i += 1
                column += 1
            if not closed:
                diagnostics.append(Diagnostic("F1002", "unterminated string", make_span(start, start_line, start_column)))
            else:
                tokens.append(Token("STRING", "".join(chars), make_span(start, start_line, start_column)))
            continue
        if ch in PUNCT or ch == "=":
            i += 1
            column += 1
            tokens.append(Token(ch, ch, make_span(start, start_line, start_column)))
            continue
        i += 1
        column += 1
        diagnostics.append(Diagnostic("F1001", f"unexpected character {ch!r}", make_span(start, start_line, start_column)))

    tokens.append(Token("EOF", "", Span(len(source), len(source), line, column)))
    if diagnostics:
        raise CompileFailure(diagnostics)
    return tokens
