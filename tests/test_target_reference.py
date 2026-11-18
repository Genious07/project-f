import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foresee.catalog import Catalog, fixture_plans
from foresee.journal import Journal, reconcile
from foresee.target_reference import postgres_reference, validate_reference


class TargetReferenceTests(unittest.TestCase):
    def test_reference_is_strict_and_credential_free(self):
        expected = {'version': 1, 'adapter': 'postgres', 'name': 'catalog', 'schema': 'managed'}
        self.assertEqual(postgres_reference('catalog', 'managed'), expected)
        self.assertEqual(validate_reference(expected), expected)
        for bad in ({**expected, 'dsn': 'secret'}, {**expected, 'version': True},
                    {**expected, 'adapter': 'arbitrary'}, {**expected, 'name': 'https://host'},
                    {**expected, 'schema': 'public,other'}, {**expected, 'name': 'x' * 65}):
            with self.assertRaises(ValueError):
                validate_reference(bad)

    def test_legacy_sqlite_journal_without_reference_table_still_reconciles(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / 'target.db')
            journal = Journal(Path(directory) / 'journal.db')
            try:
                catalog.seed()
                base = catalog.snapshot()
                payload = {'base': {'digest': base.digest}, 'plan': fixture_plans(base, 1)[0]}
                journal.connection.execute('DROP TABLE operation_targets')
                run = journal.start()
                operation = journal.prepare(run, catalog, 'program', payload)
                catalog.commit(payload, 'program', operation_id=operation)
                result = reconcile(journal.path)
                self.assertEqual(result['runs'][0]['state'], 'reconciled')
            finally:
                catalog.close()
                journal.close()

    def test_remote_errors_are_redacted_and_unknown_reference_does_not_connect(self):
        from foresee.catalog import commit_identity
        from foresee.journal import receipt_outcome
        payload = {'base': {'digest': 'snapshot'}, 'plan': {'id': 'test', 'patches': []}}
        commit, intent = commit_identity(payload, 'program', 'operation')
        operation = {'operation_id': 'operation', 'program_digest': 'program', 'payload': json.dumps(payload),
                     'commit_id': commit, 'intent_digest': intent, 'target_path': '', 'target_id': 'uuid',
                     'target_reference': json.dumps(postgres_reference('catalog', 'managed'))}
        with patch('foresee.postgres.PostgresCatalog', side_effect=RuntimeError('password=secret')) as connect:
            result = receipt_outcome(operation)
            connect.assert_not_called()
            self.assertEqual(result['status'], 'unresolved')
            result = receipt_outcome(operation, postgres_targets={'catalog': {'dsn': 'password=secret', 'schema': 'managed'}})
            self.assertEqual(result['status'], 'unresolved')
            self.assertNotIn('secret', json.dumps(result))
