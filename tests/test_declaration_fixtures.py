"""Reference expectations for the staged native declaration corpus."""
import unittest
from tools.check_declarations import cases, reference


class DeclarationFixtureTests(unittest.TestCase):
    def test_reference_declaration_diagnostics(self):
        corpus = cases()
        self.assertEqual(len({case['name'] for case in corpus}), len(corpus))
        for case in corpus:
            with self.subTest(case=case['name']):
                diagnostics, _ = reference(case['source'])
                self.assertEqual([d['code'] for d in diagnostics], case['codes'])


if __name__ == '__main__':
    unittest.main()
