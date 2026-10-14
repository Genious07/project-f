//! User-facing native compiler commands. Development stage commands stay separate.
use foresee_semantics::{canonical, check_ownership, DeclarationFailure};
use foresee_syntax::limits::MAX_SOURCE_BYTES;
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fs::{self, File, OpenOptions},
    io::{self, Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};

const HELP: &str = "Foresee native compiler\n\nUsage:\n  foresee-semantics check SOURCE [--format human|json]\n  foresee-semantics build SOURCE -o OUTPUT [--format human|json]\n\nChecks are offline. Build writes complete typed IR with a program digest.\nOutput must not already exist. No directories are created. Execution remains in Python.\nExit codes: 0 success, 1 source rejected, 2 invocation/input/output/internal failure.\nDevelopment commands: declarations, types, effects, lineage, ownership, ir, identity.";
struct Options {
    command: String,
    source: PathBuf,
    output: Option<PathBuf>,
    json: bool,
}
fn parse(args: &[OsString]) -> Result<Options, String> {
    let command = args[0].to_string_lossy().into_owned();
    let mut source = None;
    let mut output = None;
    let mut format = None;
    let mut positional = false;
    let mut index = 1;
    while index < args.len() {
        match args[index].to_str() {
            Some("--") if !positional => positional = true,
            Some("--format") if !positional => {
                index += 1;
                let value = args
                    .get(index)
                    .and_then(|s| s.to_str())
                    .ok_or("--format requires human or json")?;
                if format.is_some() || !["human", "json"].contains(&value) {
                    return Err("--format must appear once with human or json".into());
                }
                format = Some(value == "json");
            }
            Some("-o" | "--output") if !positional => {
                index += 1;
                let value = args.get(index).ok_or("--output requires a path")?;
                if command != "build" || output.is_some() || value.is_empty() {
                    return Err("--output is allowed once for build".into());
                }
                output = Some(PathBuf::from(value));
            }
            Some(value) if !positional && value.starts_with('-') => {
                return Err(format!("unknown option {value}"))
            }
            _ => {
                if source.is_some() || args[index].is_empty() {
                    return Err("expected exactly one source path".into());
                }
                source = Some(PathBuf::from(&args[index]));
            }
        }
        index += 1;
    }
    let source = source.ok_or("source path is required")?;
    if command == "build" && output.is_none() {
        return Err("build requires -o OUTPUT".into());
    }
    Ok(Options {
        command,
        source,
        output,
        json: format.unwrap_or(false),
    })
}
fn emit(value: &Value, human: &str, json_mode: bool, failed: bool) -> io::Result<()> {
    if json_mode {
        writeln!(io::stdout().lock(), "{value}")
    } else if failed {
        writeln!(io::stderr().lock(), "{human}")
    } else {
        writeln!(io::stdout().lock(), "{human}")
    }
}
fn fail(kind: &str, message: &str, json_mode: bool) -> i32 {
    let _ = emit(
        &json!({"ok":false,"error":{"kind":kind,"message":message}}),
        message,
        json_mode,
        true,
    );
    2
}
fn read_source(path: &Path) -> Result<String, String> {
    let mut bytes = Vec::new();
    File::open(path)
        .and_then(|file| {
            file.take((MAX_SOURCE_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
        })
        .map_err(|e| e.to_string())?;
    if bytes.len() > MAX_SOURCE_BYTES {
        return Err(format!("source exceeds {MAX_SOURCE_BYTES} bytes"));
    }
    String::from_utf8(bytes).map_err(|e| format!("invalid UTF-8: {e}"))
}

static TEMP_ID: AtomicUsize = AtomicUsize::new(0);
struct Temporary(PathBuf);
impl Drop for Temporary {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}
/// Publish a complete file without overwriting an existing file, symlink, or source.
fn publish(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    for _ in 0..64 {
        let id = TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let temporary = parent.join(format!(".foresee-{}-{id}.tmp", std::process::id()));
        let mut file = match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
        {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        };
        let temporary = Temporary(temporary);
        file.write_all(bytes)?;
        file.sync_all()?;
        // Same-directory hard linking publishes all bytes atomically and fails
        // if the destination exists. It also avoids a check-then-overwrite race.
        fs::hard_link(&temporary.0, path)?;
        return Ok(());
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "cannot allocate temporary output",
    ))
}

pub fn run(args: &[OsString]) -> i32 {
    if args == [OsString::from("--help")]
        || args == [OsString::from("-h")]
        || (args.len() == 2 && ["--help", "-h"].iter().any(|s| args[1] == *s))
    {
        return if writeln!(io::stdout().lock(), "{HELP}").is_ok() {
            0
        } else {
            2
        };
    }
    let requested_json = args
        .windows(2)
        .any(|w| w[0] == "--format" && w[1] == "json");
    let options = match parse(args) {
        Ok(value) => value,
        Err(e) => return fail("usage", &e, requested_json),
    };
    let source = match read_source(&options.source) {
        Ok(value) => value,
        Err(e) => return fail("input", &e, options.json),
    };
    let result = if options.command == "check" {
        check_ownership(&source).map(|_| None)
    } else {
        canonical::compile_source(&source).map(Some)
    };
    let artifact = match result {
        Ok(value) => value,
        Err(DeclarationFailure::Diagnostics(diagnostics)) => {
            let display = options.source.to_string_lossy();
            let human = diagnostics
                .iter()
                .map(|d| {
                    format!(
                        "{}: {}\n  --> {}:{}:{}",
                        d.code,
                        d.message.escape_debug(),
                        display.escape_debug(),
                        d.span.line,
                        d.span.column
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            let value = json!({"ok":false,"command":options.command,"source":display,"diagnostics":diagnostics});
            return if emit(&value, &human, options.json, true).is_ok() {
                1
            } else {
                2
            };
        }
        Err(DeclarationFailure::FrontendContract(e)) => return fail("internal", &e, options.json),
    };
    if let (Some(artifact), Some(path)) = (artifact, options.output.as_ref()) {
        let mut bytes = match serde_json::to_vec_pretty(&artifact) {
            Ok(value) => value,
            Err(e) => return fail("internal", &e.to_string(), options.json),
        };
        bytes.push(b'\n');
        if let Err(e) = publish(path, &bytes) {
            return fail("output", &e.to_string(), options.json);
        }
    }
    let value = json!({"ok":true,"command":options.command,"source":options.source.to_string_lossy(),"output":options.output.as_ref().map(|p| p.to_string_lossy())});
    let human = if let Some(path) = options.output {
        format!("Built {}", path.to_string_lossy().escape_debug())
    } else {
        format!(
            "Checked {}",
            options.source.to_string_lossy().escape_debug()
        )
    };
    if emit(&value, &human, options.json, false).is_ok() {
        0
    } else {
        2
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }
    #[test]
    fn validates_command_options_and_separator() {
        assert!(
            parse(&args(&[
                "build",
                "input.fore",
                "-o",
                "out.json",
                "--format",
                "json"
            ]))
            .unwrap()
            .json
        );
        assert_eq!(
            parse(&args(&["check", "--", "-source.fore"]))
                .unwrap()
                .source,
            Path::new("-source.fore")
        );
        for values in [
            vec!["build", "a"],
            vec!["check", "a", "-o", "b"],
            vec!["check", "a", "b"],
            vec!["check", "a", "--format", "xml"],
            vec!["check", "a", "--format", "json", "--format", "human"],
        ] {
            assert!(parse(&args(&values)).is_err());
        }
    }
}
