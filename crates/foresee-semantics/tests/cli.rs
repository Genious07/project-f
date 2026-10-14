use serde_json::Value;
use std::{
    fs,
    path::PathBuf,
    process::{Command, Output},
    sync::atomic::{AtomicUsize, Ordering},
};
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Workspace(PathBuf);
impl Workspace {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "foresee-cli-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(
            root.join("source.fore"),
            include_str!("../../../examples/repair.fore"),
        )
        .unwrap();
        // Copy the binary out of the checkout. No interpreter or repository is on PATH.
        fs::copy(
            env!("CARGO_BIN_EXE_foresee-semantics"),
            root.join("compiler"),
        )
        .unwrap();
        Self(root)
    }
    fn run(&self, args: &[&str]) -> Output {
        Command::new(self.0.join("compiler"))
            .args(args)
            .current_dir(&self.0)
            .env_clear()
            .env("PATH", "")
            .output()
            .unwrap()
    }
    fn no_temps(&self) {
        assert!(!fs::read_dir(&self.0).unwrap().any(|entry| entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".foresee-")));
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn json(output: &Output) -> Value {
    serde_json::from_slice(&output.stdout).unwrap()
}

#[test]
fn standalone_check_and_build() {
    let w = Workspace::new();
    let output = w.run(&["check", "source.fore", "--format", "json"]);
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(json(&output)["ok"], true);
    assert!(output.stderr.is_empty());
    let output = w.run(&["build", "source.fore", "-o", "built.json"]);
    assert_eq!(output.status.code(), Some(0));
    let ir: Value = serde_json::from_slice(&fs::read(w.0.join("built.json")).unwrap()).unwrap();
    assert_eq!(ir["schema_version"], "0.0.3");
    assert_eq!(ir["program_digest"].as_str().unwrap().len(), 64);
    assert!(ir.get("canonical_json").is_none());
    w.no_temps();
}
#[test]
fn source_errors_have_locations_and_no_artifact() {
    let w = Workspace::new();
    fs::write(w.0.join("bad.fore"), "resource x Catalog;").unwrap();
    let output = w.run(&["build", "bad.fore", "-o", "bad.json"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    let human = String::from_utf8(output.stderr).unwrap();
    assert!(human.contains("F2001:"));
    assert!(human.contains("bad.fore:1:12"));
    assert!(!w.0.join("bad.json").exists());
    let output = w.run(&["check", "bad.fore", "--format", "json"]);
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(json(&output)["diagnostics"][0]["span"]["column"], 12);
    assert!(output.stderr.is_empty());
}
#[test]
fn usage_and_input_failures_have_stable_json_categories() {
    let w = Workspace::new();
    for (args, kind) in [
        (vec!["build", "source.fore", "--format", "json"], "usage"),
        (vec!["check", "missing", "--format", "json"], "input"),
        (
            vec!["check", "source.fore", "--bad", "--format", "json"],
            "usage",
        ),
    ] {
        let output = w.run(&args);
        assert_eq!(output.status.code(), Some(2));
        assert_eq!(json(&output)["error"]["kind"], kind);
    }
}
#[test]
fn input_encoding_and_size_fail_without_panics() {
    let w = Workspace::new();
    for bytes in [vec![255], vec![b' '; 1_000_001]] {
        fs::write(w.0.join("input.fore"), bytes).unwrap();
        let output = w.run(&["check", "input.fore", "--format", "json"]);
        assert_eq!(output.status.code(), Some(2));
        assert_eq!(json(&output)["error"]["kind"], "input");
    }
}
#[test]
fn existing_output_and_source_are_preserved() {
    let w = Workspace::new();
    fs::write(w.0.join("out.json"), b"keep me").unwrap();
    let output = w.run(&["build", "source.fore", "-o", "out.json", "--format", "json"]);
    assert_eq!(output.status.code(), Some(2));
    assert_eq!(json(&output)["error"]["kind"], "output");
    assert_eq!(fs::read(w.0.join("out.json")).unwrap(), b"keep me");
    let before = fs::read(w.0.join("source.fore")).unwrap();
    assert_eq!(
        w.run(&["build", "source.fore", "-o", "source.fore"])
            .status
            .code(),
        Some(2)
    );
    assert_eq!(fs::read(w.0.join("source.fore")).unwrap(), before);
    w.no_temps();
}
#[test]
fn missing_parent_and_directory_destination_fail_cleanly() {
    let w = Workspace::new();
    for destination in ["missing/out.json", "."] {
        assert_eq!(
            w.run(&["build", "source.fore", "-o", destination])
                .status
                .code(),
            Some(2)
        );
        w.no_temps();
    }
}
#[test]
fn help_and_dash_prefixed_source() {
    let w = Workspace::new();
    assert_eq!(w.run(&["--help"]).status.code(), Some(0));
    assert_eq!(w.run(&["build", "--help"]).status.code(), Some(0));
    fs::copy(w.0.join("source.fore"), w.0.join("-source.fore")).unwrap();
    assert_eq!(
        w.run(&["check", "--", "-source.fore"]).status.code(),
        Some(0)
    );
}
#[cfg(unix)]
#[test]
fn symlink_destination_does_not_modify_target() {
    let w = Workspace::new();
    std::os::unix::fs::symlink("source.fore", w.0.join("linked.json")).unwrap();
    let before = fs::read(w.0.join("source.fore")).unwrap();
    assert_eq!(
        w.run(&["build", "source.fore", "-o", "linked.json"])
            .status
            .code(),
        Some(2)
    );
    assert_eq!(fs::read(w.0.join("source.fore")).unwrap(), before);
    w.no_temps();
}
#[cfg(unix)]
#[test]
fn non_utf8_paths_do_not_panic() {
    use std::os::unix::ffi::OsStringExt;
    let w = Workspace::new();
    let name = std::ffi::OsString::from_vec(vec![b'x', 255]);
    let supported = fs::copy(w.0.join("source.fore"), w.0.join(&name)).is_ok();
    let output = Command::new(w.0.join("compiler"))
        .arg("build")
        .arg(&name)
        .arg("-o")
        .arg("result.json")
        .args(["--format", "json"])
        .current_dir(&w.0)
        .env_clear()
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(if supported { 0 } else { 2 }));
    assert_eq!(json(&output)["ok"], supported);
}
#[test]
fn human_diagnostics_escape_control_characters_in_paths() {
    let w = Workspace::new();
    fs::write(w.0.join("bad\nname.fore"), "@").unwrap();
    let output = w.run(&["check", "bad\nname.fore"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("bad\\nname.fore"));
}
