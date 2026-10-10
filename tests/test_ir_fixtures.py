"""Reference IR corpus and wire-contract regression checks."""
import copy
import json
import unittest
from foresee.compiler import compile_source
from tools.check_ir import cases, validate, DEFERRED
from tools.check_types import reference
from tools.validate_ir import validate_ir_body


def body(source):
    value = json.loads(json.dumps(compile_source(source)))
    del value['program_digest']
    return value


class IrFixtureTests(unittest.TestCase):
    def test_reference_corpus(self):
        corpus = cases()
        self.assertEqual(len({c['name'] for c in corpus}), len(corpus))
        for case in corpus:
            with self.subTest(case=case['name']):
                diagnostics, _ = reference(case['source'], deferred=DEFERRED)
                validate(case, diagnostics)
                if not diagnostics:
                    validate_ir_body(body(case['source']))

    def test_metadata_and_effect_normalization(self):
        corpus = {c['name']: c for c in cases()}
        original = body(corpus['all_forms']['source'])
        for name in ('annotations_erased', 'duplicate_effects', 'reordered_effects', 'comments_crlf'):
            with self.subTest(case=name):
                self.assertEqual(original, body(corpus[name]['source']))

    def test_validator_rejects_broken_wire_documents(self):
        original = body(cases()[0]['source'])
        mutations = [
            lambda v: v.update(schema_version='0.0.2'),
            lambda v: v.update(program_digest='not-yet-supported'),
            lambda v: v['resources'][0].update(span={}),
            lambda v: v['decisions'][0]['effects'].reverse(),
            lambda v: v['decisions'][0]['body'][0].update(annotation='Int'),
            lambda v: v['decisions'][0]['body'][0]['value'].update(op='unknown'),
            lambda v: v['decisions'][0]['body'][0]['value'].pop('inferred_type'),
            lambda v: v['decisions'][0]['body'][0]['value']['inferred_type'].update(kind='error'),
            lambda v: v['decisions'][0]['body'][0]['value']['inferred_type'].update(metric_names=None),
            lambda v: v['decisions'][0]['body'][0]['value']['inferred_type'].update(lineage='snapshot:0'),
            lambda v: v['decisions'][0]['body'][1]['value']['args'][2].update(value=True),
            lambda v: v['decisions'][0]['body'][1]['value'].update(args=None),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                value = copy.deepcopy(original)
                mutate(value)
                with self.assertRaises(ValueError):
                    validate_ir_body(value)


if __name__ == '__main__':
    unittest.main()
