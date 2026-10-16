"""Build a host-native preview archive and SPDX 2.3 Cargo dependency inventory."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foresee.compiler import compile_source

TARGETS = {'aarch64-apple-darwin', 'x86_64-unknown-linux-gnu'}
BINARIES = ('foresee-semantics', 'foresee-lsp')


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sbom(metadata, lock, stamp, name):
    packages = sorted(metadata['packages'], key=lambda p: p['id'])
    ids = {p['id']: f'SPDXRef-Package-{i}' for i, p in enumerate(packages)}
    checksums = {(p['name'], p['version']): p.get('checksum') for p in lock['package']}
    result = {
        'spdxVersion': 'SPDX-2.3', 'dataLicense': 'CC0-1.0',
        'SPDXID': 'SPDXRef-DOCUMENT', 'name': name,
        'creationInfo': {'created': stamp, 'creators': ['Tool: foresee-package-native']},
        'documentNamespace': 'https://spdx.org/spdxdocs/' + str(uuid.uuid4()),
        'documentComment': 'Cargo dependency graph including build dependencies. Not a binary linkage or OS library inventory. Project license is undeclared.',
        'packages': [], 'relationships': [],
    }
    for p in packages:
        registry = (p.get('source') or '').startswith('registry+')
        item = {'SPDXID': ids[p['id']], 'name': p['name'], 'versionInfo': p['version'],
                'downloadLocation': f"https://crates.io/api/v1/crates/{p['name']}/{p['version']}/download" if registry else 'NOASSERTION',
                'filesAnalyzed': False, 'licenseConcluded': 'NOASSERTION',
                'licenseDeclared': (p.get('license') or 'NOASSERTION').replace('/', ' OR '),
                'copyrightText': 'NOASSERTION'}
        if registry and checksums.get((p['name'], p['version'])):
            item['checksums'] = [{'algorithm': 'SHA256', 'checksumValue': checksums[p['name'], p['version']]}]
        result['packages'].append(item)
    for member in metadata['workspace_members']:
        result['relationships'].append({'spdxElementId': 'SPDXRef-DOCUMENT', 'relationshipType': 'DESCRIBES', 'relatedSpdxElement': ids[member]})
    for node in metadata['resolve']['nodes']:
        for dep in node['dependencies']:
            result['relationships'].append({'spdxElementId': ids[node['id']], 'relationshipType': 'DEPENDS_ON', 'relatedSpdxElement': ids[dep]})
    return result


def archive_bytes(files):
    """Stable container bytes for identical payloads; builds themselves may differ."""
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if name.startswith('bin/') else 0o644
                archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'release-dist/native')
    args = parser.parse_args()
    rustc = run('rustc', '-vV')
    target = next(line.split(': ', 1)[1] for line in rustc.splitlines() if line.startswith('host: '))
    if target not in TARGETS:
        parser.error(f'unsupported native target: {target}')
    subprocess.run(['cargo', 'build', '--workspace', '--release', '--locked', '--target', target], cwd=ROOT, check=True)
    metadata = json.loads(run('cargo', 'metadata', '--format-version', '1', '--locked', '--offline', '--filter-platform', target))
    version = next(p['version'] for p in metadata['packages'] if p['name'] == 'foresee-semantics')
    commit = run('git', 'rev-parse', 'HEAD')
    dirty = bool(run('git', 'status', '--porcelain'))
    name = f'foresee-native-{version}-{commit[:12]}-{target}'
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    source = (ROOT / 'examples/repair.fore').read_bytes()
    files = {f'bin/{binary}': (Path(metadata['target_directory']) / target / 'release' / binary).read_bytes() for binary in BINARIES}
    files.update({'examples/repair.fore': source, 'examples/repair.ir.json': encoded(compile_source(source.decode())),
                  'README.md': (ROOT / 'docs/native-distribution.md').read_bytes(),
                  'sbom.spdx.json': encoded(sbom(metadata, tomllib.loads((ROOT / 'Cargo.lock').read_text()), stamp, name))})
    files['manifest.json'] = encoded({'schema_version': 1, 'preview': True, 'version': version,
        'source_commit': commit, 'source_dirty': dirty, 'target': target, 'rustc': rustc,
        'created': stamp, 'sha256': {path: digest(data) for path, data in files.items()}})
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / (name + '.tar.gz')
    archive.write_bytes(archive_bytes(files))
    archive.with_suffix(archive.suffix + '.sha256').write_text(f'{digest(archive.read_bytes())}  {archive.name}\n')
    print(archive)


if __name__ == '__main__':
    main()
