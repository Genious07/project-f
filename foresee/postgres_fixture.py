"""Disposable PostgreSQL target for adapter development, not a production adapter."""
from contextlib import contextmanager
from copy import deepcopy
import uuid

from .catalog import Catalog, fixture_plans


class PostgresFixture:
    """Create one fresh random schema in an explicitly supplied test database.

    adapter_factory(dsn, schema) must return the candidate resource adapter.
    Omit it to use only the database fixture/probes. Never print the DSN.
    """
    def __init__(self, dsn, *, adapter_factory=None):
        if type(dsn) is not str or not dsn.strip():
            raise ValueError('an explicit test database DSN is required')
        try:
            import psycopg
            from psycopg import sql
            from psycopg.rows import dict_row
        except ImportError:
            raise RuntimeError('install project-f-bootstrap[postgres] for PostgreSQL tests') from None
        self._dsn = dsn
        self._driver, self._sql, self._dict_row = psycopg, sql, dict_row
        self._adapter_factory = adapter_factory
        self.schema = 'foresee_test_' + uuid.uuid4().hex
        self._owned = False
        with self.database() as db:
            with db.transaction():
                db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
                db.execute('''CREATE TABLE catalog_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision BIGINT NOT NULL CHECK (revision >= 0))''')
                db.execute('''CREATE TABLE catalog_rows (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    pack_price_cents BIGINT NOT NULL CHECK (pack_price_cents >= 0),
                    units_per_pack BIGINT NOT NULL CHECK (units_per_pack > 0),
                    unit_price_cents BIGINT CHECK (unit_price_cents >= 0))''')
                db.execute('''CREATE TABLE foresee_target (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1), target_id TEXT NOT NULL)''')
                db.execute('''CREATE TABLE foresee_receipts (
                    commit_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('applied', 'stale')),
                    snapshot_digest TEXT NOT NULL, resulting_revision BIGINT NOT NULL CHECK (resulting_revision >= 0),
                    detail TEXT NOT NULL)''')
                db.execute('INSERT INTO catalog_meta VALUES (1, 0)')
                db.execute('INSERT INTO foresee_target VALUES (1, %s)', (str(uuid.uuid4()),))
                with db.cursor() as cursor:
                    cursor.executemany('INSERT INTO catalog_rows VALUES (%s, %s, %s, %s, %s)',
                                       [('coffee', 'Coffee beans', 1800, 12, None),
                                        ('filters', 'Paper filters', 2400, 24, None),
                                        ('mugs', 'Stoneware mugs', 3600, 6, 600)])
        self._owned = True

    @contextmanager
    def database(self):
        """Independent autocommit connection; callers use explicit transactions."""
        try:
            connection = self._driver.connect(self._dsn, autocommit=True, connect_timeout=5,
                                              row_factory=self._dict_row)
        except self._driver.Error:
            raise RuntimeError('PostgreSQL test connection failed') from None
        with connection as db:
            # An absent schema is ignored until CREATE SCHEMA completes. No public fallback.
            db.execute("SELECT set_config('search_path', %s, false)", (self.schema,))
            db.execute("SET statement_timeout = '5s'")
            db.execute("SET lock_timeout = '2s'")
            db.execute("SET idle_in_transaction_session_timeout = '10s'")
            yield db

    def connect(self):
        if not self._owned:
            raise RuntimeError('fixture is closed')
        if self._adapter_factory is None:
            raise RuntimeError('a candidate adapter factory is required for the conformance suite')
        return self._adapter_factory(self._dsn, self.schema)

    def close(self):
        if self._owned:
            with self.database() as db:
                db.execute(self._sql.SQL('DROP SCHEMA {} CASCADE').format(self._sql.Identifier(self.schema)))
            self._owned = False

    def valid_plan(self, base):
        return fixture_plans(base, 1)[0]

    def invalid_plan(self, base):
        plan = deepcopy(self.valid_plan(base))
        plan['patches'][0]['unit_price_cents'] = -1
        return plan

    def simulate(self, base, plan):
        return Catalog.apply_to_snapshot(base, plan)

    def mutate(self):
        with self.database() as db, db.transaction():
            db.execute('LOCK TABLE catalog_rows IN SHARE ROW EXCLUSIVE MODE')
            db.execute('SELECT revision FROM catalog_meta WHERE singleton=1 FOR UPDATE')
            db.execute("UPDATE catalog_rows SET title = title || ' (updated)' WHERE id='mugs'")
            db.execute('UPDATE catalog_meta SET revision=revision+1 WHERE singleton=1')

    def receipts(self):
        with self.database() as db:
            return db.execute('SELECT * FROM foresee_receipts ORDER BY commit_id').fetchall()

    @contextmanager
    def fail_receipt_write(self):
        with self.database() as db, db.transaction():
            db.execute('''CREATE FUNCTION reject_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'injected receipt failure'; END; $$''')
            db.execute('''CREATE TRIGGER reject_receipt BEFORE INSERT ON foresee_receipts
                          FOR EACH ROW EXECUTE FUNCTION reject_receipt()''')
        try:
            yield
        finally:
            with self.database() as db, db.transaction():
                db.execute('DROP TRIGGER reject_receipt ON foresee_receipts')
                db.execute('DROP FUNCTION reject_receipt()')
