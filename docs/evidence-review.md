# Evidence workflow internal review

Reviewed on 3 November 2026. Scope: the DSSE/Ed25519 profile, policy validation, composed APIs, Linux bounded replay worker, POSIX file custody, command-line behavior, and installed-package tests. This is a source-and-test review by the implementing agent, not an independent security audit, penetration test, or proof of protocol correctness.

## Findings and corrections

1. The high-level signer prepared a statement before checking a caller's smaller replay byte budget. The fixed API rejects input type/size before backend access, encoding, or worker launch. The global format ceiling alone was insufficient to honor the caller's chosen limit early.
2. A combined verification result was an ordinary truthy Python object even when its replay failed. Although documented callers checked `requirements_satisfied`, `if result:` could accidentally accept failure. Both successful and failed results now raise `TypeError` on implicit boolean conversion. This intentional API tightening requires explicit claim selection.
3. The bounded file helper did not explicitly validate its limit parameter. It now rejects nonpositive values, booleans, and nonintegers before opening a file. CLI limits were already validated by their budgets/constants.

Five regression tests cover these corrections, concurrent output publication, and CLI policy rejections. Legacy replay tests additionally assert that old checksum-only reports never claim authenticated origin or verified target effects.

## Acceptance matrix

| Boundary | Required behavior | Evidence |
| --- | --- | --- |
| Format | Reject ambiguous JSON, unknown fields, malformed encodings, excess bytes/depth, unsupported report versions | `test_evidence_format.py` |
| Signature | Bind exact payload bytes and type; reject changed report even when ordinary checksums are recomputed | `test_evidence_auth.py` |
| Trust | Reject unknown/revoked keys, issuer/audience mismatch, invalid validity and lifetime; support explicit rotation | `test_evidence_auth.py`, CLI policy regression |
| Signing | No signature after any replay failure; input cap before encoding/backend | `test_evidence_workflow.py` |
| Combined result | Preserve separate origin/replay claims; explicit acceptance check; no effect claim | `test_evidence_workflow.py` |
| Worker | Fixed program, no inherited credentials, input/output caps, parent timeout, Linux CPU/address-space limits | `test_bounded_replay.py` |
| Keys | Reject inappropriate ownership/mode, hard links, symlinks, malformed key material; never print seeds | `test_evidence_cli.py` |
| Files | Bounded regular reads, failure cleanup, no replacement; exactly one complete concurrent publisher | `test_evidence_cli.py` |
| CLI | Exit 0 only for successful combined verification; replay failure 2; trust/file/configuration failure 1 | Linux CLI round trip and portable rejection tests |
| Compatibility | Unsigned replay keeps its prior behavior and never authenticates itself | `test_replay.py` |
| Distribution | Repeat evidence tests using a clean installed wheel outside the checkout | `tools/verify_install.py --evidence` |

The Linux jobs run the real memory/CPU and signing/verification tests. macOS exercises file custody, signature/policy checks, unsupported-platform behavior, and portable process tests; six Linux tests are explicitly skipped. Passing on macOS is not evidence of bounded replay support there. The parent process's bounded JSON decoding and signature checks are not covered by the worker's memory/CPU limits. Concurrent request admission remains an operator responsibility.

## Operator procedures

Provision keys in a trusted, restricted directory outside the checkout. Transfer only the public fingerprint/key through an independently trusted channel. Install a verifier-controlled policy with intended issuer, audiences, and key validity. Do not accept trust policy or verifier time from an envelope sender. Private key files are unencrypted and require separate host, backup, and access controls.

For rotation, distribute the new public key and policy first, allow a bounded overlap, switch signing keys, then expire or revoke the old key. On suspected compromise, revoke the old key immediately and distribute the updated policy to every verifier. Offline verifiers with stale policy cannot discover revocation. A historical issuance claim does not prove an artifact predates compromise.

On timeout, worker failure, unsupported platform, or failed replay, reject combined acceptance. Inspect the stable error code and operator-selected budget; do not automatically fall back to unsigned replay or bypass trust rules. Retry only as an explicit operational decision. Verification is read-only and does not consume an artifact; application-level deduplication is required for any separate business action.

On output collision, preserve the existing file and choose a new destination after inspection. On process termination, inspect any leftover `.foresee-*` files in the trusted directory before cleanup. An interruption after publication may leave a complete destination even if no success message was observed. Never assume a nonzero exit means no filesystem effect. Temporary-file removal is not secure erasure; directory entries are not promised durable through power loss.

## Release disposition and remaining limits

The workflow remains experimental. This review closes the planned internal combined-review step, but does not publish a release or resolve the outstanding project license decision. Release from an exact tested commit only after all ten Verify jobs pass, version and license metadata are consistent, and the intended package/archive artifacts are inspected. Do not replace the existing alpha release.

A trusted signer can endorse fabricated but internally reproducible evidence. Neither signatures nor replay prove model execution, database authenticity, trustworthy timestamps, or actual target effects. The worker is a resource boundary for a trusted interpreter, not a filesystem/network sandbox against native-code exploitation. Parent directories and installed code must be trusted. File mode checks do not protect against the same user, root, host compromise, or privileged backup access; ACL-specific policies are not inspected.

Encrypted or hardware-backed keys, independent security review, archival timestamp/transparency mechanisms, stronger host isolation, and non-Linux bounded replay are not implemented by this milestone. Deployment suitability depends on those limits and the application's trust requirements; test counts alone are not a production-readiness claim.
