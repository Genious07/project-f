"""Draft attestation format helpers. No signing or signature verification occurs here."""
import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import json
import math
import re

from .catalog import stable_digest

PAYLOAD_TYPE = 'application/vnd.foresee.report-attestation.v1+json'
MAX_REPORT = 8_000_000
MAX_PAYLOAD = 11_000_000
MAX_ENVELOPE = 15_000_000
MAX_DEPTH = 64
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}\Z')
KEY_ID = re.compile(r'sha256:[0-9a-f]{64}\Z')
FIELDS = {'version', 'issuer', 'audience', 'keyid', 'issued_at', 'expires_at', 'report', 'report_sha256'}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('non-finite JSON number')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('non-finite JSON number')
    return number


def _json(raw, maximum):
    if type(raw) is not bytes or len(raw) > maximum:
        raise ValueError('invalid input type or byte limit exceeded')
    # Check nesting before constructing a potentially deeply recursive object.
    depth, quoted, escaped = 0, False, False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError('JSON nesting limit exceeded')
        elif byte in (93, 125):
            depth -= 1
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_constant, parse_float=_float)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid JSON encoding or depth') from error


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _b64(raw):
    return base64.b64encode(raw).decode('ascii')


def _unb64(value, maximum):
    if type(value) is not str or len(value) > 4 * ((maximum + 2) // 3):
        raise ValueError('invalid base64 length')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('invalid base64') from error
    if len(raw) > maximum or _b64(raw) != value:
        raise ValueError('noncanonical or oversized base64')
    return raw


def key_id(public_key):
    """Fingerprint raw Ed25519 public-key bytes; does not establish key trust."""
    if type(public_key) is not bytes or len(public_key) != 32:
        raise ValueError('public key must be 32 raw bytes')
    return 'sha256:' + hashlib.sha256(public_key).hexdigest()


def pae(payload_type, payload):
    """DSSE v1 pre-authentication encoding; lengths count bytes, not characters."""
    if type(payload_type) is not str or type(payload) is not bytes:
        raise ValueError('PAE requires a string type and byte payload')
    kind = payload_type.encode('utf-8')
    return b'DSSEv1 ' + str(len(kind)).encode() + b' ' + kind + b' ' + str(len(payload)).encode() + b' ' + payload


def _report(raw):
    report = _json(raw, MAX_REPORT)
    if type(report) is not dict or report.get('report_version') != '0.0.2':
        raise ValueError('attestation requires report version 0.0.2')
    evidence = report.get('evidence')
    if (type(evidence) is not dict or type(evidence.get('version')) is not int or evidence['version'] != 1
            or evidence.get('complete') is not True or evidence.get('redacted', False) is not False):
        raise ValueError('attestation requires explicitly complete, unredacted evidence')
    claimed = report.pop('report_digest', None)
    if claimed != stable_digest(report):
        raise ValueError('report checksum mismatch')


def _statement(payload):
    statement = _json(payload, MAX_PAYLOAD)
    if type(statement) is not dict or set(statement) != FIELDS or type(statement['version']) is not int or statement['version'] != 1:
        raise ValueError('invalid attestation statement fields or version')
    for name in ('issuer', 'audience'):
        if type(statement[name]) is not str or not LABEL.fullmatch(statement[name]):
            raise ValueError('invalid issuer or audience label')
    if type(statement['keyid']) is not str or not KEY_ID.fullmatch(statement['keyid']):
        raise ValueError('invalid key fingerprint')
    for name in ('issued_at', 'expires_at'):
        if type(statement[name]) is not int or not 0 <= statement[name] <= 253402300799:
            raise ValueError('timestamps must be integer Unix seconds within year 9999')
    if statement['expires_at'] <= statement['issued_at']:
        raise ValueError('expiration must follow issuance')
    report = _unb64(statement['report'], MAX_REPORT)
    if statement['report_sha256'] != hashlib.sha256(report).hexdigest():
        raise ValueError('report byte digest mismatch')
    _report(report)
    return statement, report


def prepare_statement(report, *, issuer, audience, keyid, issued_at, expires_at):
    """Prepare bytes only. Semantic replay and trust checks are separate gates."""
    if type(report) is not bytes or len(report) > MAX_REPORT:
        raise ValueError('invalid report bytes or size')
    payload = _encode({'version': 1, 'issuer': issuer, 'audience': audience, 'keyid': keyid,
                       'issued_at': issued_at, 'expires_at': expires_at,
                       'report': _b64(report), 'report_sha256': hashlib.sha256(report).hexdigest()})
    _statement(payload)
    return payload


def encode_envelope(payload, signature):
    """Serialize an externally supplied 64-byte signature without verifying it."""
    statement, _ = _statement(payload)
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError('Ed25519 signature must be 64 raw bytes')
    return _encode({'payloadType': PAYLOAD_TYPE, 'payload': _b64(payload),
                    'signatures': [{'keyid': statement['keyid'], 'sig': _b64(signature)}]})


@dataclass(frozen=True)
class EnvelopeInspection:
    payload: bytes
    report: bytes
    signature: bytes
    keyid: str
    issuer: str
    audience: str
    issued_at: int
    expires_at: int
    signature_checked: bool = field(default=False, init=False)
    origin_authenticated: bool = field(default=False, init=False)

    @property
    def signing_bytes(self):
        return pae(PAYLOAD_TYPE, self.payload)


def inspect_envelope(raw):
    """Validate structure/checksums, preserving exact signed bytes. Never authenticates."""
    envelope = _json(raw, MAX_ENVELOPE)
    if (type(envelope) is not dict or set(envelope) != {'payloadType', 'payload', 'signatures'}
            or envelope['payloadType'] != PAYLOAD_TYPE or type(envelope['signatures']) is not list
            or len(envelope['signatures']) != 1):
        raise ValueError('invalid envelope or unsupported signature count/type')
    entry = envelope['signatures'][0]
    if type(entry) is not dict or set(entry) != {'keyid', 'sig'}:
        raise ValueError('invalid signature entry')
    payload = _unb64(envelope['payload'], MAX_PAYLOAD)
    statement, report = _statement(payload)
    if entry['keyid'] != statement['keyid']:
        raise ValueError('outer and signed key IDs differ')
    signature = _unb64(entry['sig'], 64)
    if len(signature) != 64:
        raise ValueError('invalid signature length')
    return EnvelopeInspection(payload, report, signature, statement['keyid'], statement['issuer'],
                              statement['audience'], statement['issued_at'], statement['expires_at'])
