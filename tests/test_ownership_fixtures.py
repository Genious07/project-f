"""Reference expectations for native selection ownership checks."""
import unittest
from tools.check_ownership import cases, validate, DEFERRED
from tools.check_types import reference


class OwnershipFixtureTests(unittest.TestCase):
    def test_reference_ownership_expectations(self):
        corpus = cases()
        self.assertEqual(len({c['name'] for c in corpus}), len(corpus))
        for case in corpus:
            with self.subTest(case=case['name']):
                diagnostics, _ = reference(case['source'], deferred=DEFERRED)
                validate(case, diagnostics)


if __name__ == '__main__':
    unittest.main()
