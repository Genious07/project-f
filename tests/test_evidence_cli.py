import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foresee.evidence_files import generate_key, load_key, public_metadata, read_bounded, write_new
from foresee.catalog import Catalog
from foresee.compiler import compile_source
from foresee.project import SOURCE
from foresee.runtime import Runtime


@unittest.skipUnless(os.name == 'posix', 'POSIX file custody')
class EvidenceCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / 'key.json'

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'foresee', *map(str, args)],
                              capture_output=True, text=True, timeout=20)

    def test_key_generation_public_export_and_no_overwrite(self):
        created = self.cli('evidence-keygen', '--output', self.key)
        self.assertEqual(created.returncode, 0, created.stderr)
        public = json.loads(created.stdout)
        self.assertNotIn('seed', public)
        raw = self.key.read_bytes()
        self.assertNotIn(json.loads(raw)['seed'], created.stdout)
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        exported = self.cli('evidence-public-key', '--key', self.key)
        self.assertEqual(json.loads(exported.stdout), public)
        self.assertEqual(self.cli('evidence-keygen', '--output', self.key).returncode, 1)
        self.assertEqual(self.key.read_bytes(), raw)
        self.assertEqual(list(self.root.glob('.foresee-*')), [])

    def test_private_modes_owner_and_hard_links(self):
        generate_key(self.key)
        self.key.chmod(0o644)
        with self.assertRaises(ValueError):
            load_key(self.key)
        self.key.chmod(0o600)
        with patch('foresee.evidence_files.os.getuid', return_value=-1), self.assertRaises(ValueError):
            load_key(self.key)
        linked = self.root / 'alias'
        os.link(self.key, linked)
        with self.assertRaises(ValueError):
            load_key(self.key)
        linked.unlink()
        self.key.chmod(0o400)
        self.assertEqual(public_metadata(load_key(self.key))['algorithm'], 'Ed25519')

    def test_symlinks_fifo_directory_and_oversized_inputs_rejected(self):
        generate_key(self.key)
        alias = self.root / 'alias'
        alias.symlink_to(self.key)
        with self.assertRaises(OSError):
            load_key(alias)
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        for path in (fifo, self.root):
            with self.assertRaises((ValueError, OSError)):
                read_bounded(path, 4096)
        with self.assertRaises(ValueError):
            read_bounded(self.key, 1)
        destination = self.root / 'destination'
        destination.symlink_to(self.key)
        original = self.key.read_bytes()
        with self.assertRaises(FileExistsError):
            write_new(destination, b'bad')
        self.assertEqual(self.key.read_bytes(), original)

    def test_invalid_key_errors_do_not_expose_material(self):
        for raw in (b'{"seed":"secret-test-value"}', b'{"version":1,"version":1}',
                    b'\xff', b'{}', b' ' * 4097):
            self.key.write_bytes(raw)
            self.key.chmod(0o600)
            result = self.cli('evidence-public-key', '--key', self.key)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('secret-test-value', result.stdout + result.stderr)
            self.assertEqual(result.stdout, '')

    def test_publication_failure_removes_temporary_file(self):
        with patch('foresee.evidence_files.os.fsync', side_effect=OSError('test fault')):
            with self.assertRaises(OSError):
                write_new(self.key, b'secret')
        self.assertFalse(self.key.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_signing_does_not_create_output(self):
        generate_key(self.key)
        report = self.root / 'report.json'
        report.write_text('{}')
        output = self.root / 'envelope.json'
        result = self.cli('evidence-sign', report, '--key', self.key, '--output', output,
                          '--issuer', 'test/team', '--audience', 'audit', '--issued-at', 100, '--expires-at', 200)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output.exists())
        self.assertEqual(result.stdout, '')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bounded replay')
    def test_installed_cli_round_trip_failures_and_output_preservation(self):
        public = json.loads(self.cli('evidence-keygen', '--output', self.key).stdout)
        report_path = self.root / 'report.json'
        catalog = Catalog(self.root / 'catalog.db')
        try:
            catalog.seed()
            report = Runtime(compile_source(SOURCE), catalog).run()
        finally:
            catalog.close()
        report_path.write_text(json.dumps(report))
        envelope = self.root / 'envelope.json'
        sign = ['evidence-sign', report_path, '--key', self.key, '--output', envelope,
                '--issuer', 'test/team', '--audience', 'audit', '--issued-at', 100, '--expires-at', 200]
        signed = self.cli(*sign)
        self.assertEqual(signed.returncode, 0, signed.stderr)
        original = envelope.read_bytes()
        self.assertEqual(self.cli(*sign).returncode, 1)
        self.assertEqual(envelope.read_bytes(), original)
        policy = self.root / 'policy.json'
        policy.write_text(json.dumps({'version': 1, 'keys': [dict(keyid=public['keyid'], public_key=public['public_key'],
                          issuer='test/team', audiences=['audit'], status='active', not_before=50, not_after=300)]}))
        verify = ['evidence-verify', envelope, '--policy', policy, '--issuer', 'test/team',
                  '--audience', 'audit', '--now', 150, '--max-lifetime', 100]
        verified = self.cli(*verify)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        result = json.loads(verified.stdout)
        self.assertTrue(result['requirements_satisfied'])
        self.assertFalse(result['target_effect_verified'])
        self.assertNotIn('report', result)
        self.assertEqual(self.cli(*verify, '--audience', 'wrong').returncode, 1)
        failed = self.cli(*verify, '--max-report-bytes', 1)
        self.assertEqual(failed.returncode, 2, failed.stderr)
        result = json.loads(failed.stdout)
        self.assertTrue(result['origin_authenticated'])
        self.assertFalse(result['requirements_satisfied'])
        self.assertEqual(result['replay_error'], 'input_limit')


if __name__ == '__main__':
    unittest.main()
