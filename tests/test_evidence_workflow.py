import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from foresee import evidence_workflow as workflow, evidence_format as fmt
from foresee.bounded_replay import ReplayBudget, ReplayFailure, ReplayedReport
from foresee.evidence_auth import sign_statement
from foresee.catalog import Catalog, stable_digest
from foresee.compiler import compile_source
from foresee.project import SOURCE
from foresee.runtime import Runtime


class EvidenceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes_raw()
        self.keyid = fmt.key_id(public)
        self.metadata = dict(issuer='test/team', audience='test/audit', issued_at=100, expires_at=200)
        self.options = dict(expected_issuer='test/team', expected_audience='test/audit', now=150, max_lifetime=100)
        self.policy = fmt._encode({'version': 1, 'keys': [dict(keyid=self.keyid,
                                  public_key=fmt._b64(public), issuer='test/team', audiences=['test/audit'],
                                  not_before=50, not_after=300, status='active')]})
        # Eligible format, but intentionally not a reproducible report.
        report = {'report_version': '0.0.2', 'evidence': {'version': 1, 'complete': True}}
        report['report_digest'] = stable_digest(report)
        self.report = fmt._encode(report)
        self.envelope = sign_statement(fmt.prepare_statement(self.report, keyid=self.keyid, **self.metadata), self.key)

    def test_signing_occurs_only_after_replay_and_preserves_bytes(self):
        events = []
        def replay(raw, *, budget):
            events.append('replay')
            self.assertEqual(raw, self.report)
            return ReplayedReport()
        def sign(payload, key):
            events.append('sign')
            return sign_statement(payload, key)
        with patch.object(workflow, 'replay_bounded', side_effect=replay), patch.object(workflow, 'sign_statement', side_effect=sign):
            envelope = workflow.sign_report(self.report, self.key, **self.metadata)
        self.assertEqual(events, ['replay', 'sign'])
        self.assertEqual(fmt.inspect_envelope(envelope).report, self.report)
        self.assertEqual(fmt.inspect_envelope(envelope).keyid, self.keyid)

    def test_signing_fails_closed_for_every_replay_failure(self):
        for code in ('input_limit', 'unsupported_platform', 'limits_unavailable', 'invalid_report',
                     'resource_limit', 'timeout', 'worker_failed', 'worker_protocol'):
            with self.subTest(code=code), patch.object(workflow, 'replay_bounded', side_effect=ReplayFailure(code)), \
                    patch.object(workflow, 'sign_statement') as sign:
                with self.assertRaises(ReplayFailure) as raised:
                    workflow.sign_report(self.report, self.key, **self.metadata)
                self.assertEqual(raised.exception.code, code)
                sign.assert_not_called()

    def test_bad_metadata_or_key_rejected_before_replay(self):
        with patch.object(workflow, 'replay_bounded') as replay:
            for fields in ({'issuer': ''}, {'expires_at': 100}, {'issued_at': True}):
                with self.assertRaises(ValueError):
                    workflow.sign_report(self.report, self.key, **(self.metadata | fields))
            with self.assertRaises(ValueError):
                workflow.sign_report(self.report, b'not a key', **self.metadata)
            replay.assert_not_called()

    def test_authentication_failure_never_starts_replay(self):
        wrong_policy = fmt._encode({'version': 1, 'keys': []})
        corrupted = json.loads(self.envelope)
        corrupted['signatures'][0]['sig'] = fmt._b64(bytes(64))
        with patch.object(workflow, 'replay_bounded') as replay:
            for envelope, policy, options in ((self.envelope, wrong_policy, self.options),
                                              (fmt._encode(corrupted), self.policy, self.options),
                                              (self.envelope, self.policy, self.options | {'now': 200})):
                with self.assertRaises(ValueError):
                    workflow.verify_report(envelope, policy, **options)
            replay.assert_not_called()

    def test_success_has_separate_trust_replay_and_effect_claims(self):
        budget = ReplayBudget(cpu_seconds=2)
        with patch.object(workflow, 'replay_bounded', return_value=ReplayedReport()) as replay:
            result = workflow.verify_report(self.envelope, self.policy, budget=budget, **self.options)
            replay.assert_called_once_with(self.report, budget=budget)
        self.assertTrue(result.authentication.origin_authenticated)
        self.assertIsNone(result.authentication.decision_reproduced)
        self.assertTrue(result.decision_reproduced)
        self.assertTrue(result.requirements_satisfied)
        self.assertIsNone(result.replay_error)
        self.assertFalse(result.target_effect_verified)

    def test_replay_failure_preserves_authentication_but_rejects_combined_requirement(self):
        for code in ('invalid_report', 'timeout', 'resource_limit', 'unsupported_platform', 'worker_failed'):
            with patch.object(workflow, 'replay_bounded', side_effect=ReplayFailure(code)):
                result = workflow.verify_report(self.envelope, self.policy, **self.options)
            self.assertTrue(result.authentication.origin_authenticated)
            self.assertFalse(result.decision_reproduced)
            self.assertFalse(result.requirements_satisfied)
            self.assertEqual(result.replay_error, code)
            self.assertFalse(result.target_effect_verified)

    def test_invalid_budget_and_unexpected_errors_are_not_success(self):
        with self.assertRaises(ValueError):
            workflow.verify_report(self.envelope, self.policy, budget={}, **self.options)
        with patch.object(workflow, 'replay_bounded', side_effect=RuntimeError('unexpected')):
            with self.assertRaises(RuntimeError):
                workflow.verify_report(self.envelope, self.policy, **self.options)
            with self.assertRaises(RuntimeError):
                workflow.sign_report(self.report, self.key, **self.metadata)

    def test_unsupported_platform_has_no_weaker_signing_path(self):
        with patch.object(sys, 'platform', 'darwin'):
            with self.assertRaises(ReplayFailure) as raised:
                workflow.sign_report(self.report, self.key, **self.metadata)
            self.assertEqual(raised.exception.code, 'unsupported_platform')
            result = workflow.verify_report(self.envelope, self.policy, **self.options)
            self.assertFalse(result.requirements_satisfied)
            self.assertEqual(result.replay_error, 'unsupported_platform')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux bounded replay')
    def test_real_signed_report_round_trip_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(Path(directory) / 'catalog.db')
            try:
                catalog.seed()
                report = Runtime(compile_source(SOURCE), catalog).run()
            finally:
                catalog.close()
        raw = json.dumps(report, indent=2).encode() + b'\n'
        envelope = workflow.sign_report(raw, self.key, **self.metadata)
        result = workflow.verify_report(envelope, self.policy, **self.options)
        self.assertTrue(result.requirements_satisfied)
        self.assertEqual(result.authentication.report, raw)
        self.assertFalse(result.target_effect_verified)
        report['outcome']['revision'] = 999
        report.pop('report_digest')
        report['report_digest'] = stable_digest(report)
        changed = fmt._encode(report)
        with self.assertRaises(ReplayFailure):
            workflow.sign_report(changed, self.key, **self.metadata)
        # A malicious signer may bypass our high-level signer. Verification still replays.
        malicious = sign_statement(fmt.prepare_statement(changed, keyid=self.keyid, **self.metadata), self.key)
        result = workflow.verify_report(malicious, self.policy, **self.options)
        self.assertTrue(result.authentication.origin_authenticated)
        self.assertFalse(result.requirements_satisfied)
        self.assertEqual(result.replay_error, 'invalid_report')


if __name__ == '__main__':
    unittest.main()
