import unittest
from tools.check_frontends import cases, python_result
from foresee.compiler import compile_source
from foresee.model import CompileFailure


class SyntaxFixtureTests(unittest.TestCase):
    def test_shared_fixtures_match_reference_expectations(self):
        for case, source in cases():
            with self.subTest(case=case["name"]):
                self.assertEqual(python_result(source, "parse")["ok"], case["parse_ok"])
                if "semantic_ok" in case:
                    try:
                        compile_source(source)
                        accepted = True
                    except CompileFailure:
                        accepted = False
                    self.assertEqual(accepted, case["semantic_ok"])
