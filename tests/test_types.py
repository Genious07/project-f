import unittest
from pathlib import Path

from foresee.compiler import compile_source
from foresee.model import CompileFailure
from foresee.runtime import Runtime


SOURCE = (Path(__file__).parents[1] / "examples/repair.fore").read_text()


class TypeTests(unittest.TestCase):
    def reject(self, source, code):
        with self.assertRaises(CompileFailure) as result:
            compile_source(source)
        self.assertIn(code, {d.code for d in result.exception.diagnostics})

    def test_every_expression_has_a_type(self):
        ir = compile_source(SOURCE)
        def visit(node):
            if isinstance(node, dict):
                if "op" in node:
                    self.assertIn("inferred_type", node)
                    self.assertNotEqual(node["inferred_type"]["kind"], "error")
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
        visit(ir)
        body = ir["decisions"][0]["body"]
        self.assertEqual([s["value"]["inferred_type"]["kind"] for s in body],
                         ["snapshot", "plans", "trials", "selected", "outcome"])
        self.assertEqual({s["value"]["inferred_type"]["lineage"] for s in body}, {"snapshot:1"})
        self.assertEqual(body[2]["value"]["inferred_type"]["metric_names"], ("unresolved",))

    def test_proposals_cannot_use_a_different_snapshot(self):
        source = SOURCE.replace("let plans =", "let other = snapshot catalog; let plans =")
        self.reject(source.replace("from base", "from other"), "F3301")

    def test_comparison_cannot_mix_snapshots(self):
        source = SOURCE.replace("let plans =", "let other = snapshot catalog; let plans =")
        self.reject(source.replace("after, base", "after, other"), "F3301")

    def test_metric_cannot_read_an_unrelated_snapshot(self):
        source = SOURCE.replace("let plans =", "let other = snapshot catalog; let plans =")
        self.reject(source.replace("unresolved_units(after)", "unresolved_units(other)"), "F3301")

    def test_resource_method_cannot_read_another_resource(self):
        source = SOURCE.replace("model planner", "resource other: Catalog; model planner")
        self.reject(source.replace("catalog.valid_unit_arithmetic", "other.valid_unit_arithmetic"), "F3301")

    def test_snapshot_alias_preserves_identity(self):
        source = SOURCE.replace("let plans =", "let alias = base; let plans =")
        compile_source(source.replace("from base", "from alias"))

    def test_valid_annotations_preserve_digest(self):
        source = SOURCE
        for name, kind in (("base", "Snapshot<catalog>"), ("plans", "Plans<catalog>"),
                           ("trials", "Trials<catalog>"), ("after", "Simulated<catalog>"),
                           ("chosen", "Selected<catalog>")):
            source = source.replace(f"let {name} =", f"let {name}: {kind} =")
        self.assertEqual(compile_source(source)["program_digest"], compile_source(SOURCE)["program_digest"])

    def test_invalid_annotations(self):
        for annotation in ("Snapshot<other>", "Selected<catalog>", "Snapshot", "Int<catalog>", "Unknown"):
            with self.subTest(annotation=annotation):
                self.reject(SOURCE.replace("let base =", f"let base: {annotation} ="), "F3300")

    def test_digest_ignores_formatting_comments_and_effect_order(self):
        changed = "// leading comment\n\n" + SOURCE.replace(";", ";\n\n").replace("    ", "\t")
        changed = changed.replace("Snapshot(catalog), Infer(planner)", "Infer(planner), Snapshot(catalog)")
        self.assertEqual(compile_source(SOURCE), compile_source(changed))
        self.assertNotEqual(compile_source(SOURCE)["program_digest"],
                            compile_source(SOURCE.replace('prices", 4', 'prices", 3'))["program_digest"])

    def test_duplicate_metrics_and_non_outcome_returns(self):
        self.reject(SOURCE.replace("measure unresolved: Int", "measure unresolved: Int = 1; measure unresolved: Int"), "F3209")
        self.reject(SOURCE.replace("return commit chosen to catalog", "return chosen"), "F3203")

    def test_runtime_requires_current_ir_schema(self):
        for version in (None, "0.0.1", "0.0.2", "0.0.4"):
            with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, "rebuild"):
                Runtime({"schema_version": version}, None)


if __name__ == "__main__":
    unittest.main()
