"""Differential check for the explicitly staged native expression type analyzer."""
import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.compiler import Checker
from foresee.lexer import lex
from foresee.parser import parse
from foresee.model import CompileFailure, Expr, Statement

DECLARATIONS = {"F3200", "F3201", "F3000"}
# These rules are implemented by Python but are outside this native milestone.
DEFERRED = {"F3202", "F3001", "F3002", "F3207", "F3102", "F3104", "F3301", "F3400", "F3401"}


def cases():
    manifest = json.loads((ROOT / 'fixtures/types/cases.json').read_text())
    assert manifest['version'] == 1
    return manifest['cases']


def walk(value):
    if isinstance(value, Expr):
        yield value
        yield from walk(value.data)
    elif isinstance(value, Statement):
        yield from walk(value.data)
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from walk(item)


def reference(source):
    try:
        program = parse(lex(source))
    except CompileFailure as failure:
        return [{'code': d.code, 'span': asdict(d.span)} for d in failure.diagnostics], []
    checker = Checker(program)
    try:
        checker.check()
    except CompileFailure:
        pass
    declarations = [d for d in checker.diagnostics if d.code in DECLARATIONS]
    errors = declarations or [d for d in checker.diagnostics if d.code not in DEFERRED]
    diagnostics = [{'code': d.code, 'span': asdict(d.span)} for d in errors]
    if diagnostics:
        return diagnostics, []
    expressions = []
    for decision in program.decisions:
        for expr in walk(decision.body):
            ty = asdict(checker.types[id(expr)])
            ty['metric_names'] = list(ty['metric_names'])
            expressions.append({'node_id': len(expressions), 'op': expr.kind,
                                'span': asdict(expr.span), 'inferred_type': ty})
    return [], expressions


def validate_expectation(case, diagnostics):
    assert (not diagnostics) == case['types_ok'], (case['name'], diagnostics)
    for code in case.get('required_codes', []):
        assert code in [d['code'] for d in diagnostics], (case['name'], code, diagnostics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/debug/foresee-semantics')
    args = parser.parse_args()
    corpus = cases()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'case.fore'
        for case in corpus:
            diagnostics, expressions = reference(case['source'])
            validate_expectation(case, diagnostics)
            path.write_text(case['source'], encoding='utf-8')
            process = subprocess.run([str(args.binary.resolve()), 'types', str(path)], capture_output=True, text=True, timeout=10)
            assert process.returncode == (1 if diagnostics else 0), (case['name'], process.stderr, process.stdout)
            actual = json.loads(process.stdout)
            assert actual['checked_phase'] == 'types' and actual['executable'] is False
            assert actual['ok'] == (not diagnostics), case['name']
            if diagnostics:
                assert 'expressions' not in actual, case['name']
                observed = [{'code': d['code'], 'span': d['span']} for d in actual['diagnostics']]
                assert observed == diagnostics, (case['name'], observed, diagnostics)
            else:
                assert actual['expressions'] == expressions, (case['name'], actual['expressions'], expressions)
                assert all(e['inferred_type']['kind'] != 'error' for e in actual['expressions'])
    print(f'PASS: {len(corpus)} type fixtures match Python expression types, metadata, diagnostics, and source spans; effects/lineage validation/ownership remain deferred.')


if __name__ == '__main__':
    main()
