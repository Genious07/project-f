"""Compare native checked IR bodies with Python schema 0.0.3."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_types import reference, cases as type_cases
from tools.check_effects import cases as effect_cases
from tools.check_lineage import cases as prior_lineage_cases
from tools.check_ownership import cases as ownership_cases
from tools.validate_ir import validate_ir_body
from foresee.compiler import compile_source

DEFERRED = set()


def cases():
    manifest = json.loads((ROOT / 'fixtures/ir/cases.json').read_text())
    assert manifest['version'] == 1
    return manifest['cases']


def validate(case, diagnostics):
    assert bool(diagnostics) != case['ir_ok'], (case['name'], diagnostics)
    codes = [d['code'] for d in diagnostics]
    for code in case.get('required_codes', []):
        assert code in codes, (case['name'], code, diagnostics)
    for code, count in case.get('counts', {}).items():
        assert codes.count(code) == count, (case['name'], code, codes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/debug/foresee-semantics')
    args = parser.parse_args()
    ir_cases = cases()
    corpus = ir_cases + ownership_cases() + prior_lineage_cases() + effect_cases() + type_cases()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'case.fore'
        for case in corpus:
            diagnostics, expressions = reference(case['source'], deferred=DEFERRED)
            if 'ir_ok' in case:
                validate(case, diagnostics)
            path.write_text(case['source'], encoding='utf-8')
            process = subprocess.run([str(args.binary.resolve()), 'ir', str(path)], capture_output=True, text=True, timeout=10)
            assert process.returncode == (1 if diagnostics else 0), (case['name'], process.stderr, process.stdout)
            actual = json.loads(process.stdout)
            assert actual['checked_phase'] == 'ir' and actual['executable'] is False
            assert actual['ok'] == (not diagnostics), case['name']
            if diagnostics:
                assert 'ir' not in actual and 'expressions' not in actual
                observed = [{'code': d['code'], 'span': d['span']} for d in actual['diagnostics']]
                # Invalid declared effects all share the decision span, so Python's
                # set iteration order cannot change this code/span sequence.
                assert observed == diagnostics, (case['name'], observed, diagnostics)
            else:
                expected = json.loads(json.dumps(compile_source(case['source'])))
                expected.pop('program_digest')
                validate_ir_body(actual['ir'])
                assert actual['ir'] == expected, (case['name'], actual, expected)
    print(f'PASS: {len(ir_cases)} IR cases and {len(corpus)-len(ir_cases)} regressions match Python; successful IR bodies pass structural validation.')


if __name__ == '__main__':
    main()
