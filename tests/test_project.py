import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from foresee.catalog import Catalog
from foresee.compiler import compile_source
from foresee.project import SOURCE, init_project, run_project
from foresee.providers import FixedClock, ProviderError
from foresee.runtime import Runtime, replay_report, save_report


ROOT = Path(__file__).parents[1]


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.config = init_project(self.project, demo_data=True)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "foresee", *args], cwd=self.project,
                              env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, timeout=20)

    def test_full_workflow_from_new_project_directory(self):
        self.assertEqual(self.cli("check", "decision.fore").returncode, 0)
        self.assertEqual(self.cli("build", "decision.fore", "-o", ".foresee/ir.json").returncode, 0)
        run = self.cli("run", "--entry", "repair_catalog")
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["outcome"]["status"], "applied")
        inspected = self.cli("inspect", result["report"])
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(len(json.loads(inspected.stdout)["candidates"]), 1)
        replay = self.cli("replay", result["report"])
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertTrue(json.loads(replay.stdout)["decision_reproduced"])
        self.assertEqual(self.cli("reconcile", result["journal"]).returncode, 0)

    def test_init_without_demo_data_and_run_never_seed(self):
        empty = self.root / "empty"
        config = init_project(empty)
        with patch.object(Catalog, "seed", side_effect=AssertionError("unexpected seed")):
            result = run_project(config)
        self.assertEqual(result["outcome"]["status"], "no_eligible_candidate")
        with sqlite3.connect(empty / "catalog.db") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM catalog_rows").fetchone()[0], 0)

    def test_missing_target_is_not_created(self):
        target = self.project / "catalog.db"
        target.rename(self.project / "saved.db")
        with self.assertRaises(sqlite3.Error):
            run_project(self.config)
        self.assertFalse(target.exists())

    def test_malformed_fixtures_fail_before_target_open(self):
        cases = [None, [{"id": "x", "patches": [{"id": "coffee", "unit_price_cents": True}]}],
                 [{"id": "x", "patches": []}] * 2, [{"id": str(i), "patches": []} for i in range(5)]]
        for plans in cases:
            (self.project / "plans.json").write_text(json.dumps(plans))
            with self.subTest(plans=plans), patch("foresee.project.Catalog.__init__", side_effect=AssertionError("opened target")):
                with self.assertRaises(ValueError):
                    run_project(self.config)

    def test_entry_and_configuration_fail_before_target_open(self):
        with patch("foresee.project.Catalog.__init__", side_effect=AssertionError("opened target")):
            with self.assertRaisesRegex(ValueError, "entry"):
                run_project(self.config, "absent")
        config = json.loads(self.config.read_text())
        config["output"] = "catalog.db"
        config["max_candidates"] = 0
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "max_candidates"):
            run_project(self.config)

    def test_init_refuses_to_overwrite_existing_project(self):
        original = self.config.read_bytes()
        with self.assertRaises(FileExistsError):
            init_project(self.project, demo_data=True)
        self.assertEqual(original, self.config.read_bytes())

    def test_user_rows_and_fixtures_work_without_source_edits(self):
        with sqlite3.connect(self.project / "catalog.db") as db:
            db.execute("DELETE FROM catalog_rows")
            db.execute("INSERT INTO catalog_rows VALUES ('tea', 'Custom tea', 900, 3, NULL)")
            db.execute("UPDATE catalog_meta SET revision=revision+1")
        (self.project / "plans.json").write_text(json.dumps([{"id": "custom", "patches": [{"id": "tea", "unit_price_cents": 300}]}]))
        result = run_project(self.config)
        self.assertEqual(result["selection"]["plan_id"], "custom")
        with sqlite3.connect(self.project / "catalog.db") as db:
            self.assertEqual(db.execute("SELECT title, unit_price_cents FROM catalog_rows").fetchall(), [("Custom tea", 300)])

    def test_provider_error_and_clock_are_injected(self):
        class Broken:
            def propose(self, base, prompt, limit):
                raise ProviderError("fixture unavailable")
        catalog = Catalog(self.project / "catalog.db", existing=True)
        try:
            report = Runtime(compile_source(SOURCE), catalog, model_provider=Broken(), clock=FixedClock(123)).run()
            self.assertEqual(report["outcome"]["status"], "provider_error")
            self.assertEqual(report["recorded_at"], 123)
            self.assertEqual(catalog.snapshot().revision, 0)
            path = self.root / "failed.json"
            save_report(report, path)
            with self.assertRaisesRegex(ValueError, "incomplete"):
                replay_report(path)
        finally:
            catalog.close()

    def test_evidence_budget_stops_before_commit(self):
        catalog = Catalog(self.project / "catalog.db", existing=True)
        try:
            with patch.object(catalog, "commit", side_effect=AssertionError("write")):
                report = Runtime(compile_source(SOURCE), catalog, max_evidence_bytes=1).run()
            self.assertEqual(report["outcome"]["status"], "evidence_limit")
            self.assertFalse(report["evidence"]["complete"])
            self.assertEqual(catalog.snapshot().revision, 0)
        finally:
            catalog.close()

    def test_bad_schema_is_not_initialized_or_modified(self):
        config = json.loads(self.config.read_text())
        config["target"] = "unprepared.db"
        self.config.write_text(json.dumps(config))
        with sqlite3.connect(self.project / "unprepared.db") as db:
            db.execute("CREATE TABLE personal (value TEXT)")
        with self.assertRaises((ValueError, sqlite3.Error)):
            run_project(self.config)
        with sqlite3.connect(self.project / "unprepared.db") as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("personal",)])


if __name__ == "__main__":
    unittest.main()
