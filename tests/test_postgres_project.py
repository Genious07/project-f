import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foresee.project import init_project, run_project, project_recovery_targets, load_project_config


class PostgresProjectTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.target = {'adapter': 'postgres', 'name': 'catalog', 'schema': 'managed', 'dsn_env': 'FORESEE_TEST_ENDPOINT'}
        self.config = init_project(self.root / 'project', target=self.target)

    def test_init_is_offline_and_does_not_create_database(self):
        self.assertFalse((self.config.parent / 'catalog.db').exists())
        self.assertEqual(json.loads(self.config.read_text())['target'], self.target)
        rejected = self.root / 'rejected'
        with self.assertRaisesRegex(ValueError, 'does not create or seed'):
            init_project(rejected, demo_data=True, target=self.target)
        self.assertFalse(rejected.exists())

    def test_strict_target_configuration_rejects_credentials_and_unknown_fields(self):
        original = json.loads(self.config.read_text())
        for target in ({**self.target, 'dsn': 'password=secret'}, {**self.target, 'dsn_env': 'password=secret'},
                       {**self.target, 'adapter': 'other'}, {**self.target, 'schema': 'a,b'}, {}, None):
            self.config.write_text(json.dumps({**original, 'target': target}))
            with self.assertRaises(ValueError):
                load_project_config(self.config)
        self.config.write_text(json.dumps({**original, 'version': True}))
        with self.assertRaises(ValueError):
            load_project_config(self.config)

    def test_missing_environment_and_bad_candidates_fail_before_open(self):
        with patch.dict(os.environ, {'FORESEE_TEST_ENDPOINT': ''}), patch('foresee.postgres.PostgresCatalog') as opened:
            with self.assertRaisesRegex(ValueError, 'missing or empty'):
                run_project(self.config)
            opened.assert_not_called()
        (self.config.parent / 'plans.json').write_text('[{"bad": true}]')
        with patch('foresee.postgres.PostgresCatalog') as opened:
            with self.assertRaises(ValueError):
                run_project(self.config)
            opened.assert_not_called()

    def test_recovery_config_does_not_require_program_files_or_open_database(self):
        (self.config.parent / 'decision.fore').unlink()
        (self.config.parent / 'plans.json').unlink()
        with patch.dict(os.environ, {'FORESEE_TEST_ENDPOINT': 'password=secret'}), patch('foresee.postgres.PostgresCatalog') as opened:
            self.assertEqual(project_recovery_targets(self.config), {'catalog': {'dsn': 'password=secret', 'schema': 'managed'}})
            opened.assert_not_called()
        self.assertNotIn('secret', self.config.read_text())

    def test_remote_target_preserves_local_input_collision_checks(self):
        config = json.loads(self.config.read_text())
        config['candidates'] = 'decision.fore'
        self.config.write_text(json.dumps(config))
        with patch('foresee.postgres.PostgresCatalog') as opened:
            with self.assertRaisesRegex(ValueError, 'distinct'):
                run_project(self.config)
            opened.assert_not_called()
