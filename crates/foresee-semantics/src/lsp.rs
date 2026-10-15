//! Minimal synchronous LSP 3.17 server. Documents are client-owned, never read from disk.
use foresee_semantics::{check_ownership, DeclarationFailure};
use foresee_syntax::{limits::MAX_SOURCE_BYTES, Span};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{self, BufRead, Write},
};
const MAX_FRAME: usize = 8_000_000;
const MAX_HEADER: usize = 8192;
const MAX_DOCUMENTS: usize = 16;

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
fn read_frame(input: &mut impl BufRead) -> io::Result<Option<Result<Value, serde_json::Error>>> {
    let mut header = Vec::new();
    loop {
        let mut byte = [0];
        if input.read(&mut byte)? == 0 {
            return if header.is_empty() {
                Ok(None)
            } else {
                Err(invalid("truncated header"))
            };
        }
        header.push(byte[0]);
        if header.len() > MAX_HEADER {
            return Err(invalid("header limit exceeded"));
        }
        if header.ends_with(b"\r\n\r\n") {
            break;
        }
    }
    let header = std::str::from_utf8(&header).map_err(|_| invalid("invalid header"))?;
    let mut length = None;
    for line in header.split("\r\n").filter(|line| !line.is_empty()) {
        let (key, value) = line
            .split_once(':')
            .ok_or_else(|| invalid("malformed header"))?;
        if key.eq_ignore_ascii_case("Content-Length") {
            if length.is_some() {
                return Err(invalid("duplicate Content-Length"));
            }
            let value = value.trim();
            if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
                return Err(invalid("invalid Content-Length"));
            }
            length = Some(
                value
                    .parse::<usize>()
                    .map_err(|_| invalid("invalid Content-Length"))?,
            );
        }
    }
    let length = length.ok_or_else(|| invalid("missing Content-Length"))?;
    if length > MAX_FRAME {
        return Err(invalid("frame limit exceeded"));
    }
    let mut body = vec![0; length];
    input.read_exact(&mut body)?;
    // Invalid JSON is recoverable because the frame boundary is known.
    Ok(Some(serde_json::from_slice(&body)))
}
fn write_frame(output: &mut impl Write, value: &Value) -> io::Result<()> {
    let bytes = serde_json::to_vec(value)?;
    write!(output, "Content-Length: {}\r\n\r\n", bytes.len())?;
    output.write_all(&bytes)?;
    output.flush()
}
fn response(id: &Value, result: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":result})
}
fn error(id: &Value, code: i32, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}
fn log(message: &str) -> Value {
    json!({"jsonrpc":"2.0","method":"window/logMessage","params":{"type":1,"message":message}})
}
fn publish(uri: &str, version: Option<i64>, diagnostics: Vec<Value>) -> Value {
    let mut params = json!({"uri":uri,"diagnostics":diagnostics});
    if let Some(version) = version {
        params["version"] = json!(version);
    }
    json!({"jsonrpc":"2.0","method":"textDocument/publishDiagnostics","params":params})
}
// Compiler offsets count Unicode scalars; LSP positions count UTF-16 code units.
fn position(text: &str, offset: usize) -> Value {
    let (mut line, mut character, mut previous_cr) = (0, 0, false);
    for ch in text.chars().take(offset) {
        match ch {
            '\r' => {
                line += 1;
                character = 0;
            }
            '\n' => {
                if !previous_cr {
                    line += 1;
                }
                character = 0;
            }
            _ => character += ch.len_utf16(),
        }
        previous_cr = ch == '\r';
    }
    json!({"line":line,"character":character})
}
fn offset(text: &str, pos: &Value) -> Option<usize> {
    let target_line = usize::try_from(pos.get("line")?.as_u64()?).ok()?;
    let target_char = usize::try_from(pos.get("character")?.as_u64()?).ok()?;
    let (mut line, mut character, mut index) = (0, 0, 0);
    let mut chars = text.chars().peekable();
    while let Some(ch) = chars.next() {
        if line == target_line && character == target_char {
            return Some(index);
        }
        if ch == '\n' || ch == '\r' {
            if line == target_line {
                return None;
            }
            if ch == '\r' && chars.peek() == Some(&'\n') {
                chars.next();
                index += 1;
            }
            line += 1;
            character = 0;
        } else {
            character += ch.len_utf16();
        }
        index += 1;
    }
    (line == target_line && character == target_char).then_some(index)
}

