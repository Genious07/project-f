"""Frozen canonical bytes and structural identity rules for both compilers."""
import hashlib
import json
import unittest
from foresee.compiler import compile_source
from tools.check_identity import cases, validate


class IdentityFixtureTests(unittest.TestCase):
    def test_frozen_reference_bytes_and_digests(self):
        corpus = cases()
        self.assertEqual(len({c['name'] for c in corpus}), len(corpus))
        for case in corpus:
            with self.subTest(case=case['name']):
                ir = compile_source(case['source'])
                body = dict(ir)
                digest = body.pop('program_digest')
                canonical = json.dumps(body, sort_keys=True, separators=(',', ':'))
                validate(case, ir, canonical)
                self.assertTrue(canonical.isascii())
                self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)

    def test_object_insertion_order_does_not_change_identity(self):
        def reverse_maps(value):
            if isinstance(value, dict):
                return {k: reverse_maps(v) for k, v in reversed(list(value.items()))}
            if isinstance(value, (list, tuple)):
                return [reverse_maps(v) for v in value]
            return value
        for case in cases():
            with self.subTest(case=case['name']):
                ir = compile_source(case['source'])
                del ir['program_digest']
                self.assertEqual(json.dumps(reverse_maps(ir), sort_keys=True, separators=(',', ':')), case['canonical_json'])

    def test_statement_order_remains_part_of_identity(self):
        base = cases()[0]['source']
        first = base.replace('let base =', 'let a = 1; let b = 2; let base =')
        second = base.replace('let base =', 'let b = 2; let a = 1; let base =')
        self.assertNotEqual(compile_source(first)['program_digest'], compile_source(second)['program_digest'])


if __name__ == '__main__':
    unittest.main()
