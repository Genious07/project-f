import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error

from foresee.catalog import Catalog, Snapshot
from foresee.compiler import compile_source
from foresee.model_provider import BoundedModelProvider, ProposalBudget, ProposalFailure
from foresee.openai_provider import OpenAIConfig, OpenAITransport, openai_provider
from foresee import openai_worker as worker
from foresee.project import SOURCE
from foresee.replay import reproduce
from foresee.runtime import Runtime


def config(**changes):
    # Synthetic test rates, not a current price quote.
    values = dict(model='test-model', max_input_tokens=1000, max_output_tokens=100,
                  input_price_micro_usd_per_million=1_000_000,
                  output_price_micro_usd_per_million=2_000_000, max_reserved_micro_usd=2400)
    return OpenAIConfig(**{**values, **changes})


def response():
    return {'status': 'completed', 'usage': {'input_tokens': 50, 'output_tokens': 30},
            'output': [{'type': 'reasoning'}, {'type': 'message', 'role': 'assistant',
                       'content': [{'type': 'output_text', 'text': json.dumps({'plans': [
                           {'id': 'repair', 'patches': [{'id': 'coffee', 'unit_price_cents': 150}]}]})}]}]}


COUNT = {'object': 'response.input_tokens', 'input_tokens': 50}


class OpenAIProviderTests(unittest.TestCase):
    def failure(self, code, function):
        with self.assertRaises(ProposalFailure) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn('secret', str(caught.exception))

    def invoke(self):
        return worker.propose(config(), b'{"limit":4}', 'test-key', time.monotonic() + 10)

    def test_explicit_configuration_and_integer_rounding(self):
        self.assertEqual(config().reservation_per_call, 1200)
        self.assertEqual(config(input_price_micro_usd_per_million=1, output_price_micro_usd_per_million=1).reservation_per_call, 1)
        for changes in ({'model': ''}, {'model': 'bad\nmodel'}, {'max_input_tokens': True},
                        {'max_output_tokens': 0}, {'max_reserved_micro_usd': -1},
                        {'input_price_micro_usd_per_million': 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config(**changes)

    def test_count_and_generation_use_same_input_schema_and_model(self):
        with patch.object(worker, 'post', side_effect=[COUNT, response()]) as post:
            result = self.invoke()
        count_call, generate_call = post.call_args_list
        self.assertEqual(count_call.args[0], '/responses/input_tokens')
        self.assertEqual(generate_call.args[0], '/responses')
        common, generated = count_call.args[1], generate_call.args[1]
        self.assertTrue(all(generated[k] == v for k, v in common.items()))
        self.assertEqual(common['model'], 'test-model')
        self.assertTrue(common['text']['format']['strict'])
        self.assertEqual(generated['max_output_tokens'], 100)
        self.assertFalse(generated['store'])
        self.assertFalse(generated['stream'])
        self.assertNotIn('tools', generated)
        self.assertEqual(result['plans'][0]['id'], 'repair')

    def test_preflight_rejects_before_generation(self):
        for count, code in [({**COUNT, 'input_tokens': 1001}, 'input_token_limit'),
                            ({**COUNT, 'input_tokens': True}, 'invalid_response'),
                            ({'input_tokens': 1}, 'invalid_response')]:
            with self.subTest(count=count), patch.object(worker, 'post', return_value=count) as post:
                self.failure(code, self.invoke)
                self.assertEqual(post.call_count, 1)

    def test_missing_credentials_never_sends(self):
        with patch.object(worker, 'post', side_effect=AssertionError('network')):
            for key in (None, '', ' ', 'secret\nheader'):
                self.failure('missing_credentials', lambda: worker.propose(config(), b'{}', key, 1))

    def test_refusal_incomplete_usage_and_invalid_outputs(self):
        cases = []
        r = response(); r['status'] = 'incomplete'; cases.append((r, 'incomplete_response'))
        r = response(); r['usage']['output_tokens'] = 101; cases.append((r, 'usage_limit'))
        r = response(); r['usage']['input_tokens'] = 1001; cases.append((r, 'usage_limit'))
        r = response(); del r['usage']; cases.append((r, 'invalid_response'))
        r = response(); r['usage']['input_tokens'] = True; cases.append((r, 'invalid_response'))
        r = response(); r['output'][1]['content'] = [{'type': 'refusal', 'refusal': 'secret'}]; cases.append((r, 'model_refusal'))
        r = response(); r['output'] = [{'type': 'function_call'}]; cases.append((r, 'invalid_response'))
        r = response(); r['output'][1]['content'][0]['text'] = '{"plans":[],"plans":[]}'; cases.append((r, 'invalid_response'))
        r = response(); r['output'][1]['content'] *= 2; cases.append((r, 'invalid_response'))
        for value, code in cases:
            with self.subTest(code=code), patch.object(worker, 'post', side_effect=[COUNT, value]):
                self.failure(code, self.invoke)

    def test_cost_reserved_before_worker_and_never_refunded(self):
        transport = OpenAITransport(config())
        with patch.object(transport._worker, 'exchange', side_effect=ProposalFailure('timeout')) as exchange:
            for expected in ('timeout', 'timeout', 'spend_limit'):
                self.failure(expected, lambda: transport.exchange(b'{}', timeout_seconds=1, max_response_bytes=1024))
            self.assertEqual(exchange.call_count, 2)
            self.assertEqual(transport.reserved_micro_usd, 2400)
            self.assertNotIn('api_key', exchange.call_args.args[0].decode().lower())

    def test_insufficient_budget_does_not_launch_worker(self):
        transport = OpenAITransport(config(max_reserved_micro_usd=1199))
        with patch.object(transport._worker, 'exchange', side_effect=AssertionError('launched')):
            self.failure('spend_limit', lambda: transport.exchange(b'{}', timeout_seconds=1, max_response_bytes=1000))
        self.assertEqual(transport.reserved_micro_usd, 0)

    def test_worker_errors_are_allowlisted_and_output_is_bounded(self):
        for raw, expected in [(b'{"error":"rate_limit"}', 'rate_limit'),
                              (b'{"error":"secret"}', 'invalid_response'),
                              (b'{"error":[]}', 'invalid_response'),
                              (b'not json', 'invalid_response'),
                              (b'{"proposal":{"plans":[]}}', 'response_limit')]:
            with self.subTest(raw=raw):
                transport = OpenAITransport(config())
                with patch.object(transport._worker, 'exchange', return_value=raw):
                    self.failure(expected, lambda: transport.exchange(b'{}', timeout_seconds=1, max_response_bytes=1))

    def test_http_fixed_endpoint_bounds_and_redirect_rejection(self):
        reply = Mock()
        reply.__enter__ = Mock(return_value=reply)
        reply.__exit__ = Mock(return_value=False)
        reply.status = 200
        reply.headers = {}
        reply.read.return_value = b'{"ok":true}'
        opener = Mock(); opener.open.return_value = reply
        with patch.object(worker.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(worker.post('/responses', {}, 'test-key', time.monotonic() + 5), {'ok': True})
            self.assertEqual(opener.open.call_args.args[0].full_url, 'https://api.openai.com/v1/responses')
            reply.read.assert_called_with(worker.HTTP_LIMIT + 1)
            reply.read.return_value = b'x' * (worker.HTTP_LIMIT + 1)
            self.failure('response_limit', lambda: worker.post('/responses', {}, 'test-key', time.monotonic() + 5))
        self.failure('http_error', lambda: worker.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))
        self.failure('http_error', lambda: worker.post('/other', {}, 'key', 1))
        self.failure('timeout', lambda: worker.post('/responses', {}, 'key', 0))

    def test_http_status_errors_are_sanitized_without_retry(self):
        for status, expected in [(401, 'authentication_error'), (403, 'authentication_error'),
                                 (429, 'rate_limit'), (500, 'http_error')]:
            error = urllib.error.HTTPError('https://secret', status, 'secret', {}, io.BytesIO(b'secret'))
            opener = Mock(); opener.open.side_effect = error
            with self.subTest(status=status), patch.object(worker.urllib.request, 'build_opener', return_value=opener):
                self.failure(expected, lambda: worker.post('/responses', {}, 'test-key', time.monotonic() + 5))
                self.assertEqual(opener.open.call_count, 1)

    def test_no_http_import_or_constructor_side_effects(self):
        with patch.object(worker.urllib.request, 'build_opener', side_effect=AssertionError('network')):
            provider = openai_provider(config())
        self.assertIsInstance(provider, BoundedModelProvider)

    @unittest.skipUnless(os.name == 'posix', 'POSIX worker')
    def test_real_worker_missing_key_is_safe(self):
        # Explicitly remove the key from the child environment; never use a live key.
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            provider = openai_provider(config())
            self.failure('missing_credentials', lambda: provider.propose(Snapshot(0, (), 'test'), 'repair', 4))

    def test_runtime_full_validation_and_replay_with_mock_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Catalog(Path(temporary) / 'catalog.db')
            try:
                catalog.seed()
                provider = openai_provider(config(), ProposalBudget())
                def fake_worker(job, **kwargs):
                    job = json.loads(job)
                    proposal = worker.propose(OpenAIConfig(**job['config']), job['request'].encode(), 'test-key', time.monotonic() + 5)
                    return worker.encode({'proposal': proposal})
                with patch.object(provider.transport._worker, 'exchange', side_effect=fake_worker), patch.object(worker, 'post', side_effect=[COUNT, response()]):
                    report = Runtime(compile_source(SOURCE), catalog, model_provider=provider).run()
                self.assertEqual(report['outcome']['status'], 'applied')
                with patch.object(OpenAITransport, 'exchange', side_effect=AssertionError('live model')), patch('sqlite3.connect', side_effect=AssertionError('live DB')):
                    self.assertTrue(reproduce(report))
                invalid = response()
                invalid['output'][1]['content'][0]['text'] = json.dumps({'plans': [{'id': 'bad', 'patches': [{'id': 'coffee', 'title': 'changed'}]}]})
                provider = openai_provider(config())
                with patch.object(provider.transport._worker, 'exchange', side_effect=fake_worker), patch.object(worker, 'post', side_effect=[COUNT, invalid]), patch.object(catalog, 'commit', side_effect=AssertionError('commit')):
                    report = Runtime(compile_source(SOURCE), catalog, model_provider=provider).run()
                self.assertEqual(report['outcome']['provider_code'], 'invalid_response')
            finally:
                catalog.close()
