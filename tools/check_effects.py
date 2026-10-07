"""Native type/effect parity; origin and affine checks remain explicitly deferred."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_types import reference, cases as type_cases

DEFERRED = {'F3104', 'F3301', 'F3400', 'F3401'}


def cases():
    manifest = json.loads((ROOT / 'fixtures/effects/cases.json').read_text())
    assert manifest['version'] == 1
    return manifest['cases']


def validate(case, diagnostics):
    assert bool(diagnostics) != case['effects_ok'], (case['name'], diagnostics)
    codes = [d['code'] for d in diagnostics]
    for code in case.get('required_codes', []):
        assert code in codes, (case['name'], code, diagnostics)
    for code, count in case.get('counts', {}).items():
        assert codes.count(code) == count, (case['name'], code, codes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/debug/foresee-semantics')
    args = parser.parse_args()
    effect_cases = cases()
    corpus = effect_cases + type_cases()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'case.fore'
        for case in corpus:
            diagnostics, expressions = reference(case['source'], deferred=DEFERRED)
            if 'effects_ok' in case:
                validate(case, diagnostics)
            path.write_text(case['source'], encoding='utf-8')
            process = subprocess.run([str(args.binary.resolve()), 'effects', str(path)], capture_output=True, text=True, timeout=10)
            assert process.returncode == (1 if diagnostics else 0), (case['name'], process.stderr, process.stdout)
            actual = json.loads(process.stdout)
            assert actual['checked_phase'] == 'effects' and actual['executable'] is False
            assert actual['ok'] == (not diagnostics), case['name']
            if diagnostics:
                assert 'expressions' not in actual
                observed = [{'code': d['code'], 'span': d['span']} for d in actual['diagnostics']]
                # Invalid declared effects all share the decision span, so Python's
                # set iteration order cannot change this code/span sequence.
                assert observed == diagnostics, (case['name'], observed, diagnostics)
            else:
                assert actual['expressions'] == expressions, (case['name'], actual, expressions)
    print(f'PASS: {len(effect_cases)} effect cases plus {len(corpus)-len(effect_cases)} type regressions match Python diagnostics and types. Origin and ownership checks remain deferred.')


if __name__ == '__main__':
    main()
