import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.package_native import archive_bytes, digest, encoded, sbom
from tools.verify_native import FILES, unpack


class NativeDistributionTests(unittest.TestCase):
    def payload(self):
        files = {name: b'example' for name in FILES - {'manifest.json'}}
        files['manifest.json'] = encoded({'schema_version': 1, 'sha256': {n: digest(v) for n, v in files.items()}})
        return files

    def test_roundtrip_and_permissions(self):
        files = self.payload()
        self.assertEqual(archive_bytes(files), archive_bytes(files))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpack(archive_bytes(files), root)
            for name, content in files.items():
                self.assertEqual((root / name).read_bytes(), content)
            self.assertEqual((root / 'bin/foresee-lsp').stat().st_mode & 0o777, 0o755)

    def test_tampering_and_missing_payload_rejected(self):
        for action in ('change', 'remove'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temporary:
                files = self.payload()
                if action == 'change':
                    files['bin/foresee-lsp'] = b'tampered'
                else:
                    del files['bin/foresee-lsp']
                with self.assertRaises(ValueError):
                    unpack(archive_bytes(files), Path(temporary))
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_unsafe_members_rejected_before_writes(self):
        for kind in ('traversal', 'absolute', 'symlink', 'duplicate', 'oversized'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
                    item = tarfile.TarInfo({'traversal': '../outside', 'absolute': '/outside'}.get(kind, 'README.md'))
                    if kind == 'symlink':
                        item.type = tarfile.SYMTYPE
                        item.linkname = '/outside'
                    if kind == 'oversized':
                        item.size = 129 * 1024 * 1024
                    if kind != 'oversized':
                        archive.addfile(item)
                    if kind == 'duplicate':
                        archive.addfile(item)
                with self.assertRaises(ValueError):
                    data = gzip.compress(item.tobuf() + b'\0' * 1024) if kind == 'oversized' else buffer.getvalue()
                    unpack(data, Path(temporary))
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_sbom_graph_checksums_and_unknown_license(self):
        metadata = {'packages': [
            {'id': 'local', 'name': 'foresee', 'version': '0.0.1', 'source': None, 'license': None},
            {'id': 'registry', 'name': 'dep', 'version': '1.0.0', 'source': 'registry+url', 'license': 'MIT/Apache-2.0'}],
            'workspace_members': ['local'], 'resolve': {'nodes': [{'id': 'local', 'dependencies': ['registry']}, {'id': 'registry', 'dependencies': []}]}}
        result = sbom(metadata, {'package': [{'name': 'dep', 'version': '1.0.0', 'checksum': 'a' * 64}]}, '2026-10-16T00:00:00Z', 'test')
        packages = {p['name']: p for p in result['packages']}
        self.assertEqual(packages['foresee']['licenseDeclared'], 'NOASSERTION')
        self.assertEqual(packages['dep']['licenseDeclared'], 'MIT OR Apache-2.0')
        self.assertEqual(packages['dep']['checksums'][0]['checksumValue'], 'a' * 64)
        self.assertIn({'spdxElementId': packages['foresee']['SPDXID'], 'relationshipType': 'DEPENDS_ON', 'relatedSpdxElement': packages['dep']['SPDXID']}, result['relationships'])
        self.assertNotIn('local', json.dumps(result))
