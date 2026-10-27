"""Compose signature/trust checks with resource-bounded decision replay."""
from dataclasses import dataclass, field

from .bounded_replay import ReplayBudget, ReplayFailure, replay_bounded
from .evidence_auth import AuthenticatedEnvelope, _backend, authenticate_envelope, sign_statement
from .evidence_format import key_id, prepare_statement


def _budget(value):
    value = ReplayBudget() if value is None else value
    if type(value) is not ReplayBudget:
        raise ValueError('budget must be a ReplayBudget')
    return value


def sign_report(report, private_key, *, issuer, audience, issued_at, expires_at, budget=None):
    """Return a signed envelope only after successful bounded replay.

    Key custody remains the caller's responsibility. No trust policy is inferred
    for the signer. Only report bytes and budgets enter the replay subprocess.
    """
    budget = _budget(budget)
    private_type, _, _ = _backend()
    if not isinstance(private_key, private_type):
        raise ValueError('an Ed25519 private key object is required')
    payload = prepare_statement(report, issuer=issuer, audience=audience,
                                keyid=key_id(private_key.public_key().public_bytes_raw()),
                                issued_at=issued_at, expires_at=expires_at)
    replay_bounded(report, budget=budget)
    return sign_statement(payload, private_key)


@dataclass(frozen=True)
class EvidenceVerification:
    authentication: AuthenticatedEnvelope
    decision_reproduced: bool
    replay_error: str | None
    target_effect_verified: bool = field(default=False, init=False)

    @property
    def requirements_satisfied(self):
        """Both trusted origin and bounded reproduction succeeded, not real effects."""
        return self.authentication.origin_authenticated and self.decision_reproduced


def verify_report(envelope, policy, *, expected_issuer, expected_audience, now, max_lifetime, budget=None):
    """Authenticate first, then replay the exact authenticated report bytes.

    Authentication/configuration failures raise, without starting replay. Replay
    failure returns explicit separate claims; callers requiring both MUST check
    requirements_satisfied. No timeout or unsupported-platform fallback occurs.
    The supplied verifier time is the evaluation instant, not a trusted timestamp.
    """
    budget = _budget(budget)
    authentication = authenticate_envelope(envelope, policy, expected_issuer=expected_issuer,
                                           expected_audience=expected_audience, now=now,
                                           max_lifetime=max_lifetime)
    try:
        replay_bounded(authentication.report, budget=budget)
    except ReplayFailure as error:
        return EvidenceVerification(authentication, False, error.code)
    return EvidenceVerification(authentication, True, None)
