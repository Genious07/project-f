"""Read-only project package version/license checks. Never extracts or executes."""
import argparse
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.package_native import legal_files

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_MEMBERS = 10_000
MAX_TEXT = 2_000_000
NAME = 'project-f-bootstrap'


def safe_name(name):
    parts = name.rstrip('/').split('/')
    if not name or '\\' in name or any(part in ('', '.', '..') for part in parts):
        raise ValueError('unsafe archive path')
    return '/'.join(parts)


def inspect_package(path, *, version, license_id, expected_legal):
    if not version or not license_id or 'LICENSE' not in expected_legal:
        raise ValueError('explicit version, license, and expected LICENSE bytes required')
    if set(expected_legal) - {'LICENSE', 'NOTICE'} or any(type(v) is not bytes or not v.strip() or len(v) > MAX_TEXT for v in expected_legal.values()):
        raise ValueError('invalid expected legal files')
    with path.open('rb') as source:
        raw = source.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('compressed archive exceeds limit')
    wheel = path.name.endswith('.whl')
    if not wheel and not path.name.endswith('.tar.gz'):
        raise ValueError('expected wheel or tar.gz source distribution')
    prefix = 'project_f_bootstrap-' + version
    metadata_path = prefix + ('.dist-info/METADATA' if wheel else '/PKG-INFO')
    legal_prefix = prefix + ('.dist-info/licenses/' if wheel else '/')
    wanted = {metadata_path} | {legal_prefix + name for name in expected_legal}
    found, names, total = {}, set(), 0

    def accept(name, size, regular, directory, reader):
        nonlocal total
        name = safe_name(name)
        if name in names or len(names) >= MAX_MEMBERS:
            raise ValueError('duplicate path or too many archive members')
        names.add(name)
        if not regular and not directory:
            raise ValueError('archive links and special files are unsupported')
        total += size
        if size < 0 or total > MAX_ARCHIVE:
            raise ValueError('expanded archive exceeds limit')
        if not wheel and name.split('/')[0] != prefix:
            raise ValueError('source archive root differs from expected version')
        if wheel and name.endswith('.dist-info/METADATA') and name != metadata_path:
            raise ValueError('unexpected package metadata')
        if name in wanted:
            if not regular or size > MAX_TEXT:
                raise ValueError('metadata/legal file must be bounded and regular')
            content = reader()
            if len(content) != size:
                raise ValueError('archive member size mismatch')
            found[name] = content

    if wheel:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for item in archive.infolist():
                mode = stat.S_IFMT(item.external_attr >> 16)
                directory = item.is_dir()
                regular = not directory and mode in (0, stat.S_IFREG)
                accept(item.filename, item.file_size, regular, directory and mode in (0, stat.S_IFDIR),
                       lambda item=item: archive.read(item))
    else:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            for item in archive:
                accept(item.name, item.size, item.isfile(), item.isdir(),
                       lambda item=item: archive.extractfile(item).read(MAX_TEXT + 1))
    if set(found) != wanted:
        raise ValueError('required package metadata or legal files missing')
    message = BytesParser().parsebytes(found[metadata_path])
    if message.defects:
        raise ValueError('malformed package metadata')
    for field, expected in (('Name', NAME), ('Version', version), ('License-Expression', license_id)):
        if message.get_all(field, []) != [expected]:
            raise ValueError('missing, duplicate, or mismatched metadata: ' + field)
    if message.get_all('Metadata-Version', []) not in (['2.4'], ['2.5'], ['2.6']):
        raise ValueError('unsupported metadata version for license expressions')
    if message.get_all('License', []):
        raise ValueError('ambiguous legacy License metadata')
    declarations = message.get_all('License-File', [])
    if len(declarations) != len(set(declarations)) or set(declarations) != set(expected_legal):
        raise ValueError('license file declarations differ from expected files')
    for name, content in expected_legal.items():
        if found[legal_prefix + name] != content:
            raise ValueError('packaged legal bytes differ: ' + name)
    return {'artifact': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'version': version,
            'license_id': license_id, 'legal_files': sorted(expected_legal),
            'package_checks_passed': True, 'publication_authorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path, nargs='+')
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--license-id', required=True)
    parser.add_argument('--legal-dir', type=Path, required=True, help='trusted reviewed directory containing LICENSE and optional NOTICE')
    args = parser.parse_args(argv)
    try:
        expected = legal_files(args.legal_dir)
        results = [inspect_package(path, version=args.expected_version, license_id=args.license_id,
                                   expected_legal=expected) for path in args.artifacts]
        print(json.dumps({'artifacts': results, 'publication_authorized': False}, indent=2))
        return 0
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, RuntimeError) as error:
        print(json.dumps({'package_checks_passed': False, 'publication_authorized': False, 'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
