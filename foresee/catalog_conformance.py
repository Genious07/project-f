"""SQLite fixture for the adapter kit. Never points at an existing user target."""
from contextlib import closing, contextmanager
from copy import deepcopy
import sqlite3

from .catalog import Catalog, fixture_plans


class CatalogFixture:
    def __init__(self, directory):
        self.path = directory / 'conformance.db'
        if self.path.exists():
            raise ValueError('conformance requires a fresh target')
        with closing(Catalog(self.path)) as adapter:
            adapter.seed()

    def connect(self):
        return Catalog(self.path, existing=True)

    def valid_plan(self, base):
        return fixture_plans(base, 1)[0]

    def invalid_plan(self, base):
        plan = deepcopy(self.valid_plan(base))
        plan['patches'][0]['unit_price_cents'] = -1
        return plan

    def simulate(self, base, plan):
        return Catalog.apply_to_snapshot(base, plan)

    def mutate(self):
        with closing(self.connect()) as adapter:
            adapter.mutate_for_stale_test()

    def receipts(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM foresee_receipts ORDER BY commit_id')]

    @contextmanager
    def fail_receipt_write(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON foresee_receipts BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END")
            db.commit()
        try:
            yield
        finally:
            with closing(sqlite3.connect(self.path)) as db:
                db.execute('DROP TRIGGER reject_receipt')
                db.commit()
