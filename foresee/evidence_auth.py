"""Experimental signature/trust primitives, separate from semantic report replay.

No key files, network discovery, clock inference, or target access occur here.
"""
from dataclasses import dataclass, field

from .evidence_format import (LABEL, PAYLOAD_TYPE, _json, _statement, _unb64,
                              encode_envelope, inspect_envelope, key_id, pae)

MAX_POLICY = 65_536
MAX_KEYS = 64
MAX_AUDIENCES = 32
MAX_TIME = 253402300799
KEY_FIELDS = {'keyid', 'public_key', 'issuer', 'audiences', 'not_before', 'not_after', 'status'}


def _backend():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as error:
        raise RuntimeError('install project-f-bootstrap[evidence] to use signatures') from error
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


def _label(value):
    if type(value) is not str or not LABEL.fullmatch(value):
        raise ValueError('invalid identity label')


def _time(value):
    if type(value) is not int or not 0 <= value <= MAX_TIME:
        raise ValueError('invalid integer timestamp')


@dataclass(frozen=True)
class _TrustedKey:
    keyid: str
    public_key: bytes
    issuer: str
    audiences: tuple[str, ...]
    not_before: int
    not_after: int
    status: str


def _policy(raw):
    policy = _json(raw, MAX_POLICY)
    if (type(policy) is not dict or set(policy) != {'version', 'keys'}
            or type(policy['version']) is not int or policy['version'] != 1
            or type(policy['keys']) is not list or len(policy['keys']) > MAX_KEYS):
        raise ValueError('invalid trust policy')
    keys = {}
    for entry in policy['keys']:
        if type(entry) is not dict or set(entry) != KEY_FIELDS:
            raise ValueError('invalid trusted key fields')
        public = _unb64(entry['public_key'], 32)
        fingerprint = key_id(public)
        if entry['keyid'] != fingerprint or fingerprint in keys:
            raise ValueError('mismatched or duplicate trusted key fingerprint')
        _label(entry['issuer'])
        audiences = entry['audiences']
        if type(audiences) is not list or not 1 <= len(audiences) <= MAX_AUDIENCES:
            raise ValueError('invalid trusted audiences')
        for audience in audiences:
            _label(audience)
        if len(set(audiences)) != len(audiences):
            raise ValueError('duplicate trusted audience')
        _time(entry['not_before'])
        _time(entry['not_after'])
        if entry['not_before'] >= entry['not_after'] or entry['status'] not in ('active', 'revoked'):
            raise ValueError('invalid trusted key validity or status')
        keys[fingerprint] = _TrustedKey(fingerprint, public, entry['issuer'], tuple(audiences),
                                        entry['not_before'], entry['not_after'], entry['status'])
    return keys


def sign_statement(payload, private_key):
    """Low-level endorsement only; does NOT replay a report or validate trust policy.

    Accepts a caller-owned cryptography Ed25519 key object. Use
    evidence_workflow.sign_report to require bounded replay before signing.
    """
    statement, _ = _statement(payload)
    private_type, _, _ = _backend()
    if not isinstance(private_key, private_type):
        raise ValueError('an Ed25519 private key object is required')
    public = private_key.public_key().public_bytes_raw()
    if statement['keyid'] != key_id(public):
        raise ValueError('signing key does not match statement fingerprint')
    return encode_envelope(payload, private_key.sign(pae(PAYLOAD_TYPE, payload)))


@dataclass(frozen=True)
class AuthenticatedEnvelope:
    report: bytes = field(repr=False)
    keyid: str
    issuer: str
    audience: str
    issued_at: int
    expires_at: int
    verified_at: int
    format_valid: bool = field(default=True, init=False)
    signature_valid: bool = field(default=True, init=False)
    signer_trusted: bool = field(default=True, init=False)
    checksum_valid: bool = field(default=True, init=False)
    origin_authenticated: bool = field(default=True, init=False)
    # None means not attempted, rather than a failed semantic replay.
    decision_reproduced: None = field(default=None, init=False)
    target_effect_verified: bool = field(default=False, init=False)


def authenticate_envelope(raw, policy, *, expected_issuer, expected_audience, now, max_lifetime):
    """Authenticate exact bytes against caller-provided policy and clock.

    Raises ValueError on rejection, never returning a partial success. Origin
    means trusted-key endorsement only. No semantic replay or effect check runs.
    Policy must be bounded JSON bytes, never an artifact-controlled key source.
    """
    _label(expected_issuer)
    _label(expected_audience)
    _time(now)
    if type(max_lifetime) is not int or not 1 <= max_lifetime <= MAX_TIME:
        raise ValueError('max_lifetime must be a positive bounded integer')
    keys = _policy(policy)
    envelope = inspect_envelope(raw)
    key = keys.get(envelope.keyid)
    if key is None or key.status != 'active':
        raise ValueError('unknown or revoked signing key')
    if envelope.issuer != expected_issuer or key.issuer != expected_issuer:
        raise ValueError('issuer not authorized')
    if envelope.audience != expected_audience or expected_audience not in key.audiences:
        raise ValueError('audience not authorized')
    if not key.not_before <= envelope.issued_at < envelope.expires_at <= key.not_after:
        raise ValueError('attestation outside key validity')
    if not key.not_before <= now < key.not_after or not envelope.issued_at <= now < envelope.expires_at:
        raise ValueError('attestation or key not currently valid')
    if envelope.expires_at - envelope.issued_at > max_lifetime:
        raise ValueError('attestation lifetime exceeds policy')
    _, public_type, invalid_signature = _backend()
    try:
        public_type.from_public_bytes(key.public_key).verify(envelope.signature, envelope.signing_bytes)
    except invalid_signature as error:
        raise ValueError('invalid attestation signature') from error
    return AuthenticatedEnvelope(envelope.report, envelope.keyid, envelope.issuer, envelope.audience,
                                 envelope.issued_at, envelope.expires_at, now)
