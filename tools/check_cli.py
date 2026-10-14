"""Check public native CLI semantics with a standalone binary and empty PATH."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.compiler import compile_source
from tools.check_compilers import corpus
from tools.check_types import reference
from tools.generated_programs import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT / 'target/debug/foresee-semantics')
    args = parser.parse_args()
    cases = corpus() + list(generate(20261014, 16))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        binary = root / 'compiler'
        shutil.copy2(args.binary, binary)
        source = root / 'input.fore'
        for index, case in enumerate(cases):
            source.write_bytes(case['source'].encode())
            diagnostics, _ = reference(case['source'], deferred=set())
            destination = root / f'{index}.json'
            for command in ('check', 'build'):
                argv = [str(binary), command, str(source), '--format', 'json']
                if command == 'build':
                    argv += ['-o', str(destination)]
                result = subprocess.run(argv, cwd=root, env={'PATH': ''}, capture_output=True, text=True, timeout=10)
                assert result.returncode == (1 if diagnostics else 0), (case['name'], command, result.stdout, result.stderr)
                assert not result.stderr, (case['name'], result.stderr)
                value = json.loads(result.stdout)
                assert value['ok'] == (not diagnostics) and value['command'] == command
                if diagnostics:
                    assert not destination.exists(), case['name']
                    assert [{'code': d['code'], 'span': d['span']} for d in value['diagnostics']] == diagnostics, case['name']
                    assert 'ir' not in value, case['name']
            if not diagnostics:
                actual = json.loads(destination.read_text())
                expected = json.loads(json.dumps(compile_source(case['source'])))
                assert actual == expected, case['name']
        assert not list(root.glob('.foresee-*.tmp'))
    print(f'PASS: {len(cases)} cases through check and build with empty PATH; output matches Python.')


if __name__ == '__main__':
    main()
