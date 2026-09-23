import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from foresee.catalog import Catalog, fixture_plans
from foresee.runtime import snapshot_json


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "target.db"
        self.catalog = Catalog(self.path)
        self.catalog.seed()
        self.base = self.catalog.snapshot()
        self.selection = {"base": snapshot_json(self.base), "plan": fixture_plans(self.base, 1)[0]}

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def receipts(self):
        return self.catalog.connection.execute("SELECT count(*) FROM foresee_receipts").fetchone()[0]

    def test_concurrent_retry_has_one_effect_and_one_receipt(self):
        ready = threading.Barrier(4)
        def worker():
            catalog = Catalog(self.path)
            try:
                ready.wait(timeout=10)
                return catalog.commit(self.selection, "program", operation_id="same-operation")
            finally:
                catalog.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: worker(), range(4)))
        self.assertEqual({r["status"] for r in results}, {"applied"})
        self.assertEqual(len({r["commit_id"] for r in results}), 1)
        self.assertEqual(sum(not r["idempotent_replay"] for r in results), 1)
        self.assertEqual(self.catalog.snapshot().revision, 1)
        self.assertEqual(self.receipts(), 1)

    def test_conflicting_intent_cannot_reuse_operation_id(self):
        self.catalog.commit(self.selection, "program", operation_id="op")
        conflicting = deepcopy(self.selection)
        conflicting["plan"]["patches"] = conflicting["plan"]["patches"][:1]
        with self.assertRaisesRegex(RuntimeError, "different intent"):
            self.catalog.commit(conflicting, "program", operation_id="op")
        self.assertEqual(self.receipts(), 1)
        self.assertEqual(self.catalog.snapshot().revision, 1)

    def test_default_identity_excludes_intent(self):
        self.catalog.commit(self.selection, "program")
        changed = deepcopy(self.selection)
        changed["plan"]["id"] = "changed"
        with self.assertRaisesRegex(RuntimeError, "different intent"):
            self.catalog.commit(changed, "program")

    def test_snapshot_is_consistent_across_interleaved_writer(self):
        self.catalog.connection.execute("PRAGMA journal_mode=WAL")
        writer = sqlite3.connect(self.path)
        wrote = []
        def interleave(sql):
            if sql.startswith("SELECT * FROM catalog_rows") and not wrote:
                with writer:
                    writer.execute("UPDATE catalog_rows SET title='new title' WHERE id='coffee'")
                    writer.execute("UPDATE catalog_meta SET revision=revision+1")
                wrote.append(True)
        self.catalog.connection.set_trace_callback(interleave)
        try:
            captured = self.catalog.snapshot()
        finally:
            self.catalog.connection.set_trace_callback(None)
            writer.close()
        self.assertEqual(wrote, [True])
        self.assertEqual(captured.digest, self.base.digest)
        self.assertEqual(self.catalog.snapshot().revision, 1)

    def test_invalid_patches_leave_rows_revision_and_receipts_unchanged(self):
        cases = [
            [{"id": "coffee", "unit_price_cents": value}]
            for value in (True, 1.0, "150", None, -1, 2**63, 151)
        ] + [
            [{"id": "coffee"}],
            [{"id": "coffee", "title": "rewrite", "unit_price_cents": 150}],
            [{"id": "absent", "unit_price_cents": 150}],
            [{"id": "coffee", "unit_price_cents": 150}] * 2,
        ]
        for patches in cases:
            with self.subTest(patches=patches):
                selection = deepcopy(self.selection)
                selection["plan"]["patches"] = patches
                with self.assertRaises((ValueError, RuntimeError)):
                    self.catalog.commit(selection, "program")
                self.assertEqual(self.catalog.snapshot().digest, self.base.digest)
                self.assertEqual(self.receipts(), 0)

    def test_failed_receipt_insert_rolls_back_all_changes(self):
        self.catalog.connection.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON foresee_receipts BEGIN SELECT RAISE(ABORT, 'receipt failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt failure"):
            self.catalog.commit(self.selection, "program")
        self.assertEqual(self.catalog.snapshot().digest, self.base.digest)
        self.assertEqual(self.receipts(), 0)

    def test_postcondition_detects_trigger_changes(self):
        self.catalog.connection.execute("CREATE TRIGGER corrupt_row AFTER UPDATE ON catalog_rows BEGIN UPDATE catalog_rows SET title='unexpected' WHERE id=NEW.id; END")
        with self.assertRaisesRegex(RuntimeError, "postcondition"):
            self.catalog.commit(self.selection, "program")
        self.assertEqual(self.catalog.snapshot().digest, self.base.digest)
        self.assertEqual(self.receipts(), 0)

    def test_stale_receipt_retry_is_terminal(self):
        self.catalog.mutate_for_stale_test()
        first = self.catalog.commit(self.selection, "program")
        second = self.catalog.commit(self.selection, "program")
        self.assertEqual(first["status"], "stale")
        self.assertEqual(second["status"], "stale")
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(self.catalog.unresolved_units(self.catalog.snapshot()), 2)
        self.assertEqual(self.receipts(), 1)

    def test_caller_transaction_is_not_committed_or_rolled_back(self):
        self.catalog.connection.execute("BEGIN")
        self.catalog.connection.execute("UPDATE catalog_rows SET title='pending' WHERE id='coffee'")
        self.catalog.snapshot()
        with self.assertRaisesRegex(RuntimeError, "idle connection"):
            self.catalog.commit(self.selection, "program")
        self.assertTrue(self.catalog.connection.in_transaction)
        self.catalog.connection.rollback()
        self.assertEqual(self.catalog.snapshot().digest, self.base.digest)


if __name__ == "__main__":
    unittest.main()
