import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from foresee.catalog import Catalog, fixture_plans
from foresee.compiler import compile_source
from foresee.model import CompileFailure
from foresee.runtime import Runtime, Selected, TrialSet


SOURCE = (Path(__file__).parents[1] / "examples/repair.fore").read_text()


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Catalog(Path(self.temp.name) / "catalog.db")
        self.catalog.seed()
        self.ir = compile_source(SOURCE)

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def prepare_selection(self):
        runtime = Runtime(self.ir, self.catalog)
        env = {}
        for statement in self.ir["decisions"][0]["body"][:-1]:
            runtime.exec_statement(statement, env, False)
        return runtime, env, self.ir["decisions"][0]["body"][-1]["value"]

    def test_compiler_rejects_double_commit_and_alias_reuse(self):
        for ending in (
            "let first = commit chosen to catalog; return commit chosen to catalog;",
            "let alias = chosen; let first = commit alias to catalog; return commit chosen to catalog;",
            "let first = commit chosen to catalog; let alias = chosen; return first;",
        ):
            with self.subTest(ending=ending), self.assertRaises(CompileFailure) as result:
                compile_source(SOURCE.replace("return commit chosen to catalog;", ending))
            self.assertIn("F3400", {d.code for d in result.exception.diagnostics})

    def test_alias_can_be_consumed_once(self):
        ir = compile_source(SOURCE.replace("return commit chosen to catalog;", "let alias = chosen; return commit alias to catalog;"))
        self.assertEqual(Runtime(ir, self.catalog).run()["outcome"]["status"], "applied")

    def test_exactly_one_simulation_is_required(self):
        for source in (
            SOURCE.replace("simulate catalog.apply(plan)", "base"),
            SOURCE.replace("let after =", "let extra = simulate catalog.apply(plan); let after ="),
        ):
            with self.assertRaises(CompileFailure) as result:
                compile_source(source)
            self.assertIn("F3401", {d.code for d in result.exception.diagnostics})

    def test_runtime_rejects_reuse_and_forged_or_foreign_selection(self):
        runtime, env, commit = self.prepare_selection()
        original = env["chosen"]
        foreign, foreign_env, _ = self.prepare_selection()
        for forged in ({"plan": {}}, Selected(), foreign_env["chosen"]):
            env["chosen"] = forged
            with self.assertRaisesRegex(RuntimeError, "forged, foreign, or already consumed"):
                runtime.eval_expr(commit, env, False)
        self.assertEqual(self.catalog.snapshot().revision, 0)
        env["chosen"] = original
        self.assertEqual(runtime.eval_expr(commit, env, False)["status"], "applied")
        with self.assertRaisesRegex(RuntimeError, "already consumed"):
            runtime.eval_expr(commit, env, False)
        self.assertEqual(self.catalog.snapshot().revision, 1)

    def test_selection_consumed_even_when_adapter_raises(self):
        runtime, env, commit = self.prepare_selection()
        with patch.object(self.catalog, "commit", side_effect=RuntimeError("adapter failure")) as adapter:
            with self.assertRaisesRegex(RuntimeError, "adapter failure"):
                runtime.eval_expr(commit, env, False)
            with self.assertRaisesRegex(RuntimeError, "already consumed"):
                runtime.eval_expr(commit, env, False)
            self.assertEqual(adapter.call_count, 1)

    def test_forged_trial_set_cannot_mint_selection(self):
        runtime = Runtime(self.ir, self.catalog)
        select = self.ir["decisions"][0]["body"][3]["value"]
        for forged in ([], TrialSet()):
            with self.assertRaisesRegex(RuntimeError, "completed exploration"):
                runtime.eval_expr(select, {"trials": forged}, False)

    def test_snapshots_are_read_only_and_do_not_alias_exported_rows(self):
        from foresee.runtime import snapshot_json
        base = self.catalog.snapshot()
        with self.assertRaises(TypeError):
            base.rows[0]["title"] = "changed"
        exported = snapshot_json(base)
        exported["rows"][0]["title"] = "changed"
        self.assertNotEqual(base.rows[0]["title"], "changed")

    def test_each_branch_has_its_own_plan_and_outer_variables(self):
        runtime = Runtime(self.ir, self.catalog)
        env = {}
        body = self.ir["decisions"][0]["body"]
        for statement in body[:2]:
            runtime.exec_statement(statement, env, False)
        original = deepcopy(env["plans"])
        apply = Catalog.apply_to_snapshot
        seen = []
        def mutating_branch(base, plan):
            seen.append(plan["id"])
            result = apply(base, plan)
            plan["patches"].clear()
            return result
        with patch.object(Catalog, "apply_to_snapshot", side_effect=mutating_branch):
            runtime.exec_statement(body[2], env, False)
        self.assertEqual(env["plans"], original)
        self.assertEqual(len(seen), 4)
        self.assertEqual(self.catalog.unresolved_units(env["base"]), 2)

    def test_complete_exploration_and_tie_break_are_order_independent(self):
        plans = fixture_plans(self.catalog.snapshot(), 1)
        a, b = deepcopy(plans[0]), deepcopy(plans[0])
        a["id"], b["id"] = "alpha", "beta"
        winners = []
        for order in ([b, a], [a, b]):
            runtime = Runtime(self.ir, self.catalog)
            env = {}
            with patch("foresee.runtime.fixture_plans", return_value=order):
                for statement in self.ir["decisions"][0]["body"][:-1]:
                    runtime.exec_statement(statement, env, False)
            winners.append(runtime.selection["plan_id"])
            self.assertEqual(len(runtime.exploration), 2)
        self.assertEqual(winners, ["alpha", "alpha"])

    def test_no_winner_and_branch_failures_are_recorded_without_writes(self):
        invalid = {"id": "missing", "patches": [{"id": "absent", "unit_price_cents": 1}]}
        rejected = fixture_plans(self.catalog.snapshot(), 4)[2]
        with patch("foresee.runtime.fixture_plans", return_value=[invalid, rejected]):
            report = Runtime(self.ir, self.catalog).run()
        self.assertEqual(report["outcome"]["status"], "no_eligible_candidate")
        self.assertEqual([t["status"] for t in report["exploration"]], ["evaluation_failed", "rejected"])
        self.assertEqual(self.catalog.snapshot().revision, 0)
        self.assertEqual(self.catalog.connection.execute("SELECT count(*) FROM foresee_receipts").fetchone()[0], 0)

    def test_duplicate_candidate_ids_are_rejected(self):
        plan = fixture_plans(self.catalog.snapshot(), 1)[0]
        with patch("foresee.runtime.fixture_plans", return_value=[plan, plan]):
            report = Runtime(self.ir, self.catalog).run()
        self.assertEqual(report["outcome"]["status"], "invalid_plans")
        self.assertEqual(self.catalog.snapshot().revision, 0)


if __name__ == "__main__":
    unittest.main()
