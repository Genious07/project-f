# Authenticated evidence: draft v1 design

Design and format scaffolding implemented on 24 October 2026; signature and trust primitives added on 25 October. **This remains an experimental protocol profile, not a complete report-signing workflow.** Ed25519 statement signing and trusted-key authentication are implemented. Linux resource-bounded semantic replay was added on 26 October. Key-file custody, composed signing/verification workflows, and signing CLI commands are still pending. Existing unsigned replay continues to report `origin_authenticated: false`.

## Philosophy and claims

Checksums answer whether bytes match a supplied digest. Replay answers whether recorded inputs reproduce the program's decision. Signatures can establish that a holder of a trusted key endorsed specific bytes. These are independent claims and must have separate results.

A trusted signature will not prove that a database snapshot was genuine, a model generated a proposal, a commit occurred, the signer ran the program, or a timestamp came from a trusted clock. A dishonest or compromised signer can endorse fabricated but reproducible reports. Effect verification still requires adapter receipts and appropriate independent reconciliation. A report signature is never an execution capability.

## Threat model

| Actor or failure | Intended response | Remaining limitation |
| --- | --- | --- |
| Storage or transport attacker modifies a report | Signature over exact payload/report bytes must fail | An attacker may delete evidence entirely |
| Attacker recomputes all ordinary checksums | Trusted signature still required | Checksum-only artifacts remain unauthenticated |
| Attacker replaces the public key along with the report | Resolve keys only from verifier-controlled policy | Bootstrap trust must be established outside the artifact |
| Attacker changes issuer, audience, key ID, or expiry | Those claims are inside the signed payload | Claims have meaning only under local trust policy |
| Attacker supplies a valid signature for another protocol | Bind payload type using DSSE framing | Only the exact Foresee payload type is accepted |
| Attacker replays a valid old attestation | Check expiry, audience, and current key policy | Audit verification does not consume an attestation or prevent duplicate ingestion |
| Signing key is stolen | Revoke the key; reject it regardless of claimed issue time | Already accepted evidence cannot establish pre-compromise timing without external timestamps |
| Signer intentionally lies | Report replay can catch inconsistent decisions | Consistent fabricated input/effect stories can still pass |
| Hostile oversized or ambiguous JSON | Byte/depth bounds, duplicate-key rejection, strict base64 | Replay itself needs an isolated execution budget before exposed verification is shipped |

Trusted components are the verifier, its cryptographic library, its local policy and clock, and the operator who provisions keys. The report, envelope, signer-supplied metadata, and key ID are untrusted input. This profile does not provide confidentiality, transparency-log inclusion, trusted timestamps, or hardware-backed execution attestation.

## Proposed envelope

Use the [DSSE protocol](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md) to bind a payload type and its exact bytes before signing. The profile accepts one signature and the exact type `application/vnd.foresee.report-attestation.v1+json`. DSSE supports broader configurations; those are outside this initial profile.

```json
{
  "payloadType": "application/vnd.foresee.report-attestation.v1+json",
  "payload": "BASE64_OF_EXACT_STATEMENT_BYTES",
  "signatures": [{"keyid": "sha256:PUBLIC_KEY_FINGERPRINT", "sig": "BASE64_SIGNATURE"}]
}
```

The decoded statement contains exactly:

| Field | Meaning |
| --- | --- |
| `version` | Integer 1; booleans are rejected |
| `issuer` | Operator-defined signer identity label |
| `audience` | Intended verifier/deployment label |
| `keyid` | `sha256:` followed by lowercase SHA-256 of the 32 raw public-key bytes |
| `issued_at` | Claimed integer Unix seconds, not a trusted timestamp |
| `expires_at` | Claimed integer Unix seconds strictly after issuance |
| `report` | Canonical padded base64 of the exact saved report bytes |
| `report_sha256` | Lowercase SHA-256 of those report bytes, including whitespace |

Issuer and audience labels are 1 to 200 ASCII characters: an initial alphanumeric character followed by alphanumerics or `._:/@-`. Labels are case-sensitive and carry no automatic URL or discovery behavior. Timestamps range from zero through 253402300799.

The signature input is DSSE pre-authentication encoding of the UTF-8 payload type and the unchanged statement bytes. Lengths count bytes. Verifiers must not parse and reserialize the statement before checking its signature. The encoder emits sorted compact ASCII-escaped JSON for convenience; verification accepts other valid statement whitespace while retaining the original bytes.

