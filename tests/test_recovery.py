import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from foresee.catalog import Catalog
from foresee.journal import Journal, reconcile
from foresee.compiler import compile_source
from foresee.runtime import Runtime


ROOT = Path(__file__).parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def demo(self, workspace, *args):
        return subprocess.run([sys.executable, "-m", "foresee", "demo", "examples/repair.fore",
                               "--workspace", str(workspace), *args], cwd=ROOT,
                              capture_output=True, text=True, timeout=20)

    def state(self, workspace):
        with sqlite3.connect(workspace / "catalog.db") as db:
            return (db.execute("SELECT revision FROM catalog_meta").fetchone()[0],
                    db.execute("SELECT count(*) FROM foresee_receipts").fetchone()[0],
                    db.execute("SELECT count(*) FROM catalog_rows WHERE unit_price_cents IS NULL").fetchone()[0])

    def test_process_crashes_and_repeated_reconciliation_never_duplicate_effects(self):
        for stage in ("before_transaction", "before_commit", "after_commit"):
            with self.subTest(stage=stage):
                workspace = self.root / stage
                killed = self.demo(workspace, "--fault", stage)
                self.assertEqual(killed.returncode, 86, killed.stderr)
                expected = (1, 1, 0) if stage == "after_commit" else (0, 0, 2)
                self.assertEqual(self.state(workspace), expected)
                for _ in range(2):
                    result = subprocess.run([sys.executable, "-m", "foresee", "reconcile", str(workspace / "runs.db")],
                                            cwd=ROOT, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0 if stage == "after_commit" else 2, result.stderr)
                    recovered = json.loads(result.stdout)
                    self.assertEqual(recovered["target_writes"], 0)
                    outcome = recovered["runs"][0]["operations"][0]
                    self.assertEqual(outcome["status"], "applied" if stage == "after_commit" else "unresolved")
                    self.assertEqual(self.state(workspace), expected)
                with sqlite3.connect(workspace / "runs.db") as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM operations").fetchone()[0], 1)

    def test_committed_stale_receipt_is_recovered(self):
        self.assertEqual(self.demo(self.root, "--simulate-stale", "--fault", "after_commit").returncode, 86)
        result = reconcile(self.root / "runs.db")
        self.assertEqual(result["runs"][0]["operations"][0]["status"], "stale")
        self.assertEqual(self.state(self.root), (1, 1, 2))

    def test_missing_target_is_unresolved_and_not_created(self):
        self.assertEqual(self.demo(self.root, "--fault", "after_commit").returncode, 86)
        target = self.root / "catalog.db"
        target.rename(self.root / "saved.db")
        result = reconcile(self.root / "runs.db")
        self.assertEqual(result["runs"][0]["state"], "unresolved")
        self.assertFalse(target.exists())

    def test_replaced_target_is_not_mistaken_for_original(self):
        self.assertEqual(self.demo(self.root, "--fault", "after_commit").returncode, 86)
        (self.root / "catalog.db").rename(self.root / "saved.db")
        replacement = Catalog(self.root / "catalog.db")
        replacement.seed()
        replacement.close()
        result = reconcile(self.root / "runs.db")
        self.assertEqual(result["runs"][0]["operations"][0]["detail"], "target identity mismatch")
        self.assertEqual(self.state(self.root), (0, 0, 2))

    def test_inconsistent_receipt_is_unresolved(self):
        self.assertEqual(self.demo(self.root, "--fault", "after_commit").returncode, 86)
        with sqlite3.connect(self.root / "catalog.db") as db:
            db.execute("UPDATE foresee_receipts SET intent_digest='changed'")
        result = reconcile(self.root / "runs.db")
        self.assertEqual(result["runs"][0]["operations"][0]["status"], "unresolved")
        self.assertEqual(self.state(self.root), (1, 1, 0))

    def test_changed_journal_intent_is_unresolved(self):
        self.assertEqual(self.demo(self.root, "--fault", "after_commit").returncode, 86)
        with sqlite3.connect(self.root / "runs.db") as db:
            db.execute("UPDATE operations SET program_digest='changed'")
        result = reconcile(self.root / "runs.db")
        self.assertEqual(result["runs"][0]["operations"][0]["detail"], "journal intent identity mismatch")

    def test_completed_run_remains_completed_and_retains_run_id(self):
        result = self.demo(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        recovered = reconcile(self.root / "runs.db", summary["run_id"])
        self.assertEqual(recovered["runs"][0]["state"], "completed")
        self.assertEqual(recovered["runs"][0]["run_id"], summary["run_id"])
        self.assertEqual(self.state(self.root), (1, 1, 0))

    def test_started_run_without_intent_is_unresolved(self):
        journal = Journal(self.root / "runs.db")
        run_id = journal.start()
        journal.close()
        result = reconcile(self.root / "runs.db", run_id)
        self.assertEqual(result["runs"][0]["state"], "unresolved")
        self.assertEqual(result["runs"][0]["operations"], [])

    def test_missing_journal_is_not_created(self):
        path = self.root / "missing.db"
        with self.assertRaises(sqlite3.Error):
            reconcile(path)
        self.assertFalse(path.exists())

    def test_multiple_operations_have_distinct_ids_and_receipts(self):
        source = (ROOT / "examples/repair.fore").read_text().replace(
            "return commit chosen to catalog;",
            "let first = commit chosen to catalog; let second = select trials minimize unresolved; return commit second to catalog;")
        catalog = Catalog(self.root / "catalog.db")
        catalog.seed()
        journal = Journal(self.root / "runs.db")
        try:
            Runtime(compile_source(source), catalog, journal=journal).run()
        finally:
            catalog.close()
            journal.close()
        run = reconcile(self.root / "runs.db")["runs"][0]
        self.assertEqual(run["state"], "completed")
        self.assertEqual([o["status"] for o in run["operations"]], ["applied", "stale"])
        self.assertEqual(len({o["operation_id"] for o in run["operations"]}), 2)

    def test_completed_no_winner_run_needs_no_receipt(self):
        from unittest.mock import patch
        source = (ROOT / "examples/repair.fore").read_text()
        catalog = Catalog(self.root / "catalog.db")
        catalog.seed()
        journal = Journal(self.root / "runs.db")
        try:
            with patch("foresee.runtime.fixture_plans", return_value=[]):
                report = Runtime(compile_source(source), catalog, journal=journal).run()
            self.assertEqual(report["outcome"]["status"], "no_eligible_candidate")
        finally:
            catalog.close()
            journal.close()
        run = reconcile(self.root / "runs.db")["runs"][0]
        self.assertEqual(run["state"], "completed")
        self.assertEqual(run["operations"], [])


if __name__ == "__main__":
    unittest.main()
