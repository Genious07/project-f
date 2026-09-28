use serde_json::json;
use std::{env, fs, process};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 || !["lex", "parse"].contains(&args[1].as_str()) {
        eprintln!("usage: foresee-syntax <lex|parse> SOURCE\nSyntax only; use the Python compiler for semantic checks.");
        process::exit(2);
    }
    let source = match fs::read_to_string(&args[2]) {
        Ok(s) if s.len() <= 1_000_000 => s,
        Ok(_) => {
            eprintln!("source exceeds 1000000 bytes");
            process::exit(2);
        }
        Err(e) => {
            eprintln!("{}: {e}", args[2]);
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
