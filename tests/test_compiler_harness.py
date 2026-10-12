"""Exercise reproducibility and deliberate compiler divergence without Rust."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.check_compilers import compare, corpus, expected, minimize, save_failure
from tools.generated_programs import generate


class CompilerHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valid, cls.invalid = list(generate(73, 1))

    def oracle(self, mutate=None):
        def call(stage, source):
            value = copy.deepcopy(expected(source)[stage])
            if mutate:
                mutate(stage, value)
            return (0 if value['ok'] else 1), json.dumps(value), ''
        return call

    def test_seeded_generation_and_error_families(self):
        cases = list(generate(42, 16))
        self.assertEqual(cases, list(generate(42, 16)))
        self.assertNotEqual(cases, list(generate(43, 16)))
        codes = set()
        for case in cases:
            result = expected(case['source'])['identity']
            self.assertEqual(result['ok'], case['expected_ok'])
            if not result['ok']:
                self.assertIn(case['required_code'], [d['code'] for d in result['diagnostics']])
                codes.add(case['required_code'])
        self.assertEqual(len(codes), 8)

    def test_corpus_sources_are_unique_and_labels_retained(self):
        cases = corpus()
        self.assertEqual(len(cases), len({c['source'] for c in cases}))
        self.assertTrue(any(len(c['labels']) > 1 for c in cases))

    def test_matching_protocol_passes_for_valid_and_invalid(self):
        for case in (self.valid, self.invalid):
            self.assertIsNone(compare(case['source'], self.oracle()))

    def test_types_and_digest_differences_are_detected(self):
        def bad_type(stage, value):
            if stage == 'ownership':
                value['expressions'][0]['inferred_type']['kind'] = 'bool'
        self.assertEqual(compare(self.valid['source'], self.oracle(bad_type))['category'], 'expressions')
        def bad_digest(stage, value):
            if stage == 'identity':
                value['ir']['program_digest'] = '0' * 64
        self.assertEqual(compare(self.valid['source'], self.oracle(bad_digest))['category'], 'ir')

    def test_diagnostic_locations_and_artifacts_on_error_are_detected(self):
        def bad_span(stage, value):
            if stage == 'ownership':
                value['diagnostics'][0]['span']['start'] += 1
        self.assertEqual(compare(self.invalid['source'], self.oracle(bad_span))['category'], 'diagnostics')
        def leak(stage, value):
            if stage == 'identity':
                value['ir'] = {}
        self.assertEqual(compare(self.invalid['source'], self.oracle(leak))['category'], 'artifact_on_error')

    def test_process_protocol_and_timeout_failures(self):
        self.assertEqual(compare(self.valid['source'], lambda *_: (9, '', 'crash'))['category'], 'exit_code')
        self.assertEqual(compare(self.valid['source'], lambda *_: (0, 'not-json', ''))['category'], 'protocol')
        def timeout(*_):
            raise subprocess.TimeoutExpired('fake', 10)
        self.assertEqual(compare(self.valid['source'], timeout)['category'], 'process')

    def test_reduction_and_replay_evidence(self):
        def defect(stage, value):
            if stage == 'identity' and value['ok']:
                value['canonical_json'] += ' '
        source = '// removable\n' + self.valid['source']
        native = self.oracle(defect)
        failure = compare(source, native)
        reduced = minimize(source, native, failure)
        self.assertLess(len(reduced), len(source))
        self.assertTrue(expected(reduced)['identity']['ok'])
        self.assertEqual(compare(reduced, native)['category'], failure['category'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(save_failure(Path(directory), {'name': 'injected', 'source': source}, failure, reduced))
            self.assertEqual(path.read_bytes().decode(), reduced)
            report = json.loads(path.with_suffix('.json').read_text())
            self.assertEqual(report['case']['source'], source)
            self.assertEqual(report['replay_source'], reduced)


if __name__ == '__main__':
    unittest.main()
