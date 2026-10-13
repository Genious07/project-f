use foresee_syntax::limits::MAX_SOURCE_BYTES;
use serde_json::json;
use std::{env, fs::File, io::Read, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 || !["lex", "parse"].contains(&args[1].as_str()) {
        eprintln!("usage: foresee-syntax <lex|parse> SOURCE\nSyntax only; use the Python compiler for semantic checks.");
        process::exit(2);
    }
    let mut bytes = Vec::new();
    if let Err(e) = File::open(&args[2]).and_then(|file| {
        file.take((MAX_SOURCE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
    }) {
        eprintln!("{}: {e}", args[2]);
        process::exit(2);
    }
    if bytes.len() > MAX_SOURCE_BYTES {
        eprintln!("source exceeds {MAX_SOURCE_BYTES} bytes");
        process::exit(2);
    }
    let source = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("invalid UTF-8: {e}");
            process::exit(2);
        }
    };
    let result = if args[1] == "lex" {
        foresee_syntax::lex(&source).map(|tokens| json!({"ok": true, "tokens": tokens}))
    } else {
        foresee_syntax::parse(&source)
            .map(|syntax| json!({"ok": true, "syntax_version": 1, "syntax": syntax}))
    };
    match result {
        Ok(value) => println!("{value}"),
        Err(errors) => {
            println!("{}", json!({"ok": false, "diagnostics": errors}));
            process::exit(1);
        }
    }
}