fn range(text: &str, span: &Span) -> Value {
    json!({"start":position(text,span.start),"end":position(text,span.end)})
}
fn limit_diagnostic(message: &str) -> Value {
    json!({"range":{"start":{"line":0,"character":0},"end":{"line":0,"character":0}},"severity":1,"code":"F0001","source":"foresee","message":message})
}
struct Document {
    text: Option<String>,
    version: i64,
}
impl Document {
    fn diagnostics(&self) -> Vec<Value> {
        let Some(text) = &self.text else {
            return vec![limit_diagnostic("source byte limit exceeded")];
        };
        match check_ownership(text) {
            Ok(_) => vec![],
            Err(DeclarationFailure::Diagnostics(errors)) => errors.into_iter().map(|d| json!({"range":range(text,&d.span),"severity":1,"code":d.code,"source":"foresee","message":d.message})).collect(),
            Err(DeclarationFailure::FrontendContract(message)) => vec![json!({"range":{"start":{"line":0,"character":0},"end":{"line":0,"character":0}},"severity":1,"code":"internal","source":"foresee","message":message})],
        }
    }
    fn symbols(&self) -> Value {
        let Some(text) = &self.text else {
            return json!([]);
        };
        let Ok(syntax) = foresee_syntax::parse(text) else {
            return json!([]);
        };
        let mut symbols = vec![];
        // Declaration identifiers follow the keyword; lexer spans give precise name ranges.
        let Ok(tokens) = foresee_syntax::lex(text) else {
            return json!([]);
        };
        for (group, kind) in [("resources", 13), ("models", 13), ("decisions", 12)] {
            if let Some(items) = syntax[group].as_array() {
                for item in items {
                    let start = item["span"]["start"].as_u64().unwrap_or(0) as usize;
                    if let Some(pair) = tokens.windows(2).find(|pair| pair[0].span.start == start) {
                        let name_range = range(text, &pair[1].span);
                        let mut full_span = pair[0].span.clone();
                        let (mut depth, mut blocks) = (0usize, 0usize);
                        for token in tokens.iter().filter(|t| t.span.start >= start) {
                            if kind != 12 && token.kind == ";" {
                                full_span.end = token.span.end;
                                break;
                            }
                            if kind == 12 {
                                if token.kind == "{" {
                                    depth += 1;
                                }
                                if token.kind == "}" {
                                    depth = depth.saturating_sub(1);
                                    if depth == 0 {
                                        blocks += 1;
                                    }
                                    if blocks == 2 {
                                        full_span.end = token.span.end;
                                        break;
                                    }
                                }
                            }
                        }
                        symbols.push(json!({"name":item["name"],"kind":kind,"range":range(text,&full_span),"selectionRange":name_range}));
                    }
                }
            }
        }
        json!(symbols)
    }
    fn hover(&self, pos: &Value) -> Value {
        let Some(text) = &self.text else {
            return Value::Null;
        };
        let Some(at) = offset(text, pos) else {
            return Value::Null;
        };
        let Ok(analysis) = check_ownership(text) else {
            return Value::Null;
        };
        // Current AST expression spans identify their leading token only.
        let found = analysis
            .expressions()
            .iter()
            .filter(|e| e.span.start <= at && at < e.span.end)
            .min_by_key(|e| e.span.end - e.span.start);
        match found {
            Some(expr) => {
                json!({"contents":{"kind":"plaintext","value":format!("{}: {}",expr.op,serde_json::to_string(&expr.inferred_type).unwrap_or_default())},"range":range(text,&expr.span)})
            }
            None => Value::Null,
        }
    }
}
#[derive(Default)]
struct Server {
    initialized: bool,
    shutdown: bool,
    documents: BTreeMap<String, Document>,
}
impl Server {
    fn handle(&mut self, message: Value) -> (Vec<Value>, Option<i32>) {
        let id = message.get("id").cloned();
        if message.get("jsonrpc") != Some(&json!("2.0"))
            || !message["method"].is_string()
            || id
                .as_ref()
                .is_some_and(|id| !(id.is_string() || id.is_i64()))
        {
            return (vec![error(&Value::Null, -32600, "invalid request")], None);
        }
        let method = message["method"].as_str().unwrap();
        if method == "exit" && id.is_none() {
            return (vec![], Some(if self.shutdown { 0 } else { 1 }));
        }
        if method == "initialize" && id.is_some() && !self.initialized {
            self.initialized = true;
            return (
                vec![response(
                    id.as_ref().unwrap(),
                    json!({"capabilities":{"positionEncoding":"utf-16","textDocumentSync":{"openClose":true,"change":1},"documentSymbolProvider":true,"hoverProvider":true},"serverInfo":{"name":"foresee-lsp","version":env!("CARGO_PKG_VERSION")}}),
                )],
                None,
            );
        }
        if method == "initialize" && self.initialized {
            return (
                id.map(|id| vec![error(&id, -32600, "already initialized")])
                    .unwrap_or_default(),
                None,
            );
        }
        if !self.initialized || self.shutdown {
            return (
                id.map(|id| {
                    vec![error(
                        &id,
                        if self.shutdown { -32600 } else { -32002 },
                        "server is not running",
                    )]
                })
                .unwrap_or_default(),
                None,
            );
        }
        if let Some(id) = id {
            let uri = message["params"]["textDocument"]["uri"].as_str();
            let result = match method {
                "shutdown" => {
                    self.shutdown = true;
                    self.documents.clear();
                    Value::Null
                }
                "textDocument/documentSymbol" => {
                    let Some(uri) = uri else {
                        return (vec![error(&id, -32602, "document URI required")], None);
                    };
                    self.documents
                        .get(uri)
                        .map(Document::symbols)
                        .unwrap_or(json!([]))
                }
                "textDocument/hover" => {
                    let pos = &message["params"]["position"];
                    if uri.is_none() || !pos["line"].is_u64() || !pos["character"].is_u64() {
                        return (
                            vec![error(&id, -32602, "URI and nonnegative position required")],
                            None,
                        );
                    }
                    self.documents
                        .get(uri.unwrap())
                        .map(|d| d.hover(pos))
                        .unwrap_or(Value::Null)
                }
                _ => return (vec![error(&id, -32601, "method not supported")], None),
            };
            return (vec![response(&id, result)], None);
        }
        if ["initialized", "$/cancelRequest", "$/setTrace"].contains(&method) {
            return (vec![], None);
        }
        if ![
            "textDocument/didOpen",
            "textDocument/didChange",
            "textDocument/didClose",
        ]
        .contains(&method)
        {
            return (vec![], None);
        }
        let td = &message["params"]["textDocument"];
        let Some(uri) = td["uri"].as_str().filter(|uri| uri.len() <= 4096) else {
            return (vec![log("invalid document URI")], None);
        };
        if method == "textDocument/didClose" {
            self.documents.remove(uri);
            return (vec![publish(uri, None, vec![])], None);
        }
        let Some(version) = td["version"].as_i64() else {
            return (vec![log("document version required")], None);
        };
        let text = if method == "textDocument/didOpen" {
            if self.documents.contains_key(uri) {
                return (vec![log("document already open")], None);
            }
            if self.documents.len() >= MAX_DOCUMENTS {
                return (
                    vec![publish(
                        uri,
                        Some(version),
                        vec![limit_diagnostic("open document limit exceeded")],
                    )],
                    None,
                );
            }
            td["text"].as_str()
        } else {
            let Some(previous) = self.documents.get(uri) else {
                return (vec![log("change for unopened document")], None);
            };
            if version <= previous.version {
                return (vec![], None);
            }
            let changes = message["params"]["contentChanges"].as_array();
            match changes {
                Some(changes)
                    if !changes.is_empty()
                        && changes.iter().all(|change| {
                            change.get("range").is_none() && change["text"].is_string()
                        }) =>
                {
                    changes.last().and_then(|change| change["text"].as_str())
                }
                _ => None,
            }
        };
        let Some(text) = text else {
            return (
                vec![log(
                    "full document text required; incremental changes are unsupported",
                )],
                None,
            );
        };
        let doc = Document {
            text: (text.len() <= MAX_SOURCE_BYTES).then(|| text.to_owned()),
            version,
        };
        let diagnostics = doc.diagnostics();
        self.documents.insert(uri.to_owned(), doc);
        (vec![publish(uri, Some(version), diagnostics)], None)
    }
}
pub fn serve(mut input: impl BufRead, mut output: impl Write) -> io::Result<i32> {
    let mut server = Server::default();
    while let Some(message) = read_frame(&mut input)? {
        let message = match message {
            Ok(message) => message,
            Err(_) => {
                write_frame(&mut output, &error(&Value::Null, -32700, "invalid JSON"))?;
                continue;
            }
        };
        let (messages, exit) = server.handle(message);
        for message in messages {
            write_frame(&mut output, &message)?;
        }
        if let Some(code) = exit {
            return Ok(code);
        }
    }
    Ok(if server.shutdown { 0 } else { 1 })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    fn request(id: i64, method: &str, params: Value) -> Value {
        json!({"jsonrpc":"2.0","id":id,"method":method,"params":params})
    }
    fn note(method: &str, params: Value) -> Value {
        json!({"jsonrpc":"2.0","method":method,"params":params})
    }
    fn server() -> Server {
        let mut s = Server::default();
        s.handle(request(1, "initialize", json!({})));
        s
    }
    #[test]
    fn utf16_round_trip_and_surrogate_boundary() {
        let text = "a😀b\r\n茶";
        assert_eq!(position("a\rb", 2), json!({"line":1,"character":0}));
        assert_eq!(offset("a\rb", &json!({"line":1,"character":0})), Some(2));
        assert_eq!(position(text, 2), json!({"line":0,"character":3}));
        assert_eq!(offset(text, &json!({"line":0,"character":3})), Some(2));
        assert_eq!(offset(text, &json!({"line":0,"character":2})), None);
        assert_eq!(position(text, 5), json!({"line":1,"character":0}));
    }
    #[test]
    fn bounded_framing_and_parse_error_recovery() {
        for bytes in [
            b"Content-Length: 8000001\r\n\r\n".as_slice(),
            b"Content-Length: 1\r\nContent-Length: 1\r\n\r\nx",
            b"Content-Length: 10\r\n\r\nx",
        ] {
            assert!(read_frame(&mut Cursor::new(bytes)).is_err());
        }
        assert!(read_frame(&mut Cursor::new(vec![b'x'; MAX_HEADER + 1])).is_err());
        let mut input = b"Content-Length: 1\r\n\r\n{".to_vec();
        write_frame(&mut input, &request(1, "initialize", json!({}))).unwrap();
        write_frame(&mut input, &request(2, "shutdown", Value::Null)).unwrap();
        write_frame(&mut input, &note("exit", Value::Null)).unwrap();
        let mut output = vec![];
        assert_eq!(serve(Cursor::new(input), &mut output).unwrap(), 0);
        let mut output = Cursor::new(output);
        assert_eq!(
            read_frame(&mut output).unwrap().unwrap().unwrap()["error"]["code"],
            -32700
        );
        assert_eq!(read_frame(&mut output).unwrap().unwrap().unwrap()["id"], 1);
    }
    #[test]
    fn lifecycle_and_unknown_requests() {
        let mut s = Server::default();
        assert_eq!(
            s.handle(request(1, "textDocument/hover", json!({}))).0[0]["error"]["code"],
            -32002
        );
        s.handle(request(2, "initialize", json!({})));
        assert_eq!(
            s.handle(request(3, "unknown", Value::Null)).0[0]["error"]["code"],
            -32601
        );
        s.handle(request(4, "shutdown", Value::Null));
        assert_eq!(s.handle(note("exit", Value::Null)).1, Some(0));
        assert_eq!(
            Server::default().handle(note("exit", Value::Null)).1,
            Some(1)
        );
    }
    #[test]
    fn edits_clear_diagnostics_and_ignore_old_versions() {
        let mut s = server();
        let uri = "file:///sample.fore";
        let broken = s
            .handle(note(
                "textDocument/didOpen",
                json!({"textDocument":{"uri":uri,"version":1,"text":"@"}}),
            ))
            .0;
        assert!(!broken[0]["params"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty());
        let fixed = include_str!("../../../examples/repair.fore");
        let result = s
            .handle(note(
                "textDocument/didChange",
                json!({"textDocument":{"uri":uri,"version":2},"contentChanges":[{"text":"@"},{"text":fixed}]}),
            ))
            .0;
        assert_eq!(result[0]["params"]["diagnostics"], json!([]));
        assert!(s
            .handle(note(
                "textDocument/didChange",
                json!({"textDocument":{"uri":uri,"version":1},"contentChanges":[{"text":"@"}]})
            ))
            .0
            .is_empty());
        assert_eq!(s.documents[uri].text.as_deref(), Some(fixed));
        assert_eq!(
            s.handle(note(
                "textDocument/didClose",
                json!({"textDocument":{"uri":uri}})
            ))
            .0[0]["params"]["diagnostics"],
            json!([])
        );
        assert!(s.documents.is_empty());
    }
    #[test]
    fn oversized_edits_cannot_keep_stale_hover() {
        let mut s = server();
        let uri = "file:///sample.fore";
        s.handle(note("textDocument/didOpen",json!({"textDocument":{"uri":uri,"version":1,"text":include_str!("../../../examples/repair.fore")}})));
        let result=s.handle(note("textDocument/didChange",json!({"textDocument":{"uri":uri,"version":2},"contentChanges":[{"text":" ".repeat(MAX_SOURCE_BYTES+1)}]}))).0;
        assert_eq!(result[0]["params"]["diagnostics"][0]["code"], "F0001");
        assert!(s.documents[uri].text.is_none());
        assert_eq!(s.documents[uri].symbols(), json!([]));
    }
    #[test]
    fn document_limit_and_invalid_changes_are_explicit() {
        let mut s = server();
        for index in 0..MAX_DOCUMENTS {
            s.handle(note(
                "textDocument/didOpen",
                json!({"textDocument":{"uri":format!("file:///{index}"),"version":1,"text":""}}),
            ));
        }
        let messages = s
            .handle(note(
                "textDocument/didOpen",
                json!({"textDocument":{"uri":"file:///extra","version":1,"text":""}}),
            ))
            .0;
        assert_eq!(messages[0]["params"]["diagnostics"][0]["code"], "F0001");
        assert_eq!(s.documents.len(), MAX_DOCUMENTS);
        assert_eq!(s.handle(note("textDocument/didChange",json!({"textDocument":{"uri":"file:///0","version":2},"contentChanges":[{"text":"x","range":{}}]}))).0[0]["method"],"window/logMessage");
    }
    #[test]
    fn symbols_have_identifier_selection_and_whole_declaration_ranges() {
        let d = Document {
            text: Some(include_str!("../../../examples/repair.fore").into()),
            version: 1,
        };
        let symbols = d.symbols();
        let brace_text = d
            .text
            .as_ref()
            .unwrap()
            .replace("Fill only derived unit prices", "{");
        assert_eq!(
            Document {
                text: Some(brace_text),
                version: 1
            }
            .symbols()[2]["range"]["end"]["line"],
            symbols[2]["range"]["end"]["line"]
        );
        assert_eq!(symbols.as_array().unwrap().len(), 3);
        assert_eq!(symbols[0]["name"], "catalog");
        assert!(
            symbols[2]["range"]["end"]["line"].as_u64().unwrap()
                > symbols[2]["selectionRange"]["end"]["line"]
                    .as_u64()
                    .unwrap()
        );
    }
}
