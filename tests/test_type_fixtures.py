"""Reference expectations for the staged native type corpus."""
import unittest
from tools.check_types import cases, reference, validate_expectation


class TypeFixtureTests(unittest.TestCase):
    def test_reference_types_and_diagnostic_expectations(self):
        corpus = cases()
        self.assertEqual(len({c['name'] for c in corpus}), len(corpus))
        for case in corpus:
            with self.subTest(case=case['name']):
                diagnostics, expressions = reference(case['source'])
                validate_expectation(case, diagnostics)
                if case['types_ok']:
                    self.assertTrue(expressions)
                    self.assertEqual([e['node_id'] for e in expressions], list(range(len(expressions))))
                    self.assertTrue(all(e['inferred_type']['kind'] != 'error' for e in expressions))


if __name__ == '__main__':
    unittest.main()
