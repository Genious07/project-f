//! Syntax-only frontend. Type/effect/ownership checking remains in Python.
use serde::Serialize;
use serde_json::{json, Value};

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
    pub line: usize,
    pub column: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct Token {
    pub kind: String,
    pub value: String,
    pub span: Span,
}

#[derive(Clone, Debug, Serialize)]
pub struct Diagnostic {
    pub code: String,
    pub message: String,
    pub span: Span,
}

fn diagnostic(code: &str, message: &str, span: Span) -> Diagnostic {
    Diagnostic {
        code: code.into(),
        message: message.into(),
        span,
    }
}

pub fn lex(source: &str) -> Result<Vec<Token>, Vec<Diagnostic>> {
    let chars: Vec<char> = source.chars().collect();
    let (mut i, mut line, mut column) = (0, 1, 1);
    let mut tokens = Vec::new();
    let mut errors = Vec::new();
    while i < chars.len() {
        let ch = chars[i];
        if " \t\r".contains(ch) {
            i += 1;
            column += 1;
            continue;
        }
        if ch == '\n' {
            i += 1;
            line += 1;
            column = 1;
            continue;
        }
        if ch == '/' && chars.get(i + 1) == Some(&'/') {
            while i < chars.len() && chars[i] != '\n' {
                i += 1;
                column += 1;
            }
            continue;
        }
        let (start, start_line, start_column) = (i, line, column);
        let span = |end| Span {
            start,
            end,
            line: start_line,
            column: start_column,
        };
        let pair: String = chars[i..(i + 2).min(chars.len())].iter().collect();
        let (kind, value);
        if ["->", "==", "!=", "<=", ">=", "&&", "||", "=>"].contains(&pair.as_str()) {
            i += 2;
            column += 2;
            kind = pair.clone();
            value = pair;
        } else if ch.is_ascii_alphabetic() || ch == '_' {
            i += 1;
            column += 1;
            while i < chars.len() && (chars[i].is_ascii_alphanumeric() || chars[i] == '_') {
                i += 1;
                column += 1;
            }
            kind = "IDENT".into();
            value = chars[start..i].iter().collect();
        } else if ch.is_ascii_digit() {
            i += 1;
            column += 1;
            while i < chars.len() && chars[i].is_ascii_digit() {
                i += 1;
                column += 1;
            }
            kind = "INT".into();
            value = chars[start..i].iter().collect();
        } else if ch == '"' {
            i += 1;
            column += 1;
            let mut text = String::new();
            let mut closed = false;
            while i < chars.len() {
                let current = chars[i];
                if current == '"' {
                    i += 1;
                    column += 1;
                    closed = true;
                    break;
                }
                if current == '\n' {
                    break;
                }
                if current == '\\' {
                    i += 1;
                    column += 1;
                    if i == chars.len() {
                        break;
                    }
                    match chars[i] {
                        'n' => text.push('\n'),
                        'r' => text.push('\r'),
                        't' => text.push('\t'),
                        '"' => text.push('"'),
                        '\\' => text.push('\\'),
                        _ => errors.push(diagnostic("F1003", "unsupported string escape", span(i))),
                    }
                } else {
                    text.push(current);
                }
                i += 1;
                column += 1;
            }
            if !closed {
                errors.push(diagnostic("F1002", "unterminated string", span(i)));
            }
            kind = "STRING".into();
            value = text;
        } else if "{}();,:.<>[]!+-*/%=".contains(ch) {
            i += 1;
            column += 1;
            kind = ch.to_string();
            value = kind.clone();
        } else {
            i += 1;
            column += 1;
            errors.push(diagnostic(if ch.is_ascii() { "F1001" } else { "F1004" },
                "unexpected character (identifiers and numeric literals are ASCII in this frontend)", span(i)));
            continue;
        }
        tokens.push(Token {
            kind,
            value,
            span: span(i),
        });
    }
    tokens.push(Token {
        kind: "EOF".into(),
        value: String::new(),
        span: Span {
            start: i,
            end: i,
            line,
            column,
        },
    });
    if errors.is_empty() {
        Ok(tokens)
    } else {
        Err(errors)
    }
}

