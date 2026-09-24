from __future__ import annotations

import argparse
import json
import sys
import os
import sqlite3
from pathlib import Path

from .catalog import Catalog
from .compiler import compile_source
from .model import CompileFailure
from .runtime import Runtime, replay_report, save_report
from .journal import Journal, reconcile


def load_ir(source_path: Path) -> dict:
    return compile_source(source_path.read_text(), str(source_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foresee", description="Bootstrap compiler for auditable decisions")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="parse and statically check a source file")
    check.add_argument("source", type=Path)
    build = sub.add_parser("build", help="emit canonical JSON IR")
    build.add_argument("source", type=Path)
    build.add_argument("-o", "--output", type=Path, required=True)
    demo = sub.add_parser("demo", help="run the catalog-repair vertical slice")
    demo.add_argument("source", type=Path)
    demo.add_argument("--workspace", type=Path, default=Path("build/demo"))
    demo.add_argument("--simulate-stale", action="store_true")
    demo.add_argument("--fault", choices=["before_transaction", "before_commit", "after_commit"],
                      help="test only: terminate process with exit code 86 at a commit boundary")
    recover = sub.add_parser("reconcile", help="resolve recorded operations by reading target receipts without writes")
    recover.add_argument("journal", type=Path)
    recover.add_argument("--run-id")
    replay = sub.add_parser("replay", help="verify a run report without live calls")
    replay.add_argument("report", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "reconcile":
            result = reconcile(args.journal, args.run_id)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 2 if any(r["state"] == "unresolved" for r in result["runs"]) else 0
        if args.command == "replay":
            print(json.dumps(replay_report(args.report), indent=2, sort_keys=True))
            return 0
        ir = load_ir(args.source)
        if args.command == "check":
            print(f"ok: {args.source} ({ir['program_digest'][:12]})")
            return 0
        if args.command == "build":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(ir, indent=2, sort_keys=True) + "\n")
            print(args.output)
            return 0
        args.workspace.mkdir(parents=True, exist_ok=True)
        catalog = Catalog(args.workspace / "catalog.db")
        journal = None
        try:
            journal = Journal(args.workspace / "runs.db")
            catalog.seed()
            def fault_hook(stage):
                if args.fault == stage:
                    os._exit(86)
            report = Runtime(ir, catalog, simulate_stale=args.simulate_stale,
                             journal=journal, fault_hook=fault_hook).run()
            report_path = args.workspace / "run-report.json"
            save_report(report, report_path)
        finally:
            catalog.close()
            if journal:
                journal.close()
        print(json.dumps({"report": str(report_path), "run_id": report["run_id"], "journal": report["journal"], "selection": report["selection"], "outcome": report["outcome"]}, indent=2))
        return 0
    except CompileFailure as failure:
        source_name = str(getattr(args, "source", "<memory>"))
        for diagnostic in failure.diagnostics:
            print(diagnostic.render(source_name), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
