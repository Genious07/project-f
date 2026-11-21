"""Destructive fault tests against a new, exclusively owned Docker container.

No existing DSN/container is accepted. Nothing is mounted from the host. The
container and its anonymous data volume are removed even when tests fail.
"""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

# Permit direct invocation from the checkout, like other repository check tools.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foresee.compiler import compile_source
from foresee.journal import Journal, reconcile
from foresee.postgres import PostgresCatalog
from foresee.postgres_fixture import PostgresFixture
from foresee.project import SOURCE
from foresee.runtime import Runtime
from postgres_fault_proxy import CommitProxy


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('disposable Docker operation failed: ' + args[0])
    return result.stdout.strip()


class OwnedServer:
    def __init__(self):
        self.name = 'foresee-fault-' + uuid.uuid4().hex
        self.created = False
        try:
            docker('create', '--name', self.name, '--label', 'foresee.disposable=fault-test',
                   '--publish', '127.0.0.1::5432', '-e', 'POSTGRES_PASSWORD=disposable-test-only',
                   '-e', 'POSTGRES_DB=foresee_fault', 'postgres:18')
            self.created = True
            docker('start', self.name)
            self.port = int(docker('port', self.name, '5432/tcp').rsplit(':', 1)[1])
            self.dsn = (f'host=127.0.0.1 port={self.port} dbname=foresee_fault user=postgres '
                        'password=disposable-test-only sslmode=disable gssencmode=disable')
            self.ready()
        except BaseException:
            self.close()
            raise

    def ready(self):
        import psycopg
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(self.dsn, connect_timeout=2) as db:
                    db.execute('SELECT 1')
                return
            except psycopg.Error:
                time.sleep(0.2)
        raise RuntimeError('disposable PostgreSQL did not become ready')

    def crash_and_restart(self):
        if not self.created:
            raise RuntimeError('no owned test container')
        docker('kill', '--signal', 'KILL', self.name)
        docker('start', self.name)
        self.ready()

    def close(self):
        if self.created:
            docker('rm', '--force', '--volumes', self.name)
            self.created = False


class DatabaseFaultTests(unittest.TestCase):
    server = None

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='foresee-fault-journal-')
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'runs.db'
        self.fixture = PostgresFixture(self.server.dsn)
        self.addCleanup(self.fixture.close)
        self.adapter = PostgresCatalog(self.server.dsn, self.fixture.schema, target_name='catalog')
        self.addCleanup(self.adapter.close)
        self.base = self.adapter.snapshot()
        self.targets = {'catalog': {'dsn': self.server.dsn, 'schema': self.fixture.schema}}

    def run_program(self, adapter=None, fault_hook=None):
        with closing(Journal(self.path)) as journal:
            report = Runtime(compile_source(SOURCE), adapter or self.adapter, journal=journal,
                             fault_hook=fault_hook).run()
        self.assertEqual(report['outcome']['status'], 'commit_unresolved')
        self.assertFalse(report['evidence']['complete'])
        self.assertNotIn('disposable-test-only', json.dumps(report))
        return report

    def assert_recovery(self, applied):
        with closing(PostgresCatalog(self.server.dsn, self.fixture.schema)) as fresh:
            snapshot = fresh.snapshot()
            self.assertEqual(snapshot.revision, self.base.revision + int(applied))
            if applied:
                self.assertEqual(snapshot.rows, self.fixture.simulate(self.base, self.fixture.valid_plan(self.base)).rows)
            else:
                self.assertEqual(snapshot, self.base)
            receipts = self.fixture.receipts()
            self.assertEqual(len(receipts), int(applied))
            for _ in range(2):
                recovered = reconcile(self.path, postgres_targets=self.targets)
                self.assertEqual(recovered['target_writes'], 0)
                self.assertEqual(recovered['runs'][0]['state'], 'reconciled' if applied else 'unresolved')
                self.assertEqual(fresh.snapshot(), snapshot)
                self.assertEqual(self.fixture.receipts(), receipts)

    def test_server_kill_before_commit_rolls_back(self):
        def crash(stage):
            if stage == 'before_commit':
                self.server.crash_and_restart()
        self.run_program(fault_hook=crash)
        self.assert_recovery(False)

    def test_server_kill_after_commit_preserves_durable_receipt(self):
        def crash(stage):
            if stage == 'after_commit':
                self.server.crash_and_restart()
                # Force the real broken connection to surface before the runtime
                # records the outcome. Wire acknowledgement loss is tested below.
                self.adapter.connection.execute('SELECT 1')
        self.run_program(fault_hook=crash)
        self.assert_recovery(True)

    def proxied_adapter(self):
        from psycopg.conninfo import make_conninfo
        proxy = CommitProxy(self.server.port)
        self.addCleanup(proxy.close)
        adapter = PostgresCatalog(make_conninfo(self.server.dsn, port=proxy.port), self.fixture.schema,
                                  target_name='catalog')
        self.addCleanup(adapter.close)
        return proxy, adapter

    def test_connection_cut_before_commit_rolls_back(self):
        proxy, adapter = self.proxied_adapter()
        def cut(stage):
            if stage == 'before_commit':
                proxy.cut()
        self.run_program(adapter, cut)
        self.assertIsNone(proxy.error)
        self.assert_recovery(False)

    def test_commit_acknowledgement_dropped_after_durable_receipt(self):
        proxy, adapter = self.proxied_adapter()
        failures = []
        observed = threading.Event()
        def drop_ack():
            try:
                if not proxy.commit_seen.wait(timeout=10):
                    raise AssertionError('proxy did not observe COMMIT')
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if self.fixture.receipts():
                        observed.set()
                        break
                    time.sleep(0.02)
                if not observed.is_set():
                    raise AssertionError('receipt never became durable')
            except Exception as error:
                failures.append(type(error).__name__)
            finally:
                proxy.cut()
        worker = threading.Thread(target=drop_ack, daemon=True)
        worker.start()
        try:
            self.run_program(adapter, lambda stage: proxy.armed.set() if stage == 'before_commit' else None)
        finally:
            worker.join(timeout=15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(observed.is_set())
        self.assertIsNone(proxy.error)
        self.assert_recovery(True)


def main():
    server = OwnedServer()
    try:
        DatabaseFaultTests.server = server
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(DatabaseFaultTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        server.close()


if __name__ == '__main__':
    raise SystemExit(main())
