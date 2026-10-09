use foresee_semantics::{
    check_declarations, check_effects, check_lineage, check_ownership, check_types,
    DeclarationFailure,
};
use serde_json::json;
use std::{env, fs::File, io::Read, process};
fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3
        || !["declarations", "types", "effects", "lineage", "ownership"].contains(&args[1].as_str())
    {
        eprintln!("usage: foresee-semantics <declarations|types|effects|lineage|ownership> SOURCE\nStaged checks only; use Python for complete semantic validation.");
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
    let phase = &args[1];
    let result = if phase == "ownership" {
        check_ownership(&source).map(|analysis| json!({"ok":true,"checked_phase":phase,"executable":false,"expressions":analysis.expressions()}))
    } else if phase == "lineage" {
        check_lineage(&source).map(|analysis| json!({"ok":true,"checked_phase":phase,"executable":false,"expressions":analysis.expressions()}))
    } else if phase == "effects" {
        check_effects(&source).map(|analysis| json!({"ok":true,"checked_phase":phase,"executable":false,"expressions":analysis.expressions()}))
    } else if phase == "types" {
        check_types(&source).map(|analysis| json!({"ok":true,"checked_phase":phase,"executable":false,"expressions":analysis.expressions()}))
    } else {
        check_declarations(&source).map(|symbols| json!({"ok":true,"checked_phase":phase,"executable":false,"symbols":symbols.symbols()}))
    };
    match result {
        Ok(value) => println!("{value}"),
        Err(DeclarationFailure::Diagnostics(diagnostics)) => {
            println!(
                "{}",
                json!({"ok":false,"checked_phase":phase,"executable":false,"diagnostics":diagnostics})
            );
            process::exit(1);
        }
        Err(DeclarationFailure::FrontendContract(error)) => {
            eprintln!("internal frontend contract error: {error}");
            process::exit(2);
        }
    }
}