struct Parser {
    tokens: Vec<Token>,
    index: usize,
    depth: usize,
}
type Parsed = Result<Value, Diagnostic>;

impl Parser {
    fn current(&self) -> &Token {
        &self.tokens[self.index]
    }
    fn error(&self, message: &str) -> Diagnostic {
        diagnostic("F2001", message, self.current().span.clone())
    }
    fn take(&mut self) -> Token {
        let token = self.current().clone();
        if token.kind != "EOF" {
            self.index += 1;
        }
        token
    }
    fn eat(&mut self, value: &str) -> bool {
        if self.current().value == value {
            self.take();
            true
        } else {
            false
        }
    }
    fn expect(&mut self, value: &str) -> Result<(), Diagnostic> {
        if self.eat(value) {
            Ok(())
        } else {
            Err(self.error(&format!("expected {value}")))
        }
    }
    fn token(&mut self, kind: &str) -> Result<Token, Diagnostic> {
        if self.current().kind == kind {
            Ok(self.take())
        } else {
            Err(self.error(&format!("expected {kind}")))
        }
    }
    fn name(&mut self) -> Result<String, Diagnostic> {
        Ok(self.token("IDENT")?.value)
    }
    fn program(&mut self) -> Parsed {
        let (mut resources, mut models, mut decisions) = (Vec::new(), Vec::new(), Vec::new());
        while self.current().kind != "EOF" {
            let span = self.current().span.clone();
            if self.current().value == "resource" || self.current().value == "model" {
                let kind = self.take().value;
                let name = self.name()?;
                self.expect(":")?;
                let ty = self.name()?;
                self.expect(";")?;
                let decl = json!({"name": name, "type_name": ty, "span": span});
                if kind == "resource" {
                    resources.push(decl);
                } else {
                    models.push(decl);
                }
            } else if self.eat("decision") {
                let name = self.name()?;
                self.expect("(")?;
                self.expect(")")?;
                if self.eat("->") {
                    self.expect("DecisionResult")?;
                }
                self.expect("!")?;
                self.expect("{")?;
                let mut effects = Vec::new();
                while self.current().value != "}" {
                    let kind = self.name()?;
                    self.expect("(")?;
                    let target = self.name()?;
                    self.expect(")")?;
                    effects.push(json!([kind, target]));
                    if !self.eat(",") {
                        break;
                    }
                }
                self.expect("}")?;
                let body = self.block()?;
                decisions
                    .push(json!({"name": name, "effects": effects, "body": body, "span": span}));
            } else {
                return Err(self.error("expected resource, model, or decision"));
            }
        }
        Ok(json!({"resources": resources, "models": models, "decisions": decisions}))
    }
    fn block(&mut self) -> Parsed {
        self.expect("{")?;
        let mut statements = Vec::new();
        while !self.eat("}") {
            if self.current().kind == "EOF" {
                return Err(self.error("unterminated block"));
            }
            statements.push(self.statement()?);
        }
        Ok(json!(statements))
    }
    fn statement(&mut self) -> Parsed {
        let span = self.current().span.clone();
        let (kind, data);
        if self.eat("let") {
            kind = "let";
            let name = self.name()?;
            let mut annotation = Value::Null;
            if self.eat(":") {
                let ty = self.name()?;
                let resource = if self.eat("<") {
                    let r = self.name()?;
                    self.expect(">")?;
                    json!(r)
                } else {
                    Value::Null
                };
                annotation = json!({"name": ty, "resource": resource});
            }
            self.expect("=")?;
            data = json!({"name": name, "annotation": annotation, "value": self.expr()?});
        } else if self.eat("return") {
            kind = "return";
            data = json!({"value": self.expr()?});
        } else if self.eat("check") {
            kind = "check";
            let condition = self.expr()?;
            self.expect("else")?;
            data = json!({"condition": condition, "message": self.token("STRING")?.value});
        } else if self.eat("measure") {
            kind = "measure";
            let name = self.name()?;
            self.expect(":")?;
            let ty = self.name()?;
            self.expect("=")?;
            data = json!({"name": name, "type": ty, "value": self.expr()?});
        } else {
            return Err(self.error("expected statement"));
        }
        self.expect(";")?;
        Ok(json!({"kind": kind, "data": data, "span": span}))
    }
    fn args(&mut self) -> Parsed {
        self.expect("(")?;
        let mut args = Vec::new();
        if self.current().value != ")" {
            loop {
                args.push(self.expr()?);
                if !self.eat(",") {
                    break;
                }
            }
        }
        self.expect(")")?;
        Ok(json!(args))
    }
    fn expr(&mut self) -> Parsed {
        if self.depth >= 128 {
            return Err(diagnostic(
                "F2002",
                "expression nesting limit exceeded",
                self.current().span.clone(),
            ));
        }
        self.depth += 1;
        let result = self.expr_inner();
        self.depth -= 1;
        result
    }
    fn expr_inner(&mut self) -> Parsed {
        let span = self.current().span.clone();
        let (kind, data);
        if self.eat("snapshot") {
            kind = "snapshot";
            data = json!({"resource": self.name()?});
        } else if self.eat("propose") {
            kind = "propose";
            let model = self.name()?;
            self.expect("<")?;
            let ty = self.name()?;
            self.expect(">")?;
            data = json!({"model": model, "plan_type": ty, "args": self.args()?});
        } else if self.eat("explore") {
            kind = "explore";
            let item = self.name()?;
            self.expect("in")?;
            let plans = self.expr()?;
            self.expect("from")?;
            let base = self.expr()?;
            data = json!({"item": item, "plans": plans, "base": base, "body": self.block()?});
        } else if self.eat("simulate") {
            kind = "simulate";
            let resource = self.name()?;
            self.expect(".")?;
            let method = self.name()?;
            data = json!({"resource": resource, "method": method, "args": self.args()?});
        } else if self.eat("select") {
            kind = "select";
            let trials = self.expr()?;
            self.expect("minimize")?;
            data = json!({"trials": trials, "metric": self.name()?});
        } else if self.eat("commit") {
            kind = "commit";
            let selected = self.expr()?;
            self.expect("to")?;
            data = json!({"selected": selected, "resource": self.name()?});
        } else if self.current().kind == "STRING" {
            kind = "string";
            data = json!({"value": self.take().value});
        } else if self.current().kind == "INT" {
            kind = "int";
            let token = self.take();
            let digits = token.value.trim_start_matches('0');
            let number: serde_json::Number = if digits.is_empty() { "0" } else { digits }
                .parse()
                .map_err(|_| self.error("invalid integer"))?;
            data = json!({"value": number});
        } else if self.current().kind == "IDENT" {
            let name = self.name()?;
            if self.eat(".") {
                kind = "call";
                let method = self.name()?;
                data = json!({"target": name, "method": method, "args": self.args()?});
            } else {
                kind = "var";
                data = json!({"name": name});
            }
        } else {
            return Err(self.error("expected expression"));
        }
        Ok(json!({"kind": kind, "data": data, "span": span}))
    }
}

pub fn parse(source: &str) -> Result<Value, Vec<Diagnostic>> {
    let tokens = lex(source)?;
    Parser {
        tokens,
        index: 0,
        depth: 0,
    }
    .program()
    .map_err(|e| vec![e])
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unicode_string_spans_are_character_offsets() {
        let tokens = lex("\"茶\"\nabc").unwrap();
        assert_eq!(
            tokens[1].span,
            Span {
                start: 4,
                end: 7,
                line: 2,
                column: 1
            }
        );
    }
    #[test]
    fn malformed_syntax_has_a_location() {
        let errors = parse("resource x Catalog;").unwrap_err();
        assert_eq!(errors[0].code, "F2001");
        assert_eq!(errors[0].span.column, 12);
    }
    #[test]
    fn rejects_unsupported_identifier_characters() {
        assert_eq!(lex("resource café: Catalog;").unwrap_err()[0].code, "F1004");
    }
    #[test]
    fn protects_expression_stack() {
        let source = format!(
            "decision x() ! {{}} {{ return {}x{}; }}",
            "select ".repeat(140),
            " minimize m".repeat(140)
        );
        assert_eq!(parse(&source).unwrap_err()[0].code, "F2002");
    }
}