The algorithm is plain Ed25519 from [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html), with 32-byte public keys and 64-byte signatures. The signature algorithm is fixed by this profile and trusted policy, not chosen by an envelope field. Do not implement curve arithmetic in Foresee or treat the RFC's illustrative code as a production cryptographic dependency. The optional `evidence` extra pins the maintained [cryptography 50.0.2 backend](https://cryptography.io/en/stable/changelog/), using its [Ed25519 API](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/ed25519/). Tests include RFC 8032 section 7.1 test 1. Dependency updates require rerunning the evidence gates.

The outer DSSE key ID is only a lookup hint. Foresee repeats it inside the signed statement and requires exact equality, then recomputes it from the trusted public key. The artifact must never introduce its own trusted public key, key URL, certificate authority, or signature algorithm.

## Existing report compatibility

Keep report version 0.0.2 and evidence version 1 unchanged. The statement wraps the full original report as bytes, including its existing `report_digest`; it does not add a signature field to the report or change the compiler's program digest.

This profile requires an explicit `evidence.complete: true`, no redaction, and a valid ordinary report checksum. Incomplete provider/error reports and redacted copies remain unsigned diagnostic artifacts under this profile. Signing a complete report is planned to require successful semantic replay first. Parsing alone does not establish that the report has all the fields needed for replay.

Whitespace changes to the embedded report change its byte digest and require a new signature, even if its existing semantic checksum remains unchanged. A redacted artifact is a different document, not a substitute signature for the original. No files are overwritten by the current format helpers.

## Verifier-owned trust policy

The next implementation will accept a caller-supplied local policy with version 1 and key entries containing exactly `keyid`, `public_key`, `issuer`, `audiences`, `not_before`, `not_after`, and `status`. Public keys use canonical base64 of 32 raw bytes. Key IDs must match their computed fingerprints; duplicate IDs and empty audience lists are errors. Status is `active` or `revoked`.

The artifact cannot update this policy. Provision it through the operator's trusted deployment channel. No key download, trust-on-first-use, environment-based auto-discovery, or embedded self-signed trust is permitted. Verification must require an explicit expected issuer and audience rather than infer the intended principal from the artifact.

Current validity rules, to be implemented:

1. Require an active matching key whose fingerprint and issuer match local policy.
2. Require the expected audience to match the statement and appear in that key's allowed audiences.
3. Require `not_before <= issued_at < expires_at <= not_after`.
4. Require verifier time `not_before <= now < not_after` and `issued_at <= now < expires_at`.
5. Apply an operator-configured maximum attestation lifetime. No implicit clock-skew grace period.
6. Reject revoked keys regardless of the artifact's claimed issue time.

These rules deliberately do not offer historical acceptance based only on a signer-supplied timestamp. Archival verification after key expiry needs a separate policy with trusted historical evidence, not a backdated `issued_at` value.

## Key ownership and rotation

Operators own private signing keys. Verification never requires private-key access. Initial implementation should expose explicit signer/verifier interfaces so local protected key files can later be replaced by a hardware or managed signer without changing the envelope.

Key generation must be explicit. Private keys must never appear in report JSON, source files, repository fixtures, logs, or command arguments. Local key creation must refuse overwrite and apply restrictive permissions; production custody and backup belong to the deployment operator. Repository vectors must use clearly identified public test material only.

For planned rotation, provision the new public key through the trusted policy channel, allow a bounded overlap of two active keys, switch the signer, then expire or revoke the old key. Each artifact still has one signature. On compromise, revoke immediately and publish a new trusted policy. Offline verifiers using an old policy cannot know about a new revocation, so policy distribution/freshness is an operational requirement. Do not claim global revocation enforcement.

## Planned sign and verify workflows

Signing: bounded-read the report, require the supported complete/unredacted format and checksum, reproduce the decision under an execution budget, construct metadata from explicit caller inputs, obtain the key fingerprint, prepare the statement, sign its DSSE bytes, and write a new envelope without replacing existing files. Failure at any stage must produce no purported signed output.

Verification: bounded-read and inspect the envelope, resolve the expected issuer/audience/key from local policy, check the exact DSSE signature with the maintained backend, enforce key/time/lifetime policy, then replay the embedded report under resource limits. No provider or target access is needed. Reconciliation of actual effects is a separate explicit operation.

Results must distinguish `format_valid`, `signature_valid`, `signer_trusted`, `checksum_valid`, `decision_reproduced`, `origin_authenticated`, and `target_effect_verified`. A malformed artifact or unsupported version is an error. A valid signature from an untrusted key is not authenticated origin. Origin authentication means a policy-trusted key endorsed the bytes; it does not imply semantic replay succeeded. Target effect verification remains false unless a separate adapter verification succeeds. Avoid one ambiguous `verified` flag for all claims.

