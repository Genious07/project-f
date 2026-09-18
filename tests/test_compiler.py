from __future__ import annotations

import unittest
from pathlib import Path

from foresee.compiler import compile_source
from foresee.model import CompileFailure


ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "examples" / "repair.fore").read_text()


class CompilerTests(unittest.TestCase):
    def test_compiles_example_to_stable_ir(self) -> None:
        first = compile_source(SOURCE)
        second = compile_source(SOURCE)
        self.assertEqual(first["program_digest"], second["program_digest"])
        self.assertEqual(first["decisions"][0]["name"], "repair_catalog")

    def test_rejects_live_commit_inside_explore(self) -> None:
        bad = SOURCE.replace(
            "measure unresolved: Int = catalog.unresolved_units(after);",
            "let forbidden = commit plan to catalog;\n        measure unresolved: Int = catalog.unresolved_units(after);",
        )
        with self.assertRaises(CompileFailure) as caught:
            compile_source(bad)
        self.assertIn("F3102", {item.code for item in caught.exception.diagnostics})

    def test_rejects_undeclared_effect(self) -> None:
        bad = SOURCE.replace(", Commit(catalog)", "")
        with self.assertRaises(CompileFailure) as caught:
            compile_source(bad)
        self.assertIn("F3001", {item.code for item in caught.exception.diagnostics})


if __name__ == "__main__":
    unittest.main()
