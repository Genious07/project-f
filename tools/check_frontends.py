"""Cross-language syntax conformance. Run after cargo build --locked."""
import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.lexer import lex
from foresee.parser import parse
from foresee.compiler import compile_source, compile_program
from foresee.syntax_bridge import program_from_syntax
from foresee.model import CompileFailure


def cases():
    manifest = json.loads((ROOT / "fixtures/syntax/cases.json").read_text())
    assert manifest["version"] == 1
    for case in manifest["cases"]:
        source = (ROOT / case["base"]).read_text() if "base" in case else case["source"]
        for before, after in case.get("replace", []):
            source = source.replace(before, after)
        yield case, source


def python_result(source, mode):
    try:
        tokens = lex(source)
        value = [asdict(t) for t in tokens] if mode == "lex" else asdict(parse(tokens))
        return {"ok": True, "tokens" if mode == "lex" else "syntax": json.loads(json.dumps(value))}
    except CompileFailure as error:
        return {"ok": False, "diagnostics": [asdict(d) for d in error.diagnostics]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/foresee-syntax")
    args = parser.parse_args()
    count = 0
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fixture.fore"
        for case, source in cases():
            path.write_text(source)
            for mode in ("lex", "parse"):
                reference = python_result(source, mode)
                process = subprocess.run([str(args.binary.resolve()), mode, str(path)], capture_output=True, text=True, timeout=10)
                actual = json.loads(process.stdout)
                assert process.returncode == (0 if reference["ok"] else 1), (case["name"], mode, process.stderr, actual)
                assert actual["ok"] == reference["ok"], (case["name"], mode)
                if reference["ok"]:
                    field = "tokens" if mode == "lex" else "syntax"
                    assert actual[field] == reference[field], (case["name"], mode, actual[field], reference[field])
                else:
                    norm = lambda errors: [(e["code"], e["span"]) for e in errors]
                    assert norm(actual["diagnostics"]) == norm(reference["diagnostics"]), (case["name"], mode, actual, reference)
                if mode == "parse":
                    assert actual["ok"] == case["parse_ok"], case["name"]
            if "semantic_ok" in case:
                try:
                    compile_source(source)
                    accepted = True
                except CompileFailure:
                    accepted = False
                assert accepted == case["semantic_ok"], case["name"]
                try:
                    bridged = compile_program(program_from_syntax(actual["syntax"]))
                    bridge_accepted = True
                except CompileFailure:
                    bridge_accepted = False
                assert bridge_accepted == accepted, case["name"]
                if accepted:
                    assert bridged == compile_source(source), (case["name"], "typed IR bridge mismatch")
            count += 1
    print(f"PASS: {count} shared fixtures; token/AST values and spans, diagnostic codes/spans match. Bridged Python semantic checks and typed IR match. Rust semantic checking is not implemented.")


if __name__ == "__main__":
    main()
