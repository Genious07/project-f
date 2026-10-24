import base64
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foresee.catalog import Catalog, stable_digest
from foresee.compiler import compile_source
from foresee import evidence_format as fmt
from foresee.project import SOURCE
from foresee.runtime import Runtime


class EvidenceFormatTests(unittest.TestCase):
    def setUp(self):
        # Structurally suitable but intentionally not semantically replayable.
        # Inspection must never conflate this with verified execution evidence.
        value = {'report_version': '0.0.2', 'recorded_at': 1.5,
                 'evidence': {'version': 1, 'complete': True}}
        value['report_digest'] = stable_digest(value)
        self.report = json.dumps(value, indent=2).encode() + b'\n'
        self.options = dict(issuer='deployment/test', audience='auditor',
                            keyid=fmt.key_id(b'k' * 32), issued_at=100, expires_at=200)
        self.payload = fmt.prepare_statement(self.report, **self.options)
        self.envelope = fmt.encode_envelope(self.payload, b'\0' * 64)

    def test_pae_byte_lengths_and_known_vector(self):
        self.assertEqual(fmt.pae('http://example.com/HelloWorld', b'hello world'),
                         b'DSSEv1 29 http://example.com/HelloWorld 11 hello world')
        self.assertEqual(fmt.pae('é', b'\0 x'), b'DSSEv1 2 \xc3\xa9 3 \0 x')
        self.assertNotEqual(fmt.pae('a', b'bc'), fmt.pae('ab', b'c'))

    def test_inspection_never_claims_authentication(self):
        result = fmt.inspect_envelope(self.envelope)
        self.assertEqual(result.report, self.report)
        self.assertEqual(result.payload, self.payload)
        self.assertEqual(result.signing_bytes, fmt.pae(fmt.PAYLOAD_TYPE, self.payload))
        self.assertFalse(result.signature_checked)
        self.assertFalse(result.origin_authenticated)
        with self.assertRaises(FrozenInstanceError):
            result.origin_authenticated = True

    def test_exact_payload_bytes_are_preserved(self):
        pretty = json.dumps(json.loads(self.payload), indent=2).encode()
        result = fmt.inspect_envelope(fmt.encode_envelope(pretty, b'\0' * 64))
        self.assertEqual(result.payload, pretty)
        self.assertNotEqual(result.signing_bytes, fmt.inspect_envelope(self.envelope).signing_bytes)
        self.assertEqual(result.report, self.report)

    def test_unknown_fields_versions_and_signature_entries_fail(self):
        original = json.loads(self.envelope)
        variants = [dict(original, extra=True), dict(original, payloadType='text/plain'),
                    dict(original, signatures=[]), dict(original, signatures=original['signatures'] * 2),
                    dict(original, signatures=[{'keyid': self.options['keyid'], 'sig': 'AA=='}]),
                    dict(original, signatures=[dict(original['signatures'][0], keyid='sha256:' + '0' * 64)])]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                fmt.inspect_envelope(json.dumps(value).encode())
        for change in ({'version': True}, {'version': 2}, {'extra': 1}, {'issuer': 'bad label'},
                       {'audience': ''}, {'keyid': 'untrusted-label'}, {'issued_at': True},
                       {'expires_at': 100}, {'issued_at': -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                fmt.encode_envelope(json.dumps({**json.loads(self.payload), **change}).encode(), b'\0' * 64)

    def test_base64_is_strict_and_canonical(self):
        for value in ('AA==\n', 'AB==', 'AA', '-_==', 'é'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fmt._unb64(value, 64)
        value = json.loads(self.envelope)
        value['payload'] += '\n'
        with self.assertRaises(ValueError):
            fmt.inspect_envelope(json.dumps(value).encode())

    def test_duplicate_nonfinite_invalid_utf8_and_depth(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'\xff', b'[' * 65 + b']' * 65):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                fmt._json(raw, 1000)
        self.assertEqual(fmt._json(b'{"text":"[\\\"{"}', 1000), {'text': '["{'})

    def test_report_must_match_checksum_and_eligibility_markers(self):
        original = json.loads(self.report)
        for change in ({'complete': False}, {'redacted': True}, {'version': True}):
            value = deepcopy(original)
            value['evidence'].update(change)
            value.pop('report_digest')
            value['report_digest'] = stable_digest(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                fmt.prepare_statement(json.dumps(value).encode(), **self.options)
        value = deepcopy(original)
        value['recorded_at'] = 99
        with self.assertRaises(ValueError):
            fmt.prepare_statement(json.dumps(value).encode(), **self.options)
        statement = json.loads(self.payload)
        statement['report_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            fmt.encode_envelope(json.dumps(statement).encode(), b'\0' * 64)

    def test_limits_and_key_sizes(self):
        with patch.object(fmt, 'MAX_ENVELOPE', len(self.envelope) - 1), self.assertRaises(ValueError):
            fmt.inspect_envelope(self.envelope)
        with patch.object(fmt, 'MAX_REPORT', len(self.report) - 1), self.assertRaises(ValueError):
            fmt.prepare_statement(self.report, **self.options)
        with patch.object(fmt, 'MAX_PAYLOAD', len(self.payload) - 1), self.assertRaises(ValueError):
            fmt.inspect_envelope(self.envelope)
        with self.assertRaises(ValueError):
            fmt.key_id(b'short')
        self.assertEqual(self.options['keyid'], 'sha256:' + hashlib.sha256(b'k' * 32).hexdigest())

    def test_real_runtime_report_is_preserved_without_live_access(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / 'catalog.db')
            try:
                catalog.seed()
                report = Runtime(compile_source(SOURCE), catalog).run()
            finally:
                catalog.close()
        raw = json.dumps(report, indent=2).encode() + b'\n'
        with patch('sqlite3.connect', side_effect=AssertionError('live target')):
            payload = fmt.prepare_statement(raw, **self.options)
            result = fmt.inspect_envelope(fmt.encode_envelope(payload, b'\0' * 64))
        self.assertEqual(result.report, raw)
        self.assertFalse(result.origin_authenticated)
