"""Compare native declaration diagnostics and symbols with the Python reference."""
import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.compiler import Checker
from foresee.lexer import lex
from foresee.parser import parse
from foresee.model import CompileFailure

CODES = {"F3200", "F3201", "F3000"}


def cases():
    manifest = json.loads((ROOT / "fixtures/declarations/cases.json").read_text())
    assert manifest["version"] == 1
    return manifest["cases"]


def reference(source):
    try:
        program = parse(lex(source))
    except CompileFailure as failure:
        return [{"code": d.code, "span": asdict(d.span)} for d in failure.diagnostics], []
    checker = Checker(program)
    try:
        checker.check()
    except CompileFailure:
        pass
    diagnostics = [{"code": d.code, "span": asdict(d.span)}
                   for d in checker.diagnostics if d.code in CODES]
    symbols = []
    for kind, declarations in (("resource", program.resources), ("model", program.models), ("decision", program.decisions)):
        for index, item in enumerate(declarations):
            symbols.append({"id": {"kind": kind, "id": index}, "name": item.name, "span": asdict(item.span)})
    return diagnostics, symbols


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/foresee-semantics")
    args = parser.parse_args()
    binary = str(args.binary.resolve())
    corpus = cases()
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "case.fore"
        for case in corpus:
            diagnostics, symbols = reference(case["source"])
            assert [d["code"] for d in diagnostics] == case["codes"], (case["name"], diagnostics)
            source.write_text(case["source"], encoding="utf-8")
            process = subprocess.run([binary, "declarations", str(source)], capture_output=True, text=True, timeout=10)
            actual = json.loads(process.stdout)
            assert process.returncode == (1 if diagnostics else 0), (case["name"], process.stderr)
            assert actual["checked_phase"] == "declarations" and actual["executable"] is False
            assert actual["ok"] == (not diagnostics), case["name"]
            if diagnostics:
                observed = [{"code": d["code"], "span": d["span"]} for d in actual["diagnostics"]]
                assert observed == diagnostics, (case["name"], observed, diagnostics)
            else:
                assert actual["symbols"] == symbols, (case["name"], actual)
        # Operational failures are not syntax or declaration failures.
        for payload in (b"\xff", b" " * 1_000_001):
            source.write_bytes(payload)
            process = subprocess.run([binary, "declarations", str(source)], capture_output=True, timeout=10)
            assert process.returncode == 2 and not process.stdout
        for argv in ([binary], [binary, "check", str(source)], [binary, "declarations", str(source.with_name("missing.fore"))]):
            process = subprocess.run(argv, capture_output=True, timeout=10)
            assert process.returncode == 2 and not process.stdout
    print(f"PASS: {len(corpus)} declaration fixtures match Python codes, spans, and symbols; 5 CLI error paths pass. Body semantics remain Python-only.")


if __name__ == "__main__":
    main()