Repeated verification is read-only. If an application uses attestations for a one-time business action, it must add durable deduplication and an authorization protocol; this audit format must not be used as that protocol.

## Implemented format scaffolding

`foresee.evidence_format` currently provides:

- `key_id(public_key)` for a raw-key fingerprint, with no trust assertion.
- `pae(payload_type, payload)` for DSSE framing.
- `prepare_statement(report_bytes, ...)` for bounded structural/checksum validation and statement serialization.
- `encode_envelope(payload, signature)` for wrapping an externally supplied 64-byte value. It does not verify that value is a signature.
- `inspect_envelope(raw)` returning immutable exact bytes and metadata with `signature_checked=False` and `origin_authenticated=False`.

Limits are 8 MB for report bytes, 11 MB for decoded statement bytes, 15 MB for envelope bytes, and 64 JSON nesting levels. Parsers reject duplicate keys, invalid UTF-8, non-finite numbers including exponent overflow, unknown profile fields, multiple signatures, noncanonical base64, mismatched key IDs, and mismatched checksums. The low-level `pae` helper is an encoder; bounded parsing applies at the envelope/report boundary.

Nine tests cover the framing vector and UTF-8 byte lengths, unchanged signed bytes, malformed encodings, bounds, metadata, report eligibility/checksums, and a real runtime report. Zero-filled signature placeholders in these tests are deliberately non-authentic; successfully inspecting them never sets an authentication flag.

## Implemented signature and trust primitives

Install with `python -m pip install ".[evidence]"` from the checkout. The base package remains dependency-free; importing the module does not load the cryptographic backend. Calling a cryptographic operation without the extra fails explicitly.

`foresee.evidence_auth.sign_statement(payload, private_key)` accepts a caller-owned `cryptography` Ed25519 private-key object. It checks the statement and key fingerprint, signs the exact DSSE bytes, and returns an envelope. This is a low-level endorsement primitive: it does not replay the report, enforce policy, create key files, or claim the signer executed the program. The future report-signing command must enforce bounded replay before invoking it. Do not treat it as that completed workflow.

`authenticate_envelope(envelope_bytes, policy_bytes, expected_issuer=..., expected_audience=..., now=..., max_lifetime=...)` requires all verifier choices explicitly. Supply policy and time from the verifier's trusted configuration, never from the artifact. It accepts only the policy schema above, with at most 65,536 bytes, 64 keys, and 32 unique audiences per key. Empty key lists trust nobody. Parsing rejects unknown fields, duplicate keys/fingerprints/audiences, noncanonical base64, booleans as timestamps, and invalid validity intervals. It performs no discovery, file access, network request, semantic replay, or target access.

After policy and exact-byte signature checks succeed, the immutable result contains the original report bytes, signer metadata, verifier time, and separate true format/signature/trust/checksum/origin fields. `decision_reproduced=None` means replay was not attempted; `target_effect_verified=False` means no effect claim. Rejections raise `ValueError` and return no partial success. Missing backend raises `RuntimeError`. Origin authentication means trusted-key endorsement under the supplied policy at the supplied time, not a global or permanent verdict. Result objects themselves are ordinary Python values, not transferable credentials; another process must verify the envelope again.

Fourteen tests cover a published Ed25519 vector, exact bytes and protocol binding, wrong keys, changed report checksums, signed metadata, issuer/audience policy, precise time boundaries, lifetime limits, rotation/revocation, malformed policy, missing dependency, and the distinction between authenticated origin and reproducible decisions. CI runs them on Python 3.11 through 3.14 on Linux and 3.14 on macOS, then reruns them against an installed wheel outside the checkout. Run `python tools/verify_install.py dist/*.whl --evidence` after building to repeat the installed-package gate.

## Gates before authenticated verification can ship

1. Implemented: maintained Ed25519 backend, standard vector, wrong-key and tampering tests. No handwritten cryptography.
2. Implemented: explicit trust-policy parsing and key, issuer, audience, lifetime, expiry, and revocation rules with negative tests.
3. Implemented for Linux: [bounded replay](bounded-replay.md) with input/depth/output caps, a parent deadline, and kernel CPU/address-space limits. Other platforms fail closed. Composing this with signing and authentication remains pending.
4. Add signer/key custody interfaces and no-overwrite CLI output, plus installed-package end-to-end tests.
5. Verify that legacy unsigned replay remains compatible and never upgrades itself to authenticated origin.
6. Review the combined failure behavior before advertising this as authenticated evidence. The current primitives do not satisfy the remaining replay and key-custody gates.
