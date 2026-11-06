from pathlib import Path
import tempfile
import unittest

from tools.check_release_source import inspect_source


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('LICENSE', 'TEST FIXTURE ONLY, not a project license')
        self.write('pyproject.toml', '[project]\nversion="0.2.0a1"\nlicense="TEST-ID"\nlicense-files=["LICENSE"]\n')
        self.write('Cargo.toml', '[workspace]\nmembers=["crates/example"]\n')
        self.write('crates/example/Cargo.toml', '[package]\nname="example"\nversion="0.2.0-alpha.1"\nlicense="TEST-ID"\n')
        self.write('Cargo.lock', '[[package]]\nname="example"\nversion="0.2.0-alpha.1"\n')
        self.options = dict(python_version='0.2.0a1', native_version='0.2.0-alpha.1', license_id='TEST-ID',
                            commit='a' * 40, dirty=False, tracked={'LICENSE'})

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def inspect(self, **changes):
        return inspect_source(self.root, **(self.options | changes))

    def test_source_success_never_authorizes_publication(self):
        result = self.inspect()
        self.assertTrue(result['source_ready'])
        self.assertFalse(result['publication_authorized'])
        self.assertTrue(result['remaining_manual_gates'])
        self.assertEqual(result['source_commit'], 'a' * 40)

    def test_dirty_and_unselected_license_fail(self):
        for changes in ({'dirty': True}, {'license_id': None}, {'license_id': 'OTHER-ID'}):
            with self.subTest(changes=changes):
                self.assertFalse(self.inspect(**changes)['source_ready'])

    def test_missing_untracked_and_empty_license_fail(self):
        self.assertFalse(self.inspect(tracked=set())['source_ready'])
        self.write('LICENSE', ' \n')
        self.assertFalse(self.inspect()['source_ready'])
        (self.root / 'LICENSE').unlink()
        self.assertFalse(self.inspect()['source_ready'])

    def test_version_and_lock_mismatch_fail(self):
        self.assertFalse(self.inspect(python_version='0.3.0a1')['source_ready'])
        self.assertFalse(self.inspect(native_version='0.3.0-alpha.1')['source_ready'])
        self.write('Cargo.lock', '[[package]]\nname="example"\nversion="0.0.1"\n')
        result = self.inspect()
        self.assertFalse(result['source_ready'])
        self.assertFalse(next(c for c in result['checks'] if c['name'].endswith(':lock'))['passed'])

    def test_missing_metadata_and_license_packaging_fail(self):
        self.write('pyproject.toml', '[project]\nversion="0.2.0a1"\nlicense="TEST-ID"\n')
        self.assertFalse(self.inspect()['source_ready'])
        self.write('Cargo.toml', '[invalid')
        self.assertFalse(self.inspect()['source_ready'])

    def test_unreviewed_workspace_paths_fail(self):
        for member in ('../outside', '/outside', 'crates/*'):
            self.write('Cargo.toml', '[workspace]\nmembers=["' + member + '"]\n')
            self.assertFalse(self.inspect()['source_ready'])


if __name__ == '__main__':
    unittest.main()
