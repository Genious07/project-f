from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from foresee.catalog import Catalog, fixture_plans
from foresee.compiler import compile_source
from foresee.runtime import Runtime, replay_report, save_report, snapshot_json


ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "examples" / "repair.fore").read_text()


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / "catalog.db")
        self.catalog.seed()
        self.ir = compile_source(SOURCE)

    def tearDown(self) -> None:
        self.catalog.close()
        self.temp.cleanup()

    def test_end_to_end_selects_and_commits_complete_valid_plan(self) -> None:
        report = Runtime(self.ir, self.catalog).run()
        self.assertEqual(report["selection"]["plan_id"], "complete-derived-repair")
        self.assertEqual(report["outcome"]["status"], "applied")
        self.assertEqual(report["selection"]["score"], 0)
        self.assertEqual(self.catalog.unresolved_units(self.catalog.snapshot()), 0)
        rejected = {item["plan_id"] for item in report["exploration"] if not item["eligible"]}
        self.assertEqual(rejected, {"arithmetic-guess", "source-field-edit"})

    def test_commit_receipt_is_idempotent(self) -> None:
        base = self.catalog.snapshot()
        selection = {"base": snapshot_json(base), "plan": fixture_plans(base, 1)[0]}
        first = self.catalog.commit(selection, self.ir["program_digest"])
        second = self.catalog.commit(selection, self.ir["program_digest"])
        self.assertEqual(first["commit_id"], second["commit_id"])
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        count = self.catalog.connection.execute("SELECT COUNT(*) FROM foresee_receipts").fetchone()[0]
        self.assertEqual(count, 1)

    def test_stale_target_records_receipt_without_applying_plan(self) -> None:
        report = Runtime(self.ir, self.catalog, simulate_stale=True).run()
        self.assertEqual(report["outcome"]["status"], "stale")
        self.assertEqual(self.catalog.unresolved_units(self.catalog.snapshot()), 2)

    def test_replay_verifies_report_without_database(self) -> None:
        report = Runtime(self.ir, self.catalog).run()
        path = self.root / "report.json"
        save_report(report, path)
        self.catalog.close()
        (self.root / "catalog.db").rename(self.root / "catalog.offline")
        result = replay_report(path)
        self.assertTrue(result["verified"])
        self.assertEqual(result["live_calls"], 0)
        self.catalog = Catalog(self.root / "replacement.db")

    def test_replay_rejects_tampering(self) -> None:
        report = Runtime(self.ir, self.catalog).run()
        path = self.root / "report.json"
        save_report(report, path)
        altered = json.loads(path.read_text())
        altered["selection"]["score"] = 99
        path.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            replay_report(path)


if __name__ == "__main__":
    unittest.main()
