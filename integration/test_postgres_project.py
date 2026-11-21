"""CLI integration usable both in the checkout and from an installed wheel."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from foresee.postgres_fixture import PostgresFixture


class PostgresProjectIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.fixture = PostgresFixture(os.environ.get('FORESEE_TEST_POSTGRES_DSN'))
        self.addCleanup(self.fixture.close)
        self.env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME'}}
        checkout = Path(__file__).resolve().parents[1]
        if (checkout / 'foresee').is_dir():
            self.env['PYTHONPATH'] = str(checkout)
        self.env['FORESEE_PROJECT_TEST_DSN'] = os.environ['FORESEE_TEST_POSTGRES_DSN']
        self.config = self.root / 'project' / 'foresee.json'
        created = self.cli('init', str(self.config.parent), '--postgres-schema', self.fixture.schema,
                           '--dsn-env', 'FORESEE_PROJECT_TEST_DSN', '--target-name', 'catalog')
        self.assertEqual(created.returncode, 0, created.stderr)
        (self.config.parent / 'plans.json').write_text(json.dumps([{'id': 'repair', 'patches': [
            {'id': 'coffee', 'unit_price_cents': 150}, {'id': 'filters', 'unit_price_cents': 100}]}]))

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'foresee', *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_run_inspect_replay_and_configured_reconcile(self):
        run = self.cli('run', '--project', str(self.config))
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result['outcome']['status'], 'applied')
        for command in ('inspect', 'replay'):
            check = self.cli(command, result['report'])
            self.assertEqual(check.returncode, 0, check.stderr)
        missing = self.cli('reconcile', result['journal'])
        self.assertEqual(missing.returncode, 2, missing.stderr)
        for _ in range(2):
            recovery = self.cli('reconcile', result['journal'], '--project', str(self.config))
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            self.assertEqual(json.loads(recovery.stdout)['target_writes'], 0)
        with self.fixture.database() as db:
            self.assertEqual(db.execute('SELECT revision FROM catalog_meta').fetchone()['revision'], 1)
        self.assertEqual(len(self.fixture.receipts()), 1)
        secret = self.env['FORESEE_PROJECT_TEST_DSN']
        self.assertNotIn(secret, run.stdout + run.stderr + recovery.stdout + recovery.stderr)
        self.assertNotIn(secret, Path(result['report']).read_text())
        self.assertNotIn(secret, Path(result['journal']).read_bytes().decode(errors='replace'))

    def test_bad_target_and_missing_environment_exit_cleanly(self):
        original = json.loads(self.config.read_text())
        original['target']['schema'] = 'foresee_missing_project_schema'
        self.config.write_text(json.dumps(original))
        result = self.cli('run', '--project', str(self.config))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((self.config.parent / '.foresee').exists())
        self.env.pop('FORESEE_PROJECT_TEST_DSN')
        result = self.cli('run', '--project', str(self.config))
        self.assertEqual(result.returncode, 1)
        self.assertIn('missing or empty', result.stderr)
        self.assertEqual(self.fixture.receipts(), [])
