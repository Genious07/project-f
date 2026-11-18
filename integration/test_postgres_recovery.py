"""Real PostgreSQL journal recovery, including parent-issued SIGKILL."""
from contextlib import closing
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest

from foresee.compiler import compile_source
from foresee.journal import Journal, reconcile
from foresee.postgres import PostgresCatalog
from foresee.postgres_fixture import PostgresFixture
from foresee.project import SOURCE
from foresee.replay import reproduce
from foresee.runtime import Runtime


CHILD = r'''
import json, os, sys
from pathlib import Path
from foresee.compiler import compile_source
from foresee.journal import Journal
from foresee.postgres import PostgresCatalog
from foresee.project import SOURCE
from foresee.runtime import Runtime
adapter = PostgresCatalog(os.environ['FORESEE_TEST_POSTGRES_DSN'], sys.argv[1], target_name='catalog')
journal = Journal(Path(sys.argv[2]))
def hook(stage):
    if stage == sys.argv[3]:
        print(json.dumps({'stage': stage, 'backend': adapter.connection.info.backend_pid}), flush=True)
        sys.stdin.read()  # Parent kills us here, without Python cleanup.
Runtime(compile_source(SOURCE), adapter, journal=journal, fault_hook=hook).run()
raise SystemExit('parent did not terminate the worker')
'''


class PostgresRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='foresee-pg-recovery-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'journal.db'
        self.fixture = PostgresFixture(os.environ.get('FORESEE_TEST_POSTGRES_DSN'))
        self.addCleanup(self.fixture.close)
        self.adapter = PostgresCatalog(os.environ['FORESEE_TEST_POSTGRES_DSN'], self.fixture.schema, target_name='catalog')
        self.addCleanup(self.adapter.close)
        self.base = self.adapter.snapshot()
        self.targets = {'catalog': {'dsn': os.environ['FORESEE_TEST_POSTGRES_DSN'], 'schema': self.fixture.schema}}

    def run_program(self, **kwargs):
        with closing(Journal(self.path)) as journal:
            return Runtime(compile_source(SOURCE), self.adapter, journal=journal, **kwargs).run()

    def recover(self, **kwargs):
        return reconcile(self.path, postgres_targets=kwargs.get('targets', self.targets))

    def test_journaled_runtime_and_repeat_recovery_preserve_target(self):
        report = self.run_program()
        self.assertEqual(report['outcome']['status'], 'applied')
        self.assertTrue(reproduce(report))
        before = self.adapter.snapshot()
        receipts = self.fixture.receipts()
        for _ in range(2):
            recovered = self.recover()
            self.assertEqual(recovered['target_writes'], 0)
            self.assertEqual(recovered['runs'][0]['state'], 'completed')
            self.assertEqual(recovered['runs'][0]['operations'][0]['status'], 'applied')
        self.assertEqual(self.adapter.snapshot(), before)
        self.assertEqual(self.fixture.receipts(), receipts)
        with closing(Journal(self.path, existing=True)) as journal:
            operation = journal.connection.execute('SELECT * FROM operations').fetchone()
            self.assertEqual(operation['target_path'], '')
            reference = json.loads(journal.connection.execute('SELECT reference FROM operation_targets').fetchone()[0])
            self.assertEqual(reference, self.adapter.journal_reference)
        self.assertNotIn(os.environ['FORESEE_TEST_POSTGRES_DSN'], self.path.read_bytes().decode(errors='replace'))
        self.assertNotIn(os.environ['FORESEE_TEST_POSTGRES_DSN'], json.dumps(report))

    def test_database_error_leaves_prepared_intent_and_redacted_report(self):
        with self.fixture.fail_receipt_write():
            report = self.run_program()
        self.assertEqual(report['outcome']['status'], 'commit_unresolved')
        self.assertFalse(report['evidence']['complete'])
        self.assertNotIn('injected receipt failure', json.dumps(report))
        self.assertEqual(self.adapter.snapshot(), self.base)
        self.assertEqual(self.fixture.receipts(), [])
        self.assertEqual(self.recover()['runs'][0]['state'], 'unresolved')

    def test_configuration_and_identity_mismatch_do_not_infer_success(self):
        self.run_program()
        before, receipts = self.adapter.snapshot(), self.fixture.receipts()
        for targets in ({}, {'catalog': {**self.targets['catalog'], 'schema': 'different'}}):
            self.assertEqual(self.recover(targets=targets)['runs'][0]['state'], 'unresolved')
        # Same name/schema reference may point to a replacement target. UUID must match.
        with self.fixture.database() as db:
            db.execute("UPDATE foresee_target SET target_id='00000000-0000-0000-0000-000000000000'")
        self.assertEqual(self.recover()['runs'][0]['state'], 'unresolved')
        self.assertEqual(self.adapter.snapshot(), before)
        self.assertEqual(self.fixture.receipts(), receipts)

    def test_corrupt_receipt_and_intent_are_unresolved(self):
        self.run_program()
        with self.fixture.database() as db:
            db.execute("UPDATE foresee_receipts SET intent_digest='tampered'")
        before = self.adapter.snapshot()
        self.assertEqual(self.recover()['runs'][0]['state'], 'unresolved')
        with closing(Journal(self.path, existing=True)) as journal, journal.connection:
            journal.connection.execute("UPDATE operations SET intent_digest='tampered-journal'")
        self.assertEqual(self.recover()['runs'][0]['state'], 'unresolved')
        self.assertEqual(self.adapter.snapshot(), before)

    def test_stale_receipt_reconciles_without_applying(self):
        def mutate(stage):
            if stage == 'before_transaction':
                self.fixture.mutate()
        report = self.run_program(fault_hook=mutate)
        self.assertEqual(report['outcome']['status'], 'stale')
        before = self.adapter.snapshot()
        self.assertEqual(self.recover()['runs'][0]['operations'][0]['status'], 'stale')
        self.assertEqual(self.adapter.snapshot(), before)
        self.assertEqual(before.revision, 1)
        self.assertIsNone(before.rows[0]['unit_price_cents'])

    def test_absent_local_name_cannot_prepare_remote_intent(self):
        with closing(PostgresCatalog(os.environ['FORESEE_TEST_POSTGRES_DSN'], self.fixture.schema)) as adapter:
            with closing(Journal(self.path)) as journal:
                with self.assertRaisesRegex(ValueError, 'local target name'):
                    Runtime(compile_source(SOURCE), adapter, journal=journal).run()
                self.assertEqual(journal.connection.execute('SELECT count(*) FROM operations').fetchone()[0], 0)
        self.assertEqual(self.adapter.snapshot(), self.base)

    def kill_at(self, stage):
        process = subprocess.Popen([sys.executable, '-c', CHILD, self.fixture.schema, str(self.path), stage],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=20), 'worker did not reach crash boundary')
                line = process.stdout.readline()
            self.assertTrue(line, 'worker exited before crash boundary')
            boundary = json.loads(line)
            self.assertEqual(boundary['stage'], stage)
            # Even when a transaction is in-flight, absence of a visible receipt
            # must remain unresolved and must never cause an implicit retry.
            pending = self.recover()
            expected = 'reconciled' if stage == 'after_commit' else 'unresolved'
            self.assertEqual(pending['runs'][0]['state'], expected)
            process.kill()
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, -9)
            # Wait for the killed connection to disappear before asserting rollback.
            deadline = time.monotonic() + 10
            with self.fixture.database() as db:
                while db.execute('SELECT 1 FROM pg_stat_activity WHERE pid=%s', (boundary['backend'],)).fetchone():
                    self.assertLess(time.monotonic(), deadline, 'killed backend did not disconnect')
                    time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def test_sigkill_before_transaction_preserves_unknown_without_retry(self):
        self.kill_at('before_transaction')
        self.assertEqual(self.adapter.snapshot(), self.base)
        self.assertEqual(self.fixture.receipts(), [])
        for _ in range(2):
            self.assertEqual(self.recover()['runs'][0]['state'], 'unresolved')
        self.assertEqual(self.adapter.snapshot(), self.base)

    def test_sigkill_before_commit_rolls_back_and_preserves_unknown(self):
        self.kill_at('before_commit')
        self.assertEqual(self.adapter.snapshot(), self.base)
        self.assertEqual(self.fixture.receipts(), [])
        for _ in range(2):
            self.assertEqual(self.recover()['runs'][0]['state'], 'unresolved')
        self.assertEqual(self.adapter.snapshot(), self.base)

    def test_sigkill_after_commit_reconciles_exactly_one_effect(self):
        self.kill_at('after_commit')
        before, receipts = self.adapter.snapshot(), self.fixture.receipts()
        self.assertEqual(before.revision, self.base.revision + 1)
        self.assertEqual(len(receipts), 1)
        for _ in range(2):
            recovered = self.recover()
            self.assertEqual(recovered['target_writes'], 0)
            self.assertEqual(recovered['runs'][0]['state'], 'reconciled')
            self.assertEqual(recovered['runs'][0]['operations'][0]['status'], 'applied')
        self.assertEqual(self.adapter.snapshot(), before)
        self.assertEqual(self.fixture.receipts(), receipts)
