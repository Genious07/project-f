"""End-to-end native/reference differential harness with replayable failures."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.compiler import compile_source
from tools.check_frontends import python_result
from tools.check_types import reference
from tools.generated_programs import generate
from tools.validate_ir import validate_ir_body

GROUPS = ('syntax', 'declarations', 'types', 'effects', 'lineage', 'ownership', 'ir', 'identity', 'regressions')
STAGES = ('lex', 'parse', 'ownership', 'identity')


def corpus():
    """Deduplicate exact source bytes, preserving all fixture labels."""
    by_source = {}
    for group in GROUPS:
        manifest = json.loads((ROOT / 'fixtures' / group / 'cases.json').read_text())
        if manifest['version'] != 1:
            raise ValueError(f'unsupported fixture version: {group}')
        for case in manifest['cases']:
            source = (ROOT / case['base']).read_text() if 'base' in case else case['source']
            for before, after in case.get('replace', []):
                source = source.replace(before, after)
            label = f"{group}/{case['name']}"
            if source in by_source:
                by_source[source]['labels'].append(label)
            else:
                by_source[source] = {'name': label, 'labels': [label], 'source': source}
            if group == 'regressions':
                by_source[source].update(expected_ok=case['expected_ok'], required_code=case.get('required_code'))
    return list(by_source.values())


def expected(source):
    results = {stage: python_result(source, stage) for stage in ('lex', 'parse')}
    diagnostics, expressions = reference(source, deferred=set())
    for stage in ('ownership', 'identity'):
        results[stage] = {'ok': not diagnostics, 'checked_phase': stage, 'executable': False}
        if diagnostics:
            results[stage]['diagnostics'] = diagnostics
    if not diagnostics:
        results['ownership']['expressions'] = expressions
        ir = json.loads(json.dumps(compile_source(source)))
        body = dict(ir)
        body.pop('program_digest')
        results['identity'].update(ir=ir, canonical_json=json.dumps(body, sort_keys=True, separators=(',', ':')))
    for result in results.values():
        if not result['ok']:
            result['diagnostics'] = [{'code': d['code'], 'span': d['span']} for d in result['diagnostics']]
    return results


class Native:
    def __init__(self, syntax, semantics, path):
        self.syntax, self.semantics, self.path = syntax, semantics, path

    def __call__(self, stage, source):
        self.path.write_bytes(source.encode('utf-8'))
        binary = self.syntax if stage in ('lex', 'parse') else self.semantics
        process = subprocess.run([str(binary), stage, str(self.path)], capture_output=True, text=True, timeout=10)
        return process.returncode, process.stdout, process.stderr


def compare(source, native):
    """Return first mismatch with stable category and complete comparison evidence."""
    try:
        wanted = expected(source)
    except Exception as error:
        return {'stage': 'reference', 'category': 'exception', 'detail': repr(error)}
    for stage in STAGES:
        want = wanted[stage]
        try:
            code, stdout, stderr = native(stage, source)
        except (OSError, subprocess.TimeoutExpired) as error:
            return {'stage': stage, 'category': 'process', 'detail': repr(error)}
        evidence = {'stage': stage, 'expected': want, 'exit_code': code, 'stdout': stdout, 'stderr': stderr}
        if code != (0 if want['ok'] else 1):
            return dict(evidence, category='exit_code')
        try:
            actual = json.loads(stdout)
            if type(actual) is not dict or type(actual.get('ok')) is not bool:
                raise ValueError('invalid response envelope')
            if actual['ok'] != want['ok']:
                return dict(evidence, category='acceptance')
            if not actual['ok']:
                if any(key in actual for key in ('ir', 'canonical_json', 'expressions')):
                    return dict(evidence, category='artifact_on_error')
                actual['diagnostics'] = [{'code': d['code'], 'span': d['span']} for d in actual['diagnostics']]
            for field, value in want.items():
                if actual.get(field) != value:
                    return dict(evidence, category=field, actual=actual)
            if stage == 'identity' and actual['ok']:
                body = dict(actual['ir'])
                digest = body.pop('program_digest')
                validate_ir_body(body)
                if hashlib.sha256(actual['canonical_json'].encode()).hexdigest() != digest:
                    return dict(evidence, category='digest_preimage')
        except (ValueError, KeyError, TypeError) as error:
            return dict(evidence, category='protocol', detail=repr(error))
    return None


def minimize(source, native, failure, budget=40):
    """Bounded line deletion preserving mismatch category and reference acceptance."""
    signature = (failure['stage'], failure['category'])
    if signature[1] in ('process', 'protocol', 'exit_code', 'exception'):
        return source  # Infrastructure failures are not language regressions.
    original_ok = expected(source)['identity']['ok']
    lines = source.splitlines(keepends=True)
    attempts = 0
    index = 0
    while index < len(lines) and attempts < budget:
        candidate = ''.join(lines[:index] + lines[index + 1:])
        attempts += 1
        if expected(candidate)['identity']['ok'] == original_ok:
            observed = compare(candidate, native)
            if observed and (observed['stage'], observed['category']) == signature:
                lines.pop(index)
                continue
        index += 1
    return ''.join(lines)


def save_failure(directory, case, failure, source):
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(case['source'].encode()).hexdigest()[:16]
    (directory / f'{key}.fore').write_bytes(source.encode())
    (directory / f'{key}.json').write_text(json.dumps({'case': case, 'failure': failure, 'replay_source': source}, indent=2) + '\n')
    return str(directory / f'{key}.fore')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--syntax', type=Path, default=ROOT / 'target/debug/foresee-syntax')
    parser.add_argument('--semantics', type=Path, default=ROOT / 'target/debug/foresee-semantics')
    parser.add_argument('--seed', type=int, default=20261012)
    parser.add_argument('--count', type=int, default=64, help='generated valid/invalid pairs (0..1000)')
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'target/differential')
    parser.add_argument('--minimize', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.count <= 1000:
        parser.error('--count must be between 0 and 1000')
    cases = ([{'name': 'replay', 'source': args.replay.read_bytes().decode('utf-8')}] if args.replay
             else corpus() + list(generate(args.seed, args.count)))
    failures = []
    accepted = 0
    processed = 0
    with tempfile.TemporaryDirectory() as directory:
        native = Native(args.syntax.resolve(), args.semantics.resolve(), Path(directory) / 'case.fore')
        for case in cases:
            processed += 1
            failure = compare(case['source'], native)
            result = expected(case['source'])['identity'] if not failure else None
            if not failure and 'expected_ok' in case:
                codes = [d['code'] for d in result.get('diagnostics', [])]
                if result['ok'] != case['expected_ok'] or (case.get('required_code') and case['required_code'] not in codes):
                    failure = {'stage': 'generator', 'category': 'expectation', 'actual': result}
            if failure:
                source = minimize(case['source'], native, failure) if args.minimize and failure['stage'] != 'generator' else case['source']
                path = save_failure(args.output, case, failure, source)
                failures.append({'name': case['name'], 'stage': failure['stage'], 'category': failure['category'], 'replay': path})
                if len(failures) >= 5:
                    break
            else:
                accepted += result['ok']
    summary = {'seed': args.seed, 'planned': len(cases), 'processed': processed, 'accepted': accepted,
               'rejected': processed - len(failures) - accepted, 'failures': failures,
               'status': 'failed' if failures else 'passed', 'stages': list(STAGES)}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
