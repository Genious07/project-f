"""Test the smoke runner's deterministic inputs and rejection of broken results."""
import json
import unittest
from tools.fuzz_compiler import cases, validate
from foresee.compiler import compile_source


class FuzzSmokeTests(unittest.TestCase):
    def test_reproducible_bytes_and_boundary_cases(self):
        first = list(cases(17, 8))
        self.assertEqual(first, list(cases(17, 8)))
        self.assertNotEqual(first, list(cases(18, 8)))
        self.assertTrue(any(c['data'] == b'\xff\xfe' for c in first))
        self.assertTrue(any(len(c['data']) > 1_000_000 for c in first))

    def test_crashes_internal_errors_and_diagnostic_floods_fail(self):
        with self.assertRaises(ValueError):
            validate(-6, '', 'abort', 'parse', b'')
        with self.assertRaises(ValueError):
            validate(2, '', 'internal error', 'identity', b'valid utf8')
        with self.assertRaises(ValueError):
            validate(1, json.dumps({'ok': False, 'diagnostics': [{}] * 65}), '', 'parse', b'@')
        validate(2, '', 'invalid utf8', 'parse', b'\xff')
        validate(2, '', 'oversized', 'parse', b' ' * 1_000_001)

    def test_successful_ir_is_checked_and_artifacts_cannot_leak(self):
        source = next(cases(1, 0))['data']
        ir = compile_source(source.decode())
        body = dict(ir)
        body.pop('program_digest')
        value = {'ok': True, 'ir': ir, 'canonical_json': json.dumps(body, sort_keys=True, separators=(',', ':'))}
        validate(0, json.dumps(value), '', 'identity', source)
        value['ir']['program_digest'] = '0' * 64
        with self.assertRaises(ValueError):
            validate(0, json.dumps(value), '', 'identity', source)
        with self.assertRaises(ValueError):
            validate(1, json.dumps({'ok': False, 'diagnostics': [{}], 'ir': {}}), '', 'identity', source)
