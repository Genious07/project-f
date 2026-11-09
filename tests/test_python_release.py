import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

from tools.verify_python_release import inspect_package


class PythonReleaseTests(unittest.TestCase):
    version = '0.2.0a1'
    prefix = 'project_f_bootstrap-0.2.0a1'
    legal = {'LICENSE': b'TEST FIXTURE ONLY', 'NOTICE': b'TEST NOTICE'}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def files(self, wheel=True):
        metadata = b'Metadata-Version: 2.4\nName: project-f-bootstrap\nVersion: 0.2.0a1\nLicense-Expression: LicenseRef-Test\nLicense-File: LICENSE\nLicense-File: NOTICE\n\nDescription\n'
        if wheel:
            root = self.prefix + '.dist-info/'
            return {root + 'METADATA': metadata, **{root + 'licenses/' + k: v for k, v in self.legal.items()}}
        return {self.prefix + '/PKG-INFO': metadata, **{self.prefix + '/' + k: v for k, v in self.legal.items()}}

    def archive(self, files, wheel=True, duplicate=False):
        path = self.root / ('candidate.whl' if wheel else 'candidate.tar.gz')
        if wheel:
            with zipfile.ZipFile(path, 'w') as archive, warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                for name, value in list(files.items()) + (list(files.items())[:1] if duplicate else []):
                    archive.writestr(name, value)
        else:
            with tarfile.open(path, 'w:gz') as archive:
                for name, value in files.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(value)
                    archive.addfile(info, io.BytesIO(value))
        return path

    def verify(self, path, **changes):
        return inspect_package(path, **({'version': self.version, 'license_id': 'LicenseRef-Test',
                                         'expected_legal': self.legal} | changes))

    def test_both_formats_preserve_expected_metadata_and_bytes(self):
        for wheel in (True, False):
            result = self.verify(self.archive(self.files(wheel), wheel))
            self.assertTrue(result['package_checks_passed'])
            self.assertFalse(result['publication_authorized'])
            self.assertEqual(len(result['sha256']), 64)

    def test_versions_and_license_are_explicit(self):
        path = self.archive(self.files())
        for change in ({'version': '0.3.0a1'}, {'license_id': 'OTHER'}, {'expected_legal': {}},
                       {'expected_legal': {'LICENSE': b'changed', 'NOTICE': b'TEST NOTICE'}}):
            with self.assertRaises(ValueError):
                self.verify(path, **change)

    def test_missing_and_changed_legal_files_fail(self):
        for wheel in (True, False):
            for mode in ('missing', 'changed'):
                files = self.files(wheel)
                name = next(k for k in files if k.endswith('/LICENSE'))
                if mode == 'missing':
                    del files[name]
                else:
                    files[name] = b'tampered'
                with self.assertRaises(ValueError):
                    self.verify(self.archive(files, wheel))

    def test_duplicate_and_ambiguous_metadata_fail(self):
        for suffix in (b'Version: 0.2.0a1\n', b'License: MIT\n', b'License-File: NOTICE\n'):
            files = self.files()
            key = next(k for k in files if k.endswith('/METADATA'))
            files[key] = files[key].replace(b'\n\n', b'\n' + suffix + b'\n')
            with self.assertRaises(ValueError):
                self.verify(self.archive(files))
        files = self.files()
        key = next(k for k in files if k.endswith('/METADATA'))
        files[key] = files[key].replace(b'Metadata-Version: 2.4', b'Metadata-Version: 2.3')
        with self.assertRaises(ValueError):
            self.verify(self.archive(files))

    def test_duplicate_paths_and_unsafe_paths_fail_without_extraction(self):
        with self.assertRaises(ValueError):
            self.verify(self.archive(self.files(), duplicate=True))
        for name in ('../escape', '/escape', 'a//b', 'a\\b'):
            for wheel in (True, False):
                files = self.files(wheel) | {name: b'bad'}
                with self.assertRaises(ValueError):
                    self.verify(self.archive(files, wheel))
        self.assertEqual({p.suffix for p in self.root.iterdir()}, {'.whl', '.gz'})

    def test_symlinks_and_expanded_limits_fail(self):
        path = self.archive(self.files())
        with zipfile.ZipFile(path, 'a') as archive:
            item = zipfile.ZipInfo('link')
            item.external_attr = 0o120777 << 16
            archive.writestr(item, 'LICENSE')
        with self.assertRaises(ValueError):
            self.verify(path)
        path = self.archive(self.files())
        with patch('tools.verify_python_release.MAX_TEXT', 10), self.assertRaises(ValueError):
            self.verify(path)
        with patch('tools.verify_python_release.MAX_MEMBERS', 2), self.assertRaises(ValueError):
            self.verify(path)

    def test_source_root_and_additional_package_metadata_fail(self):
        with self.assertRaises(ValueError):
            self.verify(self.archive(self.files(False) | {'other/file': b'x'}, False))
        with self.assertRaises(ValueError):
            self.verify(self.archive(self.files() | {'other-1.dist-info/METADATA': b'x'}))


if __name__ == '__main__':
    unittest.main()
