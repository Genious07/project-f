import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from foresee.cli import main
from foresee.compiler import compile_source
from foresee.model import CompileFailure
from foresee.runtime import Runtime


SOURCE = (Path(__file__).parents[1] / "examples/repair.fore").read_text()


class SubsetTests(unittest.TestCase):
    def test_invalid_programs_never_open_database(self):
        cases = {
            "empty": "",
            "ambiguous entry": SOURCE + "decision extra() ! {} { return 1; }",
            "unknown resource": SOURCE.replace(": Catalog", ": Other"),
            "unknown model": SOURCE.replace(": Planner", ": Other"),
            "unknown effect": SOURCE.replace("Snapshot(catalog),", "Write(catalog),"),
            "wrong effect target": SOURCE.replace("Infer(planner)", "Infer(catalog)"),
            "unknown method": SOURCE.replace("valid_unit_arithmetic", "close"),
            "wrong target": SOURCE.replace("catalog.valid_unit_arithmetic", "planner.valid_unit_arithmetic"),
            "wrong arity": SOURCE.replace("valid_unit_arithmetic(after)", "valid_unit_arithmetic(after, base)"),
            "wrong argument": SOURCE.replace("valid_unit_arithmetic(after)", "valid_unit_arithmetic(1)"),
            "bad proposal": SOURCE.replace('base, "Fill only derived unit prices", 4', "base"),
            "bad proposal type": SOURCE.replace("<Patch>", "<Other>"),
            "bad limit": SOURCE.replace('prices", 4', 'prices", 0'),
            "bad simulate": SOURCE.replace("catalog.apply", "catalog.close"),
            "bad check": SOURCE.replace("check catalog.valid_unit_arithmetic(after)", "check 1"),
            "bad metric": SOURCE.replace("unresolved: Int", "unresolved: String"),
            "bad return": SOURCE.replace("return commit chosen to catalog", "return 1"),
            "bad return annotation": SOURCE.replace("-> DecisionResult", "-> String"),
            "ignored annotation": SOURCE.replace("let base =", "let base: String ="),
            "reserved binding": SOURCE.replace("let after =", "let __base__ ="),
            "unreachable effects": SOURCE.replace("return commit chosen to catalog;", "return commit chosen to catalog; let x = snapshot catalog;"),
            "branch snapshot": SOURCE.replace("let after =", "let live = snapshot catalog; let after ="),
            "branch proposal": SOURCE.replace("let after =", 'let more = propose planner<Patch>(base, "x", 1); let after ='),
            "nested explore": SOURCE.replace("let after =", "let nested = explore p in plans from base {}; let after ="),
            "branch return": SOURCE.replace("let after =", "return 1; let after ="),
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.fore"
            for label, text in cases.items():
                with self.subTest(label=label):
                    with self.assertRaises(CompileFailure):
                        compile_source(text)
                    source.write_text(text)
                    with patch("foresee.cli.Catalog") as database, contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(main(["demo", str(source), "--workspace", str(Path(directory) / "out")]), 1)
                        database.assert_not_called()

    def test_runtime_rejects_branch_effect_before_evaluating_arguments(self):
        runtime = Runtime(compile_source(SOURCE), None)
        for op in ("snapshot", "propose", "explore", "select", "commit"):
            with self.subTest(op=op), self.assertRaisesRegex(RuntimeError, "forbidden"):
                runtime.eval_expr({"op": op}, {}, branch=True)

    def test_runtime_dispatch_is_explicit(self):
        runtime = Runtime(compile_source(SOURCE), None)
        with self.assertRaisesRegex(RuntimeError, "unknown resource method"):
            runtime.eval_expr({"op": "call", "target": "catalog", "method": "close", "args": []}, {}, False)


if __name__ == "__main__":
    unittest.main()
