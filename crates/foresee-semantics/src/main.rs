use foresee_semantics::{check_declarations, DeclarationFailure};
use serde_json::json;
use std::{env, fs::File, io::Read, process};
fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 || args[1] != "declarations" {
        eprintln!("usage: foresee-semantics declarations SOURCE\nDeclaration checks only; use Python for complete semantic validation.");
        process::exit(2);
    }
    let mut bytes = Vec::new();
    let read = File::open(&args[2]).and_then(|file| file.take(1_000_001).read_to_end(&mut bytes));
    if let Err(e) = read {
        eprintln!("{}: {e}", args[2]);
        process::exit(2);
    }
    if bytes.len() > 1_000_000 {
        eprintln!("source exceeds 1000000 bytes");
        process::exit(2);
    }
    let source = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("invalid UTF-8: {e}");
            process::exit(2);
        }
    };
    match check_declarations(&source) {
        Ok(symbols) => println!(
            "{}",
            json!({"ok":true,"checked_phase":"declarations","executable":false,"symbols":symbols.symbols()})
        ),
        Err(DeclarationFailure::Diagnostics(diagnostics)) => {
            println!(
                "{}",
                json!({"ok":false,"checked_phase":"declarations","executable":false,"diagnostics":diagnostics})
            );
            process::exit(1);
        }
        Err(DeclarationFailure::FrontendContract(error)) => {
            eprintln!("internal frontend contract error: {error}");
            process::exit(2);
        }
    }
}
