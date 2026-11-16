"""Requires an explicit disposable PostgreSQL database; missing DSN is a failure."""
import os
import unittest

from foresee.postgres_fixture import PostgresFixture


class PostgresFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PostgresFixture(os.environ.get('FORESEE_TEST_POSTGRES_DSN'))
        self.addCleanup(self.fixture.close)

    def test_seed_identity_and_schema_isolation(self):
        other = PostgresFixture(os.environ['FORESEE_TEST_POSTGRES_DSN'])
        self.addCleanup(other.close)
        with self.fixture.database() as first, other.database() as second:
            self.assertEqual(first.execute('SELECT count(*) AS n FROM catalog_rows').fetchone()['n'], 3)
            one = first.execute('SELECT target_id FROM foresee_target').fetchone()['target_id']
            two = second.execute('SELECT target_id FROM foresee_target').fetchone()['target_id']
            self.assertNotEqual(one, two)
            self.assertNotEqual(self.fixture.schema, other.schema)
        self.fixture.mutate()
        with other.database() as db:
            self.assertEqual(db.execute('SELECT revision FROM catalog_meta').fetchone()['revision'], 0)

    def test_receipt_failure_rolls_back_effect_and_revision(self):
        with self.fixture.fail_receipt_write():
            with self.assertRaises(Exception):
                with self.fixture.database() as db, db.transaction():
                    db.execute("UPDATE catalog_rows SET unit_price_cents=150 WHERE id='coffee'")
                    db.execute('UPDATE catalog_meta SET revision=1')
                    db.execute("INSERT INTO foresee_receipts VALUES ('id', 'intent', 'applied', 'snapshot', 1, 'test')")
        with self.fixture.database() as db:
            self.assertIsNone(db.execute("SELECT unit_price_cents FROM catalog_rows WHERE id='coffee'").fetchone()['unit_price_cents'])
            self.assertEqual(db.execute('SELECT revision FROM catalog_meta').fetchone()['revision'], 0)
            db.execute("INSERT INTO foresee_receipts VALUES ('id', 'intent', 'stale', 'snapshot', 0, 'test')")
        self.assertEqual(len(self.fixture.receipts()), 1)

    def test_lock_contention_is_bounded_and_transaction_recovers(self):
        from psycopg.errors import LockNotAvailable
        with self.fixture.database() as owner, self.fixture.database() as contender:
            with owner.transaction():
                owner.execute('SELECT revision FROM catalog_meta FOR UPDATE')
                with self.assertRaises(LockNotAvailable):
                    with contender.transaction():
                        contender.execute("SET LOCAL lock_timeout='100ms'")
                        contender.execute('SELECT revision FROM catalog_meta FOR UPDATE')
            with contender.transaction():
                contender.execute('SELECT revision FROM catalog_meta FOR UPDATE')

    def test_repeatable_read_keeps_revision_and_rows_together(self):
        with self.fixture.database() as reader, reader.transaction():
            reader.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.assertEqual(reader.execute('SELECT revision FROM catalog_meta').fetchone()['revision'], 0)
            self.fixture.mutate()
            self.assertEqual(reader.execute("SELECT title FROM catalog_rows WHERE id='mugs'").fetchone()['title'], 'Stoneware mugs')
        with self.fixture.database() as reader:
            self.assertEqual(reader.execute('SELECT revision FROM catalog_meta').fetchone()['revision'], 1)

    def test_cleanup_drops_only_owned_schema(self):
        other = PostgresFixture(os.environ['FORESEE_TEST_POSTGRES_DSN'])
        self.addCleanup(other.close)
        schema = self.fixture.schema
        self.fixture.close()
        self.fixture.close()
        with other.database() as db:
            self.assertIsNone(db.execute('SELECT to_regnamespace(%s) AS name', (schema,)).fetchone()['name'])
            self.assertEqual(db.execute('SELECT count(*) AS n FROM catalog_rows').fetchone()['n'], 3)
        with self.assertRaises(RuntimeError):
            self.fixture.connect()

    def test_factory_is_explicit_and_receipt_identity_unique(self):
        from psycopg.errors import UniqueViolation
        with self.assertRaisesRegex(RuntimeError, 'factory'):
            self.fixture.connect()
        with self.fixture.database() as db:
            db.execute("INSERT INTO foresee_receipts VALUES ('id', 'intent', 'stale', 'snapshot', 0, 'test')")
            with self.assertRaises(UniqueViolation):
                db.execute("INSERT INTO foresee_receipts VALUES ('id', 'other', 'applied', 'snapshot', 1, 'test')")
        self.assertEqual(len(self.fixture.receipts()), 1)


if __name__ == '__main__':
    unittest.main()
