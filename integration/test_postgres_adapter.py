"""Run the same contract as SQLite against a real PostgreSQL adapter."""
import os
import unittest
from copy import deepcopy

from foresee.conformance import adapter_suite
from foresee.postgres import PostgresCatalog
from foresee.postgres_fixture import PostgresFixture


def fixture(_directory=None):
    return PostgresFixture(os.environ.get('FORESEE_TEST_POSTGRES_DSN'), adapter_factory=PostgresCatalog)


class PostgresSpecificTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture()
        self.addCleanup(self.fixture.close)
        self.adapter = self.fixture.connect()
        self.addCleanup(self.adapter.close)
        self.base = self.adapter.snapshot()
        self.selection = {'base': {'digest': self.base.digest}, 'plan': self.fixture.valid_plan(self.base)}

    def test_missing_schema_is_not_created(self):
        with self.assertRaises(Exception):
            PostgresCatalog(os.environ['FORESEE_TEST_POSTGRES_DSN'], self.fixture.schema + '_absent')
        with self.fixture.database() as db:
            self.assertIsNone(db.execute('SELECT to_regnamespace(%s) AS name', (self.fixture.schema + '_absent',)).fetchone()['name'])

    def test_invalid_target_identity_rejected(self):
        with self.fixture.database() as db:
            db.execute("UPDATE foresee_target SET target_id='not-a-uuid'")
        with self.assertRaises(ValueError):
            self.fixture.connect()

    def test_active_transaction_rejected_without_committing_caller(self):
        with self.adapter.connection.transaction():
            for operation in (self.adapter.snapshot, lambda: self.adapter.commit(self.selection, 'program')):
                with self.assertRaisesRegex(RuntimeError, 'idle'):
                    operation()
        self.assertEqual(self.adapter.snapshot(), self.base)

    def test_receipt_lookup_and_target_identity_after_reopen(self):
        outcome = self.adapter.commit(self.selection, 'program', operation_id='lookup')
        other = self.fixture.connect()
        self.addCleanup(other.close)
        self.assertEqual(other.target_id, self.adapter.target_id)
        self.assertEqual(other.receipt(outcome['commit_id'])['status'], 'applied')
        self.assertIsNone(other.receipt('0' * 64))
        with self.assertRaises(ValueError):
            other.receipt("' OR true")

    def test_invalid_arithmetic_unknown_row_and_source_edit_rollback(self):
        for patch in ({'id': 'coffee', 'unit_price_cents': 1},
                      {'id': 'missing', 'unit_price_cents': 150},
                      {'id': 'coffee', 'title': 'changed'}):
            selection = deepcopy(self.selection)
            selection['plan']['patches'] = [patch]
            with self.assertRaises(ValueError):
                self.adapter.commit(selection, 'program')
            self.assertEqual(self.adapter.snapshot(), self.base)
            self.assertEqual(self.fixture.receipts(), [])

    def test_lock_timeout_rolls_back_and_connection_reusable(self):
        self.adapter.connection.execute("SET lock_timeout='100ms'")
        with self.fixture.database() as owner, owner.transaction():
            owner.execute('LOCK TABLE catalog_rows IN SHARE ROW EXCLUSIVE MODE')
            with self.assertRaisesRegex(RuntimeError, 'reconcile the original operation'):
                self.adapter.commit(self.selection, 'program')
        self.assertEqual(self.adapter.snapshot(), self.base)
        self.assertEqual(self.fixture.receipts(), [])
        self.assertEqual(self.adapter.commit(self.selection, 'program')['status'], 'applied')

    def test_temporary_table_cannot_shadow_target(self):
        self.adapter.connection.execute('CREATE TEMP TABLE catalog_rows (id TEXT)')
        self.assertEqual(self.adapter.snapshot(), self.base)
        self.assertEqual(self.adapter.commit(self.selection, 'program')['status'], 'applied')


def load_tests(loader, tests, pattern):
    tests.addTests(adapter_suite(fixture, 'PostgresCatalog'))
    return tests
