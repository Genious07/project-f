import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foresee import bounded_replay as bounded
from foresee.catalog import Catalog, stable_digest
from foresee.compiler import compile_source
from foresee.model_provider import ProcessTransport
from foresee.project import SOURCE
from foresee.runtime import Runtime



def runtime_report():
    with tempfile.TemporaryDirectory() as directory:
        catalog = Catalog(Path(directory) / 'catalog.db')
        try:
            catalog.seed()
            return Runtime(compile_source(SOURCE), catalog).run()
        finally:
            catalog.close()


class BoundedReplayTests(unittest.TestCase):
    def test_budget_rejects_invalid_values(self):
        for fields in ({'max_report_bytes': True}, {'max_report_bytes': 8_000_001},
                       {'cpu_seconds': 0}, {'cpu_seconds': 31}, {'memory_bytes': 1},
                       {'memory_bytes': 2**31}, {'wall_seconds': True}, {'wall_seconds': float('nan')},
                       {'wall_seconds': 0}, {'wall_seconds': 61}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                bounded.ReplayBudget(**fields)
        with self.assertRaises(ValueError):
            bounded.replay_bounded(b'{}', budget={})

    def test_input_bounds_precede_spawn(self):
        with patch.object(bounded, 'ProcessTransport') as transport:
            for value in ('{}', bytearray(b'{}'), b'abc'):
                with self.assertRaises(bounded.ReplayFailure) as raised:
                    bounded.replay_bounded(value, budget=bounded.ReplayBudget(max_report_bytes=2))
                self.assertEqual(raised.exception.code, 'input_limit')
            transport.assert_not_called()

    def test_unsupported_platform_never_falls_back(self):
        for platform in ('darwin', 'win32'):
            with patch.object(sys, 'platform', platform), patch.object(bounded, 'ProcessTransport') as transport:
                with self.assertRaises(bounded.ReplayFailure) as raised:
                    bounded.replay_bounded(b'{}')
                self.assertEqual(raised.exception.code, 'unsupported_platform')
                transport.assert_not_called()

    def test_fixed_worker_and_no_inherited_environment(self):
        with patch.object(sys, 'platform', 'linux'), patch.object(bounded, 'ProcessTransport') as transport:
            transport.return_value.exchange.return_value = bounded._SUCCESS
            result = bounded.replay_bounded(b'{}')
            argv = transport.call_args.args[0]
            self.assertEqual(argv[:4], [sys.executable, '-I', '-S', '-B'])
            self.assertEqual(Path(argv[4]), Path(bounded.__file__).with_name('replay_worker.py').resolve())
            self.assertEqual(transport.call_args.kwargs, {'env': {}})
            self.assertTrue(result.decision_reproduced)
            self.assertFalse(result.origin_authenticated)
            self.assertFalse(result.target_effect_verified)

    def test_worker_protocol_is_exact_and_fail_closed(self):
        cases = [(b'', 'worker_protocol'), (b'{"decision_reproduced":true}', 'worker_protocol'),
                 (bounded._SUCCESS + b'extra', 'worker_protocol'),
                 (b'{"error":"invalid_report"}', 'invalid_report'),
                 (b'{"error":"resource_limit"}', 'resource_limit'),
                 (b'{"error":"limits_unavailable"}', 'limits_unavailable')]
        with patch.object(sys, 'platform', 'linux'), patch.object(bounded, 'ProcessTransport') as transport:
            for response, code in cases:
                transport.return_value.exchange.return_value = response
                with self.subTest(code=code), self.assertRaises(bounded.ReplayFailure) as raised:
                    bounded.replay_bounded(b'{}')
                self.assertEqual(raised.exception.code, code)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process transport')
    def test_real_worker_timeout_output_limit_and_crash(self):
        factory = ProcessTransport
        cases = [('import time; time.sleep(30)', 'timeout'),
                 ('import sys; sys.stdout.write("x" * 10000)', 'worker_protocol'),
                 ('raise SystemExit(7)', 'worker_failed')]
        for script, code in cases:
            def launch(argv, *, env):
                return factory([sys.executable, '-I', '-S', '-c', script], env=env)
            with patch.object(sys, 'platform', 'linux'), patch.object(bounded, 'ProcessTransport', side_effect=launch):
                with self.assertRaises(bounded.ReplayFailure) as raised:
                    bounded.replay_bounded(b'{}', budget=bounded.ReplayBudget(wall_seconds=0.5))
                self.assertEqual(raised.exception.code, code)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process transport')
    def test_process_environment_does_not_leak_credentials(self):
        with patch.dict(os.environ, {'FORESEE_TEST_SECRET': 'private-test-value'}):
            transport = ProcessTransport([sys.executable, '-I', '-S', '-c',
                                          'import os,sys; sys.stdout.buffer.write(os.environ.get("FORESEE_TEST_SECRET", "absent").encode())'], env={})
            self.assertEqual(transport.exchange(b'', timeout_seconds=3, max_response_bytes=32), b'absent')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux hard resource limits')
    def test_real_report_replays_in_worker(self):
        report = runtime_report()
        result = bounded.replay_bounded(json.dumps(report).encode())
        self.assertTrue(result.decision_reproduced)
        self.assertFalse(result.origin_authenticated)
        self.assertFalse(result.target_effect_verified)
        # Tampering with recomputed checksums must still fail semantic reproduction.
        report['outcome']['revision'] = 500
        report.pop('report_digest')
        report['report_digest'] = stable_digest(report)
        with self.assertRaises(bounded.ReplayFailure) as raised:
            bounded.replay_bounded(json.dumps(report).encode())
        self.assertEqual(raised.exception.code, 'invalid_report')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux hard resource limits')
    def test_malformed_incomplete_legacy_and_deep_reports(self):
        report = runtime_report()
        variants = [b'{}', b'\xff', b'{"x":1,"x":2}', b'[' * 65 + b']' * 65,
                    b'{"report_version":"0.0.1"}', b'{"x":NaN}']
        report['evidence']['complete'] = False
        report.pop('report_digest')
        report['report_digest'] = stable_digest(report)
        variants.append(json.dumps(report).encode())
        for raw in variants:
            with self.subTest(raw=raw[:40]), self.assertRaises(bounded.ReplayFailure) as raised:
                bounded.replay_bounded(raw)
            self.assertEqual(raised.exception.code, 'invalid_report')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux hard resource limits')
    def test_os_memory_and_cpu_limits_are_enforced(self):
        # Invoke the actual limit installer only in disposable children.
        import foresee.replay_worker as worker
        prefix = ('import sys; sys.path.insert(0, ' + repr(str(Path(worker.__file__).resolve().parents[1])) + '); '
                  'from foresee.replay_worker import _install_limits; _install_limits(1, 64 * 1024**2); ')
        memory = subprocess.run([sys.executable, '-I', '-S', '-c', prefix +
                                 '\ntry:\n x=bytearray(256 * 1024**2)\nexcept MemoryError:\n print("bounded")\n'],
                                capture_output=True, timeout=5)
        self.assertEqual(memory.returncode, 0)
        self.assertEqual(memory.stdout.strip(), b'bounded')
        cpu = subprocess.run([sys.executable, '-I', '-S', '-c', prefix + '\nwhile True: pass\n'],
                             capture_output=True, timeout=5)
        self.assertLess(cpu.returncode, 0)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux hard resource limits')
    def test_worker_installs_limits_before_loading_report(self):
        import foresee.replay_worker as worker
        from io import BytesIO
        from types import SimpleNamespace
        output = BytesIO()
        with patch.object(sys, 'argv', ['worker', '8000000', '3', str(512 * 1024**2)]), \
                patch.object(worker, '_install_limits', side_effect=OSError('unavailable')), \
                patch.object(sys, 'stdin', SimpleNamespace(buffer=None)), \
                patch.object(sys, 'stdout', SimpleNamespace(buffer=output)):
            worker.main()
        self.assertEqual(output.getvalue(), b'{"error":"limits_unavailable"}')


if __name__ == '__main__':
    unittest.main()
