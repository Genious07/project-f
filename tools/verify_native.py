"""Verify a trusted native preview archive in an isolated temporary directory."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_lsp import verify as verify_lsp

FILES = {'bin/foresee-semantics', 'bin/foresee-lsp', 'examples/repair.fore',
         'examples/repair.ir.json', 'README.md', 'sbom.spdx.json', 'manifest.json'}
MAX_ARCHIVE = 128 * 1024 * 1024


def unpack(data, directory):
    """Reject unknown members, links, duplicate paths, and oversized payloads."""
    payload = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for item in archive:
            if item.name not in FILES or item.name in payload or not item.isfile():
                raise ValueError(f'unsafe archive member: {item.name}')
            total += item.size
            if item.size < 0 or total > MAX_ARCHIVE:
                raise ValueError('archive payload exceeds limit')
            payload[item.name] = archive.extractfile(item).read()
    if set(payload) != FILES:
        raise ValueError('archive is incomplete')
    manifest = json.loads(payload['manifest.json'])
    expected = {name: hashlib.sha256(content).hexdigest() for name, content in payload.items() if name != 'manifest.json'}
    if manifest.get('schema_version') != 1 or manifest.get('sha256') != expected:
        raise ValueError('payload checksum mismatch')
    for name, content in payload.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if name.startswith('bin/') else 0o644)
    return manifest


def verify(archive):
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError('compressed archive exceeds limit')
    data = archive.read_bytes()
    expected = f'{hashlib.sha256(data).hexdigest()}  {archive.name}\n'
    if archive.with_suffix(archive.suffix + '.sha256').read_text() != expected:
        raise ValueError('archive checksum mismatch')
    target = {('Darwin', 'arm64'): 'aarch64-apple-darwin',
              ('Linux', 'x86_64'): 'x86_64-unknown-linux-gnu'}.get((platform.system(), platform.machine()))
    with tempfile.TemporaryDirectory(prefix='foresee-distribution-') as temporary:
        directory = Path(temporary)
        manifest = unpack(data, directory)
        if manifest['target'] != target:
            raise ValueError('archive target does not match verifier host')
        binary = directory / 'bin/foresee-semantics'
        for arguments in [('check', 'examples/repair.fore'), ('build', 'examples/repair.fore', '-o', 'actual.json')]:
            subprocess.run([str(binary), *arguments], cwd=directory, env={'PATH': ''}, check=True, capture_output=True, timeout=15)
        if json.loads((directory / 'actual.json').read_text()) != json.loads((directory / 'examples/repair.ir.json').read_text()):
            raise ValueError('native IR differs from Python reference')
        verify_lsp(directory / 'bin/foresee-lsp', source=(directory / 'examples/repair.fore').read_text())
    print(f'Verified {archive.name}: checksums, standalone check/build, reference IR, and LSP session')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', type=Path, nargs='+')
    for archive in parser.parse_args().archives:
        verify(archive)


if __name__ == '__main__':
    main()
