"""Reusable storage-adapter contract tests for Foresee's current catalog domain."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
from typing import Protocol
import unittest

from .catalog import Snapshot


class AdapterFixture(Protocol):
    """Every fixture owns a new disposable target beneath the supplied directory.

    connect() returns an independent closable ResourceProvider. Fixture helpers
    inspect persisted state and inject failures; they must not implement commit
    on the adapter's behalf. Connections used by threads are opened there.
    """
    def connect(self): ...
    def valid_plan(self, base: Snapshot) -> dict: ...
    def invalid_plan(self, base: Snapshot) -> dict: ...
    def simulate(self, base: Snapshot, plan: dict) -> Snapshot: ...
    def mutate(self) -> None: ...
    def receipts(self) -> list[dict]: ...
    def fail_receipt_write(self):
        """Context manager: force persisted receipt creation to raise."""
        ...


class InjectedFailure(RuntimeError):
    pass


class AdapterContract(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='foresee-adapter-')
        self.addCleanup(directory.cleanup)
        self.fixture = self.factory(Path(directory.name))
        self.adapter = self.fixture.connect()
        self.addCleanup(self.adapter.close)
        self.base = self.adapter.snapshot()
        self.selection = {'base': {'revision': self.base.revision, 'digest': self.base.digest,
                                  'rows': [dict(row) for row in self.base.rows]},
                          'plan': self.fixture.valid_plan(self.base)}
        self.assertEqual(self.fixture.receipts(), [], 'fixture must start without receipts')

    def commit(self, **kwargs):
        return self.adapter.commit(self.selection, 'conformance-program', operation_id='operation-1', **kwargs)

    def assert_unchanged(self, base=None):
        base = base or self.base
        with closing(self.fixture.connect()) as reader:
            current = reader.snapshot()
        self.assertEqual((current.revision, current.digest, current.rows), (base.revision, base.digest, base.rows))

    def test_snapshot_is_immutable_and_identity_persists(self):
        self.assertTrue(self.adapter.target_id)
        with closing(self.fixture.connect()) as reader:
            self.assertEqual(reader.target_id, self.adapter.target_id)
            self.assertEqual(reader.snapshot(), self.base)
        self.assertTrue(self.base.rows, 'fixture must contain rows')
        with self.assertRaises(TypeError):
            self.base.rows[0]['id'] = 'changed'
        frozen = deepcopy(self.selection['base'])
        self.fixture.mutate()
        self.assertEqual([dict(row) for row in self.base.rows], frozen['rows'])
        self.assertEqual(self.base.digest, frozen['digest'])
        self.assertNotEqual(self.adapter.snapshot().digest, self.base.digest)

    def test_simulation_does_not_write(self):
        simulated = self.fixture.simulate(self.base, deepcopy(self.selection['plan']))
        self.assertNotEqual(simulated.rows, self.base.rows, 'valid plan must change fixture rows')
        self.assert_unchanged()
        self.assertEqual(self.fixture.receipts(), [])

    def test_commit_persists_rows_revision_and_receipt(self):
        expected = self.fixture.simulate(self.base, deepcopy(self.selection['plan']))
        original = deepcopy(self.selection)
        outcome = self.commit()
        self.assertEqual(outcome['status'], 'applied')
        self.assertFalse(outcome['idempotent_replay'])
        self.assertEqual(self.selection, original, 'adapter mutated caller selection')
        with closing(self.fixture.connect()) as reader:
            current = reader.snapshot()
        self.assertEqual(current.rows, expected.rows)
        self.assertEqual(current.revision, self.base.revision + 1)
        self.assertEqual(outcome['revision'], current.revision)
        receipts = self.fixture.receipts()
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['commit_id'], outcome['commit_id'])
        self.assertEqual(receipts[0]['status'], 'applied')

    def test_retry_is_idempotent_after_reopen(self):
        first = self.commit()
        before = self.adapter.snapshot()
        receipts = self.fixture.receipts()
        with closing(self.fixture.connect()) as reopened:
            again = reopened.commit(self.selection, 'conformance-program', operation_id='operation-1')
        self.assertEqual(again['commit_id'], first['commit_id'])
        self.assertEqual(again['status'], 'applied')
        self.assertTrue(again['idempotent_replay'])
        self.assert_unchanged(before)
        self.assertEqual(self.fixture.receipts(), receipts)

    def test_conflicting_intent_cannot_reuse_operation(self):
        self.commit()
        before = self.adapter.snapshot()
        receipts = self.fixture.receipts()
        changed = deepcopy(self.selection)
        changed['plan']['id'] += '-different-intent'
        with self.assertRaises((ValueError, RuntimeError)):
            self.adapter.commit(changed, 'conformance-program', operation_id='operation-1')
        self.assert_unchanged(before)
        self.assertEqual(self.fixture.receipts(), receipts)

    def test_invalid_plan_has_no_effect_or_receipt(self):
        changed = deepcopy(self.selection)
        changed['plan'] = self.fixture.invalid_plan(self.base)
        with self.assertRaises((ValueError, RuntimeError)):
            self.adapter.commit(changed, 'conformance-program', operation_id='operation-1')
        self.assert_unchanged()
        self.assertEqual(self.fixture.receipts(), [])

    def test_stale_receipt_is_terminal(self):
        self.fixture.mutate()
        before = self.adapter.snapshot()
        first = self.commit()
        self.assertEqual(first['status'], 'stale')
        self.assert_unchanged(before)
        with closing(self.fixture.connect()) as reopened:
            again = reopened.commit(self.selection, 'conformance-program', operation_id='operation-1')
        self.assertEqual(again['status'], 'stale')
        self.assertTrue(again['idempotent_replay'])
        self.assertEqual(first['commit_id'], again['commit_id'])
        self.assertEqual(len(self.fixture.receipts()), 1)
        self.assert_unchanged(before)

    def test_precommit_faults_hide_and_rollback_writes(self):
        for stage in ('before_transaction', 'before_commit'):
            with self.subTest(stage=stage):
                visited = []
                def fail(point):
                    if point == stage:
                        visited.append(point)
                        self.assert_unchanged()
                        self.assertEqual(self.fixture.receipts(), [])
                        raise InjectedFailure(point)
                with self.assertRaises(InjectedFailure):
                    self.commit(fault_hook=fail)
                self.assertEqual(visited, [stage], 'adapter must expose the fault boundary')
                self.assert_unchanged()
                self.assertEqual(self.fixture.receipts(), [])

    def test_receipt_failure_rolls_back_effect(self):
        with self.fixture.fail_receipt_write():
            with self.assertRaises(Exception):
                self.commit()
        self.assert_unchanged()
        self.assertEqual(self.fixture.receipts(), [])
        self.assertEqual(self.commit()['status'], 'applied', 'target must remain usable')

    def test_lost_acknowledgment_is_recoverable_without_duplicate_effect(self):
        def fail(stage):
            if stage == 'after_commit':
                raise InjectedFailure(stage)
        with self.assertRaises(InjectedFailure):
            self.commit(fault_hook=fail)
        current = self.adapter.snapshot()
        self.assertEqual(current.revision, self.base.revision + 1)
        self.assertEqual(current.rows, self.fixture.simulate(self.base, deepcopy(self.selection['plan'])).rows)
        receipts = self.fixture.receipts()
        self.assertEqual(len(receipts), 1)
        with closing(self.fixture.connect()) as reopened:
            recovered = reopened.commit(self.selection, 'conformance-program', operation_id='operation-1')
        self.assertTrue(recovered['idempotent_replay'])
        self.assertEqual(recovered['commit_id'], receipts[0]['commit_id'])
        self.assertEqual(recovered['status'], 'applied')
        self.assertEqual(self.adapter.snapshot().revision, self.base.revision + 1)
        self.assertEqual(self.fixture.receipts(), receipts)

    def test_runtime_evidence_replays_offline(self):
        from .compiler import compile_source
        from .project import SOURCE
        from .providers import CandidateProvider
        from .replay import reproduce
        from .runtime import Runtime
        report = Runtime(compile_source(SOURCE), self.adapter,
                         model_provider=CandidateProvider([self.fixture.valid_plan(self.base)])).run()
        self.assertEqual(report['outcome']['status'], 'applied')
        self.assertTrue(report['evidence']['complete'])
        self.assertTrue(reproduce(report))

    def test_concurrent_retry_has_one_effect(self):
        ready = threading.Barrier(4)
        def attempt(_):
            with closing(self.fixture.connect()) as adapter:
                ready.wait(timeout=10)
                return adapter.commit(deepcopy(self.selection), 'conformance-program', operation_id='operation-1')
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(attempt, range(4)))
        self.assertEqual({o['status'] for o in outcomes}, {'applied'})
        self.assertEqual(len({o['commit_id'] for o in outcomes}), 1)
        self.assertEqual(sum(not o['idempotent_replay'] for o in outcomes), 1)
        self.assertEqual(self.adapter.snapshot().revision, self.base.revision + 1)
        self.assertEqual(len(self.fixture.receipts()), 1)


def adapter_suite(factory, name='Adapter'):
    """Return fresh tests. The factory receives only a disposable directory."""
    case = type(name + 'Contract', (AdapterContract,), {'factory': staticmethod(factory)})
    return unittest.defaultTestLoader.loadTestsFromTestCase(case)


if __name__ == '__main__':
    from .catalog_conformance import CatalogFixture
    result = unittest.TextTestRunner(verbosity=2).run(adapter_suite(CatalogFixture, 'SQLiteCatalog'))
    raise SystemExit(0 if result.wasSuccessful() else 1)
