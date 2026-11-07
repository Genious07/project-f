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


class NativeReleaseTests(unittest.TestCase):
    expected = ('a' * 40, '0.2.0-alpha.1', 'TEST-ID')

    def payload(self, **changes):
        files = NativeDistributionTests().payload()
        files['LICENSE'] = b'TEST FIXTURE, not a project license'
        manifest = dict(schema_version=1, source_commit='a' * 40, source_dirty=False,
                        version='0.2.0-alpha.1', project_license='TEST-ID', preview=True)
        manifest.update(changes)
        manifest['sha256'] = {n: digest(v) for n, v in files.items() if n != 'manifest.json'}
        files['manifest.json'] = encoded(manifest)
        return files

    def test_release_accepts_matching_candidate_and_preserves_license(self):
        files = self.payload()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpack(archive_bytes(files), root, release=self.expected)
            self.assertEqual((root / 'LICENSE').read_bytes(), files['LICENSE'])

    def test_release_mismatch_rejected_before_extraction(self):
        for changes in ({'source_commit': 'b' * 40}, {'source_dirty': True}, {'source_dirty': 0},
                        {'version': '0.0.1'}, {'project_license': None}, {'project_license': 'OTHER'},
                        {'preview': False}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaises(ValueError):
                    unpack(archive_bytes(self.payload(**changes)), root, release=self.expected)
                self.assertEqual(list(root.iterdir()), [])

    def test_release_requires_license_and_full_commit(self):
        for files, expected in ((NativeDistributionTests().payload(), self.expected),
                                (self.payload(), ('a' * 7, '0.2.0-alpha.1', 'TEST-ID'))):
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                unpack(archive_bytes(files), Path(temporary), release=expected)

    def test_license_tampering_is_checked(self):
        files = self.payload()
        files['LICENSE'] = b'replaced'
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            unpack(archive_bytes(files), Path(temporary), release=self.expected)

    def test_legal_files_are_optional_but_strict_when_present(self):
        from tools.package_native import legal_files
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(legal_files(root), {})
            (root / 'LICENSE').write_text('test text')
            (root / 'NOTICE').write_text('test notice')
            self.assertEqual(set(legal_files(root)), {'LICENSE', 'NOTICE'})
            (root / 'NOTICE').write_text(' ')
            with self.assertRaises(ValueError):
                legal_files(root)
            (root / 'NOTICE').unlink()
            (root / 'NOTICE').symlink_to(root / 'LICENSE')
            with self.assertRaises(ValueError):
                legal_files(root)

    def test_workspace_license_requires_unanimous_declaration(self):
        from tools.package_native import project_license
        metadata = {'workspace_members': ['a', 'b'], 'packages': [
                    {'id': 'a', 'license': 'TEST-ID'}, {'id': 'b', 'license': 'TEST-ID'}]}
        self.assertEqual(project_license(metadata), 'TEST-ID')
        metadata['packages'][1]['license'] = 'OTHER'
        self.assertIsNone(project_license(metadata))
        metadata['packages'].pop()
        self.assertIsNone(project_license(metadata))
