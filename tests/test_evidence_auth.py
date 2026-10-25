"""The RFC seed below is PUBLIC TEST DATA, never a deployment credential."""
import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from foresee.catalog import Catalog, stable_digest
from foresee.compiler import compile_source
from foresee.project import SOURCE
from foresee.runtime import Runtime
from foresee import evidence_auth as auth, evidence_format as fmt
from foresee.replay import reproduce


class EvidenceAuthTests(unittest.TestCase):
    def setUp(self):
        # RFC 8032 section 7.1 test 1, public test material only.
        self.key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
            '9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60'))
        self.public = self.key.public_key().public_bytes_raw()
        self.keyid = fmt.key_id(self.public)
        report = {'report_version': '0.0.2', 'evidence': {'version': 1, 'complete': True}}
        report['report_digest'] = stable_digest(report)
        self.report = fmt._encode(report)
        self.metadata = dict(issuer='example/team', audience='production/audit', keyid=self.keyid,
                             issued_at=100, expires_at=200)
        self.payload = fmt.prepare_statement(self.report, **self.metadata)
        self.envelope = auth.sign_statement(self.payload, self.key)
        self.entry = dict(keyid=self.keyid, public_key=fmt._b64(self.public), issuer='example/team',
                          audiences=['production/audit'], not_before=50, not_after=300, status='active')
        self.policy = dict(version=1, keys=[self.entry])
        self.options = dict(expected_issuer='example/team', expected_audience='production/audit',
                            now=150, max_lifetime=100)

    def verify(self, envelope=None, policy=None, **options):
        return auth.authenticate_envelope(self.envelope if envelope is None else envelope,
                                          fmt._encode(self.policy if policy is None else policy),
                                          **(self.options | options))

    def test_rfc8032_vector(self):
        self.assertEqual(self.public.hex(), 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
        signature = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f'
                                  'b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
        self.assertEqual(self.key.sign(b''), signature)
        self.key.public_key().verify(signature, b'')

    def test_authentication_is_not_replay_or_effect_verification(self):
        result = self.verify()
        self.assertEqual(result.report, self.report)
        for name in ('format_valid', 'signature_valid', 'signer_trusted', 'checksum_valid', 'origin_authenticated'):
            self.assertIs(getattr(result, name), True)
        self.assertIsNone(result.decision_reproduced)
        self.assertFalse(result.target_effect_verified)
        self.assertFalse(fmt.inspect_envelope(self.envelope).origin_authenticated)
        with self.assertRaises(ValueError):
            reproduce(json.loads(result.report))
        with self.assertRaises(FrozenInstanceError):
            result.issuer = 'attacker'

    def test_wrong_key_and_corrupt_signature(self):
        other = Ed25519PrivateKey.generate()
        for signature in (other.sign(fmt.pae(fmt.PAYLOAD_TYPE, self.payload)), bytes(64)):
            with self.assertRaisesRegex(ValueError, 'invalid attestation signature'):
                self.verify(fmt.encode_envelope(self.payload, signature))
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            auth.sign_statement(self.payload, other)
        with self.assertRaises(ValueError):
            auth.sign_statement(self.payload, b'not a key object')

    def test_exact_bytes_and_protocol_binding(self):
        pretty = json.dumps(json.loads(self.payload), indent=2).encode()
        self.verify(auth.sign_statement(pretty, self.key))
        signature = fmt.inspect_envelope(self.envelope).signature
        for payload, sig in ((pretty, signature), (self.payload, self.key.sign(self.payload)),
                             (self.payload, self.key.sign(fmt.pae('text/plain', self.payload)))):
            with self.assertRaisesRegex(ValueError, 'invalid attestation signature'):
                self.verify(fmt.encode_envelope(payload, sig))

    def test_recomputed_checksums_do_not_allow_report_tampering(self):
        changed = json.loads(self.report)
        changed.pop('report_digest')
        changed['fabricated'] = True
        changed['report_digest'] = stable_digest(changed)
        payload = fmt.prepare_statement(fmt._encode(changed), **self.metadata)
        with self.assertRaisesRegex(ValueError, 'invalid attestation signature'):
            self.verify(fmt.encode_envelope(payload, fmt.inspect_envelope(self.envelope).signature))

    def test_signed_metadata_cannot_be_changed(self):
        # All variants still satisfy policy, so only signature verification rejects them.
        self.entry['audiences'].append('another/audit')
        for change, options in (({'issued_at': 101}, {}), ({'expires_at': 199}, {}),
                                ({'audience': 'another/audit'}, {'expected_audience': 'another/audit'})):
            payload = fmt.prepare_statement(self.report, **(self.metadata | change))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid attestation signature'):
                self.verify(fmt.encode_envelope(payload, fmt.inspect_envelope(self.envelope).signature), **options)

    def test_unknown_revoked_and_replaced_keys(self):
        self.verify(policy={'version': 1, 'keys': [self.entry]})
        variants = [{'version': 1, 'keys': []}, {'version': 1, 'keys': [self.entry | {'status': 'revoked'}]}]
        other = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        variants.append({'version': 1, 'keys': [self.entry | {'keyid': fmt.key_id(other), 'public_key': fmt._b64(other)}]})
        for policy in variants:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.verify(policy=policy)

    def test_issuer_and_audience_restrictions(self):
        for option in ({'expected_issuer': 'another/team'}, {'expected_audience': 'another/audit'}):
            with self.assertRaises(ValueError):
                self.verify(**option)
        for change in ({'issuer': 'another/team'}, {'audiences': ['another/audit']}):
            with self.assertRaises(ValueError):
                self.verify(policy={'version': 1, 'keys': [self.entry | change]})

    def test_clock_and_lifetime_boundaries(self):
        self.verify(now=100)
        self.verify(now=199)
        for now in (49, 50, 99, 200, 299, 300):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.verify(now=now)
        with self.assertRaises(ValueError):
            self.verify(max_lifetime=99)
        self.verify(policy={'version': 1, 'keys': [self.entry | {'not_before': 100, 'not_after': 200}]})
        for change in ({'not_before': 101}, {'not_after': 199}):
            with self.assertRaises(ValueError):
                self.verify(policy={'version': 1, 'keys': [self.entry | change]})

    def test_policy_schema_and_bounds(self):
        changes = [{'extra': 1}, {'public_key': 'AA=='}, {'keyid': 'sha256:' + '0' * 64},
                   {'audiences': []}, {'audiences': ['a'] * 2}, {'audiences': ['a'] * 33},
                   {'audiences': [True]}, {'issuer': 'bad label'}, {'not_before': True},
                   {'not_after': 50}, {'not_after': 253402300800}, {'status': 'disabled'}]
        variants = [self.policy | {'version': True}, self.policy | {'extra': 1},
                    self.policy | {'keys': [self.entry] * 2}, self.policy | {'keys': [self.entry] * 65}]
        variants += [{'version': 1, 'keys': [self.entry | change]} for change in changes]
        for policy in variants:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.verify(policy=policy)
        for raw in (b'{"version":1,"version":1,"keys":[]}', b' ' * (auth.MAX_POLICY + 1),
                    b'{"version":1,"keys":NaN}', b'\xff'):
            with self.assertRaises(ValueError):
                auth.authenticate_envelope(self.envelope, raw, **self.options)

    def test_explicit_caller_inputs(self):
        for change in ({'now': True}, {'now': -1}, {'max_lifetime': True}, {'max_lifetime': 0},
                       {'max_lifetime': 1.5}, {'expected_issuer': ''}, {'expected_audience': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(**change)
        with self.assertRaises(TypeError):
            auth.authenticate_envelope(self.envelope, fmt._encode(self.policy))

    def test_rotation_and_revocation(self):
        other = Ed25519PrivateKey.generate()
        public = other.public_key().public_bytes_raw()
        entry = self.entry | {'keyid': fmt.key_id(public), 'public_key': fmt._b64(public)}
        policy = deepcopy(self.policy)
        policy['keys'].append(entry)
        envelope = auth.sign_statement(fmt.prepare_statement(self.report, **(self.metadata | {'keyid': entry['keyid']})), other)
        self.verify(policy=policy)
        self.verify(envelope, policy)
        policy['keys'][0]['status'] = 'revoked'
        self.verify(envelope, policy)
        with self.assertRaises(ValueError):
            self.verify(policy=policy)

    def test_real_report_authenticates_offline_without_claiming_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / 'catalog.db')
            try:
                catalog.seed()
                report = Runtime(compile_source(SOURCE), catalog).run()
            finally:
                catalog.close()
        raw = json.dumps(report, indent=2).encode() + b'\n'
        with patch('sqlite3.connect', side_effect=AssertionError('live target')), \
                patch('socket.socket', side_effect=AssertionError('network access')), \
                patch('foresee.replay.reproduce', side_effect=AssertionError('implicit replay')):
            envelope = auth.sign_statement(fmt.prepare_statement(raw, **self.metadata), self.key)
            result = self.verify(envelope)
        self.assertEqual(result.report, raw)
        self.assertTrue(result.origin_authenticated)
        self.assertIsNone(result.decision_reproduced)
        self.assertFalse(result.target_effect_verified)

    def test_missing_backend_fails_explicitly(self):
        real_import = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name.startswith('cryptography'):
                raise ImportError('test missing optional extra')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=blocked):
            with self.assertRaisesRegex(RuntimeError, 'evidence'):
                self.verify()
            with self.assertRaisesRegex(RuntimeError, 'evidence'):
                auth.sign_statement(self.payload, self.key)


if __name__ == '__main__':
    unittest.main()
