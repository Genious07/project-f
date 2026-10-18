import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from foresee.catalog import Catalog, Snapshot, stable_digest
from foresee.compiler import compile_source
from foresee.model_provider import BoundedModelProvider, ProcessTransport, ProposalBudget, ProposalFailure
from foresee.project import SOURCE
from foresee.replay import reproduce
from foresee.runtime import Runtime


class Reply:
    def __init__(self, transform=None):
        self.calls = []
        self.transform = transform or (lambda value: value)

    def exchange(self, request, **bounds):
        self.calls.append((json.loads(request), bounds))
        value = {'version': 1, 'request_digest': hashlib.sha256(request).hexdigest(),
                 'plans': [{'id': 'repair', 'patches': [{'id': 'coffee', 'unit_price_cents': 150}]}]}
        value = self.transform(value)
        return value if isinstance(value, bytes) else json.dumps(value).encode()


class ModelProviderTests(unittest.TestCase):
    def setUp(self):
        self.base = Snapshot(0, (), stable_digest({'revision': 0, 'rows': []}))

    def fails(self, code, provider, limit=4, prompt='repair'):
        with self.assertRaises(ProposalFailure) as caught:
            provider.propose(self.base, prompt, limit)
        self.assertEqual(caught.exception.code, code)

    def test_request_contract_and_call_budget(self):
        reply = Reply()
        provider = BoundedModelProvider(reply)
        result = provider.propose(self.base, 'repair', 2)
        self.assertEqual(result[0]['id'], 'repair')
        request, bounds = reply.calls[0]
        self.assertEqual(request, {'version': 1, 'snapshot': {'revision': 0, 'rows': [], 'digest': self.base.digest}, 'prompt': 'repair', 'limit': 2})
        self.assertEqual(bounds, {'timeout_seconds': 10.0, 'max_response_bytes': 262144})
        self.fails('call_limit', provider)
        self.assertEqual(len(reply.calls), 1)

    def test_invalid_budget_values(self):
        for kwargs in ({'max_calls': True}, {'max_candidates': 5}, {'max_patches': 0},
                       {'max_request_bytes': 2_000_001}, {'max_response_bytes': -1},
                       {'timeout_seconds': float('nan')}, {'timeout_seconds': float('inf')},
                       {'timeout_seconds': True}, {'timeout_seconds': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ProposalBudget(**kwargs)

    def test_invalid_or_oversized_request_never_calls_transport(self):
        reply = Reply()
        provider = BoundedModelProvider(reply, ProposalBudget(max_request_bytes=10))
        self.fails('invalid_request', provider, limit=True)
        self.fails('invalid_request', provider, limit=5)
        self.fails('request_limit', provider)
        self.fails('request_limit', provider, prompt='x' * 11)
        self.assertEqual(reply.calls, [])

    def test_response_byte_limit_and_failed_call_consumption(self):
        reply = Reply(lambda value: b'x' * 11)
        provider = BoundedModelProvider(reply, ProposalBudget(max_response_bytes=10))
        self.fails('response_limit', provider)
        self.fails('call_limit', provider)
        self.assertEqual(len(reply.calls), 1)

    def test_strict_json_and_envelope(self):
        transforms = [lambda v: b'\xff', lambda v: b'{', lambda v: b'{"version":1,"version":1}',
                      lambda v: b'{"plans":NaN}', lambda v: b'[' * 2000 + b']' * 2000,
                      lambda v: {**v, 'version': True}, lambda v: {**v, 'request_digest': 'wrong'},
                      lambda v: {**v, 'extra': 1}, lambda v: {**v, 'plans': None}]
        for transform in transforms:
            with self.subTest(transform=transform):
                self.fails('invalid_response', BoundedModelProvider(Reply(transform)))

    def test_candidate_count_schema_duplicates_and_patch_limits(self):
        plans = [
            [{'id': str(i), 'patches': []} for i in range(5)],
            [{'id': 'same', 'patches': []}] * 2,
            [{'id': 'x', 'patches': [{'id': 'coffee', 'unit_price_cents': True}]}],
            [{'id': 'x', 'patches': [{'id': 'coffee', 'unit_price_cents': 2**63}]}],
            [{'id': 'x', 'patches': [{'id': 'coffee', 'title': 'changed'}]}],
            [{'id': 'x', 'patches': [{'id': 'coffee', 'unit_price_cents': 150}] * 2}],
            [{'id': 'x', 'patches': []}, {'id': 'y', 'patches': []}],
        ]
        for value in plans:
            with self.subTest(value=value):
                self.fails('invalid_response', BoundedModelProvider(Reply(lambda v: {**v, 'plans': value})), limit=1 if len(value) == 2 and value[1].get('id') == 'y' else 4)
        value = [{'id': 'x', 'patches': [{'id': str(i), 'unit_price_cents': 150} for i in range(2)]}]
        self.fails('invalid_response', BoundedModelProvider(Reply(lambda v: {**v, 'plans': value}), ProposalBudget(max_patches=1)))

    def test_empty_response_and_exact_response_boundary(self):
        reply = Reply(lambda v: {**v, 'plans': []})
        self.assertEqual(BoundedModelProvider(reply).propose(self.base, 'repair', 4), [])
        request = json.dumps(reply.calls[0][0], sort_keys=True, separators=(',', ':')).encode()
        length = len(reply.exchange(request))
        self.assertEqual(BoundedModelProvider(reply, ProposalBudget(max_response_bytes=length)).propose(self.base, 'repair', 4), [])

    def test_safe_transport_error_and_late_response(self):
        reply = Reply()
        with patch.object(reply, 'exchange', side_effect=RuntimeError('secret-api-key')):
            self.fails('transport_error', BoundedModelProvider(reply))
        with patch.object(reply, 'exchange', side_effect=TimeoutError('secret-url')):
            self.fails('timeout', BoundedModelProvider(reply))
        with patch('foresee.model_provider.time.monotonic', side_effect=[0, 11]):
            self.fails('timeout', BoundedModelProvider(Reply()))

    def test_reentrant_calls_rejected(self):
        reply = Reply()
        provider = BoundedModelProvider(reply)
        original = reply.exchange
        def nested(request, **bounds):
            self.fails('busy', provider)
            return original(request, **bounds)
        reply.exchange = nested
        self.assertTrue(provider.propose(self.base, 'repair', 4))

    @unittest.skipUnless(os.name == 'posix', 'POSIX transport')
    def test_process_success_failure_timeout_and_output_cap(self):
        for script, expected in [('import sys; sys.stdout.buffer.write(b"ok")', b'ok'),
                                 ('import sys; sys.stderr.write("secret"); sys.exit(1)', 'transport_error'),
                                 ('import time; time.sleep(5)', 'timeout'),
                                 ('import sys; sys.stdout.buffer.write(b"x" * 10000)', 'response_limit'),
                                 ('import os,time; os.close(1); time.sleep(5)', 'timeout')]:
            with self.subTest(script=script):
                transport = ProcessTransport([sys.executable, '-c', script])
                if isinstance(expected, bytes):
                    self.assertEqual(transport.exchange(b'input', timeout_seconds=2, max_response_bytes=2), expected)
                else:
                    with self.assertRaises(ProposalFailure) as caught:
                        transport.exchange(b'x' * 262144, timeout_seconds=0.3 if expected == 'timeout' else 2, max_response_bytes=2)
                    self.assertEqual(caught.exception.code, expected)
        with self.assertRaises(ProposalFailure) as caught:
            ProcessTransport(['/nonexistent/foresee-worker']).exchange(b'', timeout_seconds=1, max_response_bytes=10)
        self.assertEqual(caught.exception.code, 'transport_error')

    @unittest.skipUnless(os.name == 'posix', 'POSIX transport')
    def test_process_descendant_cannot_hold_response_pipe_open(self):
        script = 'import os,time; pid=os.fork(); time.sleep(5) if pid == 0 else None'
        started = time.monotonic()
        with self.assertRaises(ProposalFailure) as caught:
            ProcessTransport([sys.executable, '-c', script]).exchange(b'', timeout_seconds=0.3, max_response_bytes=100)
        self.assertEqual(caught.exception.code, 'timeout')
        self.assertLess(time.monotonic() - started, 4)

    def test_runtime_failure_is_incomplete_and_never_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Catalog(Path(temporary) / 'catalog.db')
            try:
                catalog.seed()
                before = catalog.snapshot()
                with patch.object(catalog, 'commit', side_effect=AssertionError('unexpected commit')):
                    report = Runtime(compile_source(SOURCE), catalog, model_provider=BoundedModelProvider(Reply(lambda v: b'bad'))).run()
                self.assertEqual(report['outcome']['provider_code'], 'invalid_response')
                self.assertEqual(report['outcome']['status'], 'provider_error')
                self.assertFalse(report['evidence']['complete'])
                self.assertEqual(catalog.snapshot().digest, before.digest)
                self.assertEqual([e['kind'] for e in report['evidence']['events']], ['snapshot'])
            finally:
                catalog.close()

    @unittest.skipUnless(os.name == 'posix', 'POSIX transport')
    def test_real_process_runtime_and_offline_replay(self):
        worker = Path(__file__).resolve().parents[1] / 'examples/proposal_worker.py'
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Catalog(Path(temporary) / 'catalog.db')
            try:
                catalog.seed()
                provider = BoundedModelProvider(ProcessTransport([sys.executable, str(worker)]))
                report = Runtime(compile_source(SOURCE), catalog, model_provider=provider).run()
                self.assertEqual(report['outcome']['status'], 'applied')
                with patch.object(ProcessTransport, 'exchange', side_effect=AssertionError('live model')), patch('sqlite3.connect', side_effect=AssertionError('live DB')):
                    self.assertTrue(reproduce(report))
            finally:
                catalog.close()
