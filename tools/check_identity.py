"""Compare canonical bytes and complete native IR identity with Python."""
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
from tools.check_ir import cases as prior_ir_cases
import hashlib
from foresee.compiler import compile_source

DEFERRED = set()


def cases():
    manifest = json.loads((ROOT / 'fixtures/identity/cases.json').read_text())
    assert manifest['version'] == 1
    return manifest['cases']


def validate(case, ir, canonical):
    assert canonical == case['canonical_json'], case['name']
    assert ir['program_digest'] == case['program_digest'], case['name']
    baseline = cases()[0]['program_digest']
    assert (ir['program_digest'] == baseline) == (case['identity'] == 'same'), case['name']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/debug/foresee-semantics')
    args = parser.parse_args()
    identity_cases = cases()
    corpus = identity_cases + prior_ir_cases() + ownership_cases() + prior_lineage_cases() + effect_cases() + type_cases()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'case.fore'
        for case in corpus:
            diagnostics, expressions = reference(case['source'], deferred=DEFERRED)
            path.write_text(case['source'], encoding='utf-8')
            process = subprocess.run([str(args.binary.resolve()), 'identity', str(path)], capture_output=True, text=True, timeout=10)
            assert process.returncode == (1 if diagnostics else 0), (case['name'], process.stderr, process.stdout)
            actual = json.loads(process.stdout)
            assert actual['checked_phase'] == 'identity' and actual['executable'] is False
            assert actual['ok'] == (not diagnostics), case['name']
            if diagnostics:
                assert 'ir' not in actual and 'canonical_json' not in actual
                observed = [{'code': d['code'], 'span': d['span']} for d in actual['diagnostics']]
                # Invalid declared effects all share the decision span, so Python's
                # set iteration order cannot change this code/span sequence.
                assert observed == diagnostics, (case['name'], observed, diagnostics)
            else:
                expected = json.loads(json.dumps(compile_source(case['source'])))
                body = dict(actual['ir'])
                digest = body.pop('program_digest')
                validate_ir_body(body)
                expected_body = dict(expected)
                expected_body.pop('program_digest')
                canonical = json.dumps(expected_body, sort_keys=True, separators=(',', ':'))
                assert actual['canonical_json'] == canonical, case['name']
                assert hashlib.sha256(canonical.encode()).hexdigest() == digest, case['name']
                if 'identity' in case:
                    validate(case, actual['ir'], canonical)
                assert actual['ir'] == expected, (case['name'], actual, expected)
    print(f'PASS: {len(identity_cases)} identity goldens and {len(corpus)-len(identity_cases)} regressions match Python canonical bytes, digests, IR, and rejection diagnostics.')


if __name__ == '__main__':
    main()
