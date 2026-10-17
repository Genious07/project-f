"""Run the native compiler preview gate and retain per-step evidence."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def commands(python):
    yield 'format', ['cargo', 'fmt', '--all', '--check']
    yield 'rust-tests', ['cargo', 'test', '--workspace', '--locked']
    yield 'build', ['cargo', 'build', '--workspace', '--locked']
    for stage in ('frontends', 'declarations', 'types', 'effects', 'lineage', 'ownership', 'ir', 'identity', 'compilers', 'cli', 'lsp'):
        yield stage, [python, f'tools/check_{stage}.py']
    yield 'conformance-extended', [python, 'tools/check_compilers.py', '--seed', '451', '--count', '256', '--output', 'target/differential-extended']
    yield 'fuzz-smoke', [python, 'tools/fuzz_compiler.py']
    yield 'fuzz-extended', [python, 'tools/fuzz_compiler.py', '--seed', '913', '--count', '1024', '--output', 'target/fuzz-extended']


def run_gate(steps, output, provenance):
    output.mkdir(parents=True, exist_ok=True)
    report = {**provenance, 'scope': 'native-compiler-correctness',
              'publication_authorized': False, 'status': 'running', 'steps': []}
    def save():
        (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    for name, command in steps:
        started = time.monotonic()
        step = {'name': name, 'command': command, 'log': f'{name}.log'}
        print(f'Running {name}', flush=True)
        with (output / step['log']).open('w') as log:
            try:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600)
                step['exit_code'] = result.returncode
                step['status'] = 'passed' if result.returncode == 0 else 'failed'
            except (OSError, subprocess.TimeoutExpired) as error:
                step.update(status='failed', error=str(error))
            step['seconds'] = round(time.monotonic() - started, 3)
        report['steps'].append(step)
        if step['status'] == 'failed':
            report['status'] = 'failed'
            save()
            print(f'FAILED {name}: see {output / step["log"]}', file=sys.stderr)
            return 1
        save()
    report['status'] = 'passed'
    save()
    print(f'Passed {len(report["steps"])} native gates; evidence: {output / "summary.json"}')
    return 0


def main():
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    return run_gate(commands(sys.executable), ROOT / 'target/preview-gate',
                    {'source_commit': commit, 'source_dirty': dirty})


if __name__ == '__main__':
    sys.exit(main())
