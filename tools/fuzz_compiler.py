"""Bounded seeded mutation campaign for native compiler crash/resource smoke tests."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import resource
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.compiler import compile_source
from tools.generated_programs import generate
from tools.validate_ir import validate_ir_body

STAGES = ('lex', 'parse', 'ownership', 'identity')
OUTPUT_LIMIT = 16 * 1024 * 1024


def cases(seed, count):
    base = (ROOT / 'examples/repair.fore').read_bytes()
    def case(name, data, code=None):
        return {'name': name, 'data': data, 'code': code}
    yield case('example', base)
    yield case('valid-source-at-limit', base + b' ' * (1_000_000 - len(base)))
    yield case('valid-string-at-limit', base.replace(b'Fill only derived unit prices', b'a' * 65536))
    yield case('valid-integer-at-limit', base.replace(b'let base =', b'let big = ' + b'9' * 4096 + b'; let base ='))
    metrics = b' '.join(b'measure ' + b'm' * 120 + str(i).encode() + b': Int = catalog.unresolved_units(after);' for i in range(100))
    metadata = base.replace(b'measure unresolved:', metrics + b' measure unresolved:')
    aliases = b' '.join(b'let trial_alias' + str(i).encode() + b' = trials;' for i in range(100))
    yield case('valid-metric-metadata-growth', metadata.replace(b'let chosen =', aliases + b' let chosen ='))
    yield case('invalid-utf8', b'\xff\xfe', 2)
    yield case('source-at-limit', b' ' * 1_000_000)
    yield case('source-over-limit', b' ' * 1_000_001, 2)
    yield case('token-over-limit', b'x ' * 8193, 1)
    yield case('identifier-over-limit', b'a' * 129, 1)
    yield case('integer-over-limit', b'9' * 4097, 1)
    yield case('string-over-limit', b'"' + b'a' * 65537 + b'"', 1)
    yield case('diagnostic-flood', b'@' * 10000, 1)
    yield case('escape-flood', b'"' + b'\\q' * 10000 + b'"', 1)
    yield case('declaration-flood', b'resource r: Wrong;' * 129)
    yield case('statement-flood', b'decision d() ! {} {' + b'let a = 1;' * 129 + b'}')
    yield case('argument-flood', b'decision d() ! {} {return c.f(' + b'1,' * 128 + b'1);}')
    yield case('effect-flood', b'decision d() ! {' + b'Snapshot(c),' * 129 + b'} {return 1;}')
    for depth in (15, 16, 128, 1000):
        yield case(f'nested-calls-{depth}', b'decision d() ! {} {return ' + b'c.f(' * depth + b'x' + b')' * depth + b';}')
    for depth in (15, 16, 100):
        yield case(f'nested-explorations-{depth}', b'decision d() ! {} {return ' + b'explore p in x from y {let a = ' * depth + b'1' + b';}' * depth + b';}')
    for generated in generate(seed, 16):
        yield case(generated['name'], generated['source'].encode())
    rng = random.Random(seed)
    for index in range(count):
        data = bytearray(base if index % 2 else rng.randbytes(rng.randrange(512)))
        for _ in range(rng.randrange(1, 9)):
            start = rng.randrange(len(data) + 1)
            stop = min(len(data), start + rng.randrange(24))
            data[start:stop] = rng.choice([b'', b'\x00', b'"', b'{}', b'\\', b'select ', b'\xff', rng.randbytes(rng.randrange(12))])
        yield case(f'mutation-{seed}-{index}', bytes(data))


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))


def validate(code, stdout, stderr, stage, data, required=None):
    if code not in (0, 1, 2) or (required is not None and code != required):
        raise ValueError(f'unexpected exit {code}, expected {required}')
    if code == 2:
        # Valid UTF-8 within the source budget must never fail internally.
        try:
            data.decode('utf-8')
            valid_utf8 = True
        except UnicodeDecodeError:
            valid_utf8 = False
        if valid_utf8 and len(data) <= 1_000_000:
            raise ValueError('internal error for bounded UTF-8 input')
        if stdout or not stderr:
            raise ValueError('bad input-error response')
        return
    result = json.loads(stdout)
    if type(result.get('ok')) is not bool or result['ok'] != (code == 0):
        raise ValueError('bad response envelope')
    if code == 1:
        diagnostics = result['diagnostics']
        if not 1 <= len(diagnostics) <= 64:
            raise ValueError('unbounded/empty diagnostics')
        if any(k in result for k in ('ir', 'canonical_json', 'expressions')):
            raise ValueError('artifact leaked on rejection')
    elif stage == 'identity':
        ir = result['ir']
        body = dict(ir)
        digest = body.pop('program_digest')
        validate_ir_body(body)
        canonical = json.dumps(body, sort_keys=True, separators=(',', ':'))
        if result['canonical_json'] != canonical or hashlib.sha256(canonical.encode()).hexdigest() != digest:
            raise ValueError('invalid canonical identity')
        if ir != json.loads(json.dumps(compile_source(data.decode('utf-8')))):
            raise ValueError('accepted IR differs from Python')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=20261013)
    parser.add_argument('--count', type=int, default=256)
    parser.add_argument('--binary-dir', type=Path, default=ROOT / 'target/debug')
    parser.add_argument('--output', type=Path, default=ROOT / 'target/fuzz-smoke')
    args = parser.parse_args()
    if not 0 <= args.count <= 5000:
        parser.error('--count must be in 0..5000')
    args.output.mkdir(parents=True, exist_ok=True)
    executions = 0
    failures = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'input.fore'
        for case in cases(args.seed, args.count):
            path.write_bytes(case['data'])
            for stage in STAGES:
                binary = args.binary_dir / ('foresee-syntax' if stage in ('lex', 'parse') else 'foresee-semantics')
                executions += 1
                try:
                    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                        process = subprocess.run([str(binary.resolve()), stage, str(path)], stdout=out, stderr=err,
                                                 timeout=5, preexec_fn=limits)
                        if out.tell() > OUTPUT_LIMIT or err.tell() > OUTPUT_LIMIT:
                            raise ValueError('output budget exceeded')
                        out.seek(0); err.seek(0)
                        validate(process.returncode, out.read().decode(), err.read().decode(), stage, case['data'], case['code'])
                except Exception as error:
                    key = hashlib.sha256(case['data']).hexdigest()[:16]
                    (args.output / f'{key}.fore').write_bytes(case['data'])
                    failures.append({'name': case['name'], 'stage': stage, 'error': repr(error), 'source': f'{key}.fore'})
            if failures:
                break
    summary = {'seed': args.seed, 'mutations': args.count, 'executions': executions, 'failures': failures}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
