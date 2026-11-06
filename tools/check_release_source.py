"""Read-only release source preflight. Passing never authorizes publication."""
import argparse
import json
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def inspect_source(root, *, python_version, native_version, license_id, commit, dirty, tracked):
    checks = []
    def check(name, passed, detail):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})
    def read(name):
        try:
            return tomllib.loads((root / name).read_text())
        except (OSError, ValueError):
            check('metadata:' + name, False, 'missing or invalid TOML')
            return {}

    check('clean_checkout', not dirty, 'working tree must match the recorded commit')
    check('license_selected', bool(license_id), 'operator must explicitly select the project license')
    license_path = root / 'LICENSE'
    check('license_file', license_path.is_file() and not license_path.is_symlink()
          and 'LICENSE' in tracked and bool(license_path.read_text().strip()) if license_path.is_file() else False,
          'nonempty tracked LICENSE required; legal text correctness needs human review')
    project = read('pyproject.toml').get('project', {})
    check('python_version', project.get('version') == python_version, f'expected {python_version}')
    check('python_license', bool(license_id) and project.get('license') == license_id,
          'project.license must equal the selected SPDX expression')
    license_files = project.get('license-files', [])
    check('python_license_files', type(license_files) is list and 'LICENSE' in license_files,
          'project.license-files must explicitly include LICENSE')
    workspace = read('Cargo.toml').get('workspace', {})
    members = workspace.get('members', [])
    check('workspace_members', bool(members) and isinstance(members, list), 'explicit workspace member paths required')
    lock = read('Cargo.lock').get('package', [])
    for member in members if isinstance(members, list) else []:
        # This repository uses explicit local members, not globs/inherited metadata.
        if not isinstance(member, str) or '*' in member or Path(member).is_absolute() or '..' in Path(member).parts:
            check('workspace_member', False, 'unsupported workspace member path')
            continue
        package = read(member + '/Cargo.toml').get('package', {})
        check(member + ':version', package.get('version') == native_version, f'expected {native_version}')
        check(member + ':license', bool(license_id) and package.get('license') == license_id,
              'package.license must equal the selected SPDX expression')
        versions = [item.get('version') for item in lock if item.get('name') == package.get('name')]
        check(member + ':lock', versions == [native_version], 'Cargo.lock must contain the exact workspace version')
    return {'schema_version': 1, 'source_commit': commit, 'source_ready': all(c['passed'] for c in checks),
            'publication_authorized': False, 'checks': checks,
            'remaining_manual_gates': ['review license text and notices',
                                       'verify LICENSE/notices in wheel, source, and both native archives',
                                       'require every Verify job on this exact commit to pass',
                                       'inspect artifact provenance and checksums before publication']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-version', required=True)
    parser.add_argument('--native-version', required=True)
    parser.add_argument('--license-id', help='operator-selected SPDX expression; omission fails the preflight')
    args = parser.parse_args(argv)
    try:
        def git(*words):
            return subprocess.check_output(['git', *words], cwd=ROOT, text=True).strip()
        result = inspect_source(ROOT, python_version=args.python_version, native_version=args.native_version,
                                license_id=args.license_id, commit=git('rev-parse', 'HEAD'),
                                dirty=bool(git('status', '--porcelain')), tracked=set(git('ls-files').splitlines()))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result['source_ready'] else 1
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        print(json.dumps({'source_ready': False, 'publication_authorized': False, 'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
