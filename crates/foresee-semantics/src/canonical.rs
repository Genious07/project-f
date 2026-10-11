//! Python-compatible canonical identity for checked IR, not arbitrary JSON.
use crate::{ir, DeclarationFailure};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fmt::Write;

/// Complete checked IR with a digest. Construction requires successful source
/// checking; serialization does not grant runtime authority.
#[derive(Debug, Serialize)]
#[serde(transparent)]
pub struct CompiledProgram {
    ir: Value,
    #[serde(skip)]
    canonical: String,
}
impl CompiledProgram {
    /// The ASCII JSON bytes hashed before adding `program_digest`.
    pub fn canonical_json(&self) -> &str {
        &self.canonical
    }
}
pub fn compile_source(source: &str) -> Result<CompiledProgram, DeclarationFailure> {
    let ir::IrBody(mut ir) = ir::lower_source(source)?;
    let mut canonical = String::new();
    encode(&ir, &mut canonical)?;
    let digest = format!("{:x}", Sha256::digest(canonical.as_bytes()));
    ir["program_digest"] = Value::String(digest);
    Ok(CompiledProgram { ir, canonical })
}

fn encode(value: &Value, out: &mut String) -> Result<(), DeclarationFailure> {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(value) => out.push_str(if *value { "true" } else { "false" }),
        Value::Number(value) => {
            let digits = value.to_string();
            // IR source integers are arbitrary-size nonnegative decimal integers.
            // Reject floats and other forms rather than silently changing identity.
            if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
                return Err(DeclarationFailure::FrontendContract(
                    "non-integer IR number".into(),
                ));
            }
            out.push_str(&digits);
        }
        Value::String(value) => string(value, out),
        Value::Array(values) => {
            out.push('[');
            for (index, value) in values.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                encode(value, out)?;
            }
            out.push(']');
        }
        Value::Object(values) => {
            out.push('{');
            // UTF-8 lexicographic ordering matches Unicode scalar ordering.
            // Explicit sorting keeps identity independent of serde map features.
            let mut entries: Vec<_> = values.iter().collect();
            entries.sort_by(|a, b| a.0.cmp(b.0));
            for (index, (key, value)) in entries.into_iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                string(key, out);
                out.push(':');
                encode(value, out)?;
            }
            out.push('}');
        }
    }
    Ok(())
}
fn string(value: &str, out: &mut String) {
    out.push('"');
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            ' '..='~' => out.push(ch),
            _ => {
                let mut units = [0; 2];
                for unit in ch.encode_utf16(&mut units) {
                    // Writing to a String is infallible.
                    write!(out, "\\u{unit:04x}").expect("String formatting cannot fail");
                }
            }
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn golden_bytes_match_python_escape_and_key_order_rules() {
        let value = json!({"😀": ["\u{0}\u{8}\u{c}\n\r\t\u{1f}\u{7f}é😀/\\\"", null, true], "z": 12, "\u{e000}": []});
        let mut actual = String::new();
        encode(&value, &mut actual).unwrap();
        assert_eq!(
            actual,
            r#"{"z":12,"\ue000":[],"\ud83d\ude00":["\u0000\b\f\n\r\t\u001f\u007f\u00e9\ud83d\ude00/\\\"",null,true]}"#
        );
    }
    #[test]
    fn huge_integer_keeps_every_digit_and_float_is_rejected() {
        let number = "12345678901234567890123456789012345678901234567890";
        let mut out = String::new();
        encode(&serde_json::from_str(number).unwrap(), &mut out).unwrap();
        assert_eq!(out, number);
        assert!(encode(&json!(1.25), &mut String::new()).is_err());
    }
    #[test]
    fn object_order_is_irrelevant_but_array_order_is_preserved() {
        let left: Value = serde_json::from_str(r#"{"b":[1,2],"a":{"z":0,"x":1}}"#).unwrap();
        let right: Value = serde_json::from_str(r#"{"a":{"x":1,"z":0},"b":[1,2]}"#).unwrap();
        let mut first = String::new();
        let mut second = String::new();
        encode(&left, &mut first).unwrap();
        encode(&right, &mut second).unwrap();
        assert_eq!(first, second);
        let source = include_str!("../../../examples/repair.fore");
        let left =
            compile_source(&source.replace("let base =", "let a = 1; let b = 2; let base ="))
                .unwrap();
        let right =
            compile_source(&source.replace("let base =", "let b = 2; let a = 1; let base ="))
                .unwrap();
        assert_ne!(left.ir["program_digest"], right.ir["program_digest"]);
    }
    #[test]
    fn sha256_uses_standard_known_vector() {
        assert_eq!(
            format!("{:x}", Sha256::digest(b"abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
    #[test]
    fn digest_is_excluded_from_preimage_and_bad_source_has_no_artifact() {
        let program = compile_source(include_str!("../../../examples/repair.fore")).unwrap();
        assert!(!program.canonical_json().contains("program_digest"));
        assert!(serde_json::to_value(&program).unwrap()["program_digest"].is_string());
        assert!(compile_source("invalid").is_err());
    }
}
