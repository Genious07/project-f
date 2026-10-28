# Experimental evidence commands

Added on 28 October 2026. Install the optional backend with `python -m pip install ".[evidence]"`. Key-file operations require POSIX. Signing and successful combined verification require Linux, where the replay resource limits are supported. This is not a production certification or proof that a real target effect happened.

## Keys and trust

Use an operator-controlled directory outside the repository, with permissions restricting access to the operator. The commands never create parent directories or overwrite an existing destination.

```sh
foresee evidence-keygen --output /secure/operator/signing-key.json
foresee evidence-public-key --key /secure/operator/signing-key.json
```

Key generation writes an **unencrypted** Ed25519 seed in a versioned JSON file with owner-only permissions. Only public metadata (`algorithm`, `keyid`, `public_key`) appears on stdout. Public export displays the same metadata from an existing key. No private key material belongs in command arguments, source control, logs, reports, or trust policies. These commands do not provide encrypted storage, hardware custody, memory zeroization, or secure deletion. File permissions do not protect against the same user, root, backup readers, or a compromised host.

The verifier's operator must independently provision the public key through a trusted channel in the [explicit trust-policy format](authenticated-evidence.md). Generating a key or receiving an envelope never establishes trust. A policy looks like:

```json
{
  "version": 1,
  "keys": [{
    "keyid": "sha256:REPLACE_WITH_PUBLIC_FINGERPRINT",
    "public_key": "REPLACE_WITH_CANONICAL_PUBLIC_KEY_BASE64",
    "issuer": "deployment/team",
    "audiences": ["audit/production"],
    "not_before": 100,
    "not_after": 300,
    "status": "active"
  }]
}
```

The example is deliberately incomplete and uses illustrative Unix timestamps; replace them with the intended key validity period and real public metadata. The `algorithm` field printed by export is not part of a policy entry. Do not paste the entire key file or export object into the policy.

## Sign and verify

```sh
foresee evidence-sign report.json --key /secure/operator/signing-key.json \
  --output evidence.json --issuer deployment/team --audience audit/production \
  --issued-at 100 --expires-at 200

foresee evidence-verify evidence.json --policy /secure/operator/trust-policy.json \
  --issuer deployment/team --audience audit/production \
  --now 150 --max-lifetime 100
```

These timestamps illustrate the policy above, not a current deployment. Supply actual issuance/expiry and a trusted verifier evaluation time in integer Unix seconds. `--now` is required explicitly; never derive it from the artifact. Labels and maximum attestation lifetime are also explicit. Signing validates and reproduces the report before writing any output. It does not certify that any particular verifier trusts the signer.

Both commands accept `--wall-seconds`, `--cpu-seconds`, `--memory-mib`, and `--max-report-bytes`, using the [bounded replay defaults and ranges](bounded-replay.md). The report is capped before reading it into memory. Envelope, policy, and private-key files are capped at 15 MB, 65,536 bytes, and 4,096 bytes respectively.

Verification prints only separate claims and signer metadata, not the embedded report or signature bytes. `requirements_satisfied` means trusted origin and bounded decision reproduction both succeeded. `target_effect_verified` remains false. A trusted signature with failed replay retains `origin_authenticated=true` but returns `requirements_satisfied=false`, a replay error code, and exit status 2.

| Exit | Meaning |
| --- | --- |
| 0 | Command succeeded; verification satisfied both requirements |
| 1 | File, configuration, authentication, signing, or other handled failure; no success JSON |
| 2 | Verification authenticated the signer but replay failed; also argparse usage errors, which emit no result JSON |

Always check the exit code and the verification result. A low-level signature alone is not acceptance. Existing `replay`, `inspect`, and runtime behavior remain unchanged.

## File guarantees and limits

Reads open the final component without following symlinks, use nonblocking mode to avoid FIFO hangs, and require a bounded regular file. Key reads also require ownership by the current user, no group/other permission bits, and a single hard link. Read-only owner keys are accepted. The directory hierarchy must be trusted: these checks do not prevent hostile parent-directory replacement or same-user file mutation.

Writes use an owner-only temporary file in the destination directory, flush and sync its contents, then create the destination using an atomic hard link. Existing files, symlinks, and competing destination creation cause failure; nothing is overwritten. Temporary files are cleaned up on handled failures. This requires filesystem hard-link support. It does not promise directory-entry durability through power loss, recovery of temporary files after process termination, or secure erasure. A concurrent reader may transiently see two hard links and reject a just-published private key until cleanup finishes.

Tests cover ordinary success, ownership/mode checks, malformed secret-safe errors, hard links, symlinks, FIFOs, directories, byte caps, output protection, and temporary-file cleanup. GitHub additionally runs a real Linux sign/verify cycle, replay-budget rejection, wrong-audience rejection, and installed-wheel checks. Final release acceptance still requires review of the combined protocol and operations.
