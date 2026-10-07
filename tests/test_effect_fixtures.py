"""Reference expectations for native effect conformance cases."""
import unittest
from tools.check_effects import cases, validate, DEFERRED
from tools.check_types import reference


class EffectFixtureTests(unittest.TestCase):
    def test_reference_effect_expectations(self):
        corpus = cases()
        self.assertEqual(len({c['name'] for c in corpus}), len(corpus))
        for case in corpus:
            with self.subTest(case=case['name']):
                diagnostics, _ = reference(case['source'], deferred=DEFERRED)
                validate(case, diagnostics)


if __name__ == '__main__':
    unittest.main()
