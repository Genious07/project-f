import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from foresee.catalog import Catalog, stable_digest
from foresee.compiler import compile_source
from foresee.runtime import Runtime, replay_report, save_report


SOURCE = (Path(__file__).parents[1] / "examples/repair.fore").read_text()


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = Catalog(self.root / "catalog.db")
        self.catalog.seed()
        self.ir = compile_source(SOURCE)
        self.report = Runtime(self.ir, self.catalog).run()
        self.path = self.root / "report.json"

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def write(self, report):
        # Recompute the outer checksum, as an editor could do.
        report = deepcopy(report)
        report.pop("report_digest", None)
        report["report_digest"] = stable_digest(report)
        save_report(report, self.path)

    def test_replays_with_all_live_access_disabled(self):
        self.write(self.report)
        with patch("sqlite3.connect", side_effect=AssertionError("live DB access")), \
             patch("foresee.runtime.fixture_plans", side_effect=AssertionError("provider access")), \
             patch.object(Catalog, "commit", side_effect=AssertionError("live write")), \
             patch.object(Catalog, "snapshot", side_effect=AssertionError("live read")):
            result = replay_report(self.path)
        self.assertTrue(result["decision_reproduced"])
        self.assertTrue(result["checksum_valid"])
        self.assertFalse(result["origin_authenticated"])
        self.assertFalse(result["target_effect_verified"])
        self.assertEqual(result["live_calls"], 0)

    def test_changed_metric_with_recomputed_checksum_is_rejected(self):
        self.report["exploration"][0]["metrics"]["unresolved"] = 99
        self.write(self.report)
        with self.assertRaisesRegex(ValueError, "exploration"):
            replay_report(self.path)

    def test_changed_event_and_summary_are_still_rejected(self):
        self.report["exploration"][0]["checks"][0]["passed"] = False
        event = next(e for e in self.report["evidence"]["events"] if e["kind"] == "exploration")
        event["data"] = deepcopy(self.report["exploration"])
        self.write(self.report)
        with self.assertRaisesRegex(ValueError, "exploration"):
            replay_report(self.path)

    def test_different_winner_is_rejected(self):
        self.report["selection"]["plan_id"] = "partial-repair"
        self.write(self.report)
        with self.assertRaisesRegex(ValueError, "selection"):
            replay_report(self.path)

    def test_missing_reordered_and_extra_events_fail(self):
        for change in ("missing", "reordered", "extra"):
            with self.subTest(change=change):
                report = deepcopy(self.report)
                events = report["evidence"]["events"]
                if change == "missing":
                    events.pop(0)
                elif change == "reordered":
                    events[0], events[1] = events[1], events[0]
                else:
                    events.append(deepcopy(events[-1]))
                self.write(report)
                with self.assertRaises(ValueError):
                    replay_report(self.path)

    def test_program_identity_and_inferred_types_are_checked(self):
        for mode in ("identity", "type"):
            with self.subTest(mode=mode):
                report = deepcopy(self.report)
                if mode == "identity":
                    report["program_digest"] = "wrong"
                else:
                    ir = report["evidence"]["ir"]
                    ir["decisions"][0]["body"][0]["value"]["inferred_type"]["lineage"] = "forged"
                    ir.pop("program_digest")
                    ir["program_digest"] = stable_digest(ir)
                    report["program_digest"] = ir["program_digest"]
                self.write(report)
                with self.assertRaisesRegex(ValueError, "identity|typed IR"):
                    replay_report(self.path)

    def test_snapshot_digest_and_receipt_reference_are_checked(self):
        for kind in ("snapshot", "commit"):
            with self.subTest(kind=kind):
                report = deepcopy(self.report)
                data = next(e["data"] for e in report["evidence"]["events"] if e["kind"] == kind)
                if kind == "snapshot":
                    data["snapshot"]["rows"][0]["title"] = "changed"
                else:
                    data["outcome"]["commit_id"] = "wrong"
                self.write(report)
                with self.assertRaises(ValueError):
                    replay_report(self.path)

    def test_redaction_or_missing_evidence_does_not_pass(self):
        for mode in ("redacted", "missing"):
            report = deepcopy(self.report)
            if mode == "redacted":
                report["evidence"]["redacted"] = True
            else:
                del report["evidence"]
            self.write(report)
            with self.assertRaises(ValueError):
                replay_report(self.path)

    def test_legacy_reports_only_claim_checksum_verification(self):
        report = deepcopy(self.report)
        report["report_version"] = "0.0.1"
        del report["evidence"]
        self.write(report)
        result = replay_report(self.path)
        self.assertTrue(result["checksum_valid"])
        self.assertFalse(result["decision_reproduced"])

    def test_no_winner_stale_and_multiple_operations_reproduce(self):
        source = SOURCE.replace("return commit chosen to catalog;", "let first = commit chosen to catalog; let next = select trials minimize unresolved; return commit next to catalog;")
        # Use a fresh target for each scenario.
        for scenario in ("no_winner", "stale", "multiple"):
            catalog = Catalog(self.root / (scenario + ".db"))
            catalog.seed()
            try:
                runtime = Runtime(compile_source(source if scenario == "multiple" else SOURCE), catalog, simulate_stale=scenario == "stale")
                if scenario == "no_winner":
                    with patch("foresee.runtime.fixture_plans", return_value=[]):
                        report = runtime.run()
                else:
                    report = runtime.run()
                self.write(report)
                self.assertTrue(replay_report(self.path)["decision_reproduced"])
            finally:
                catalog.close()


if __name__ == "__main__":
    unittest.main()
