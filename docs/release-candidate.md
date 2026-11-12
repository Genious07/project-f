# Draft next preview release

Prepared on 6 November 2026. Updated on 12 November 2026 after the owner selected MIT. Candidate version mapping: tag `v0.2.0-alpha.1`, Python `0.2.0a1`, native crates `0.2.0-alpha.1`. Python/Rust versions and Cargo.lock now match this candidate. The previous alpha remains unchanged. Publication requires the exact candidate CI/artifact checks below.

## Draft release description

Foresee's next preview adds a native compiler and editor foundation, bounded model proposals, and an experimental signed-evidence workflow. It keeps decision execution in the Python runtime while checking source programs and emitting matching typed IR through the Rust compiler.

Included scope:

- Native source checking and IR generation with type, effect, snapshot-lineage, and selection-ownership checks. Linux x86-64 and macOS ARM64 preview archives include the compiler, LSP executable, example program/IR, checksums, manifest, and Cargo dependency inventory.
- A language-server foundation supporting diagnostics, full-document edits, symbols, and type/lineage hover. Completion, rename, incremental analysis, and an editor extension are not included.
- Bounded model-provider transport and an opt-in OpenAI Responses adapter with configured token/cost limits. Tests use mocks and credential-free worker checks; live account/model compatibility has not been verified.
- A twelve-check adapter conformance kit for the current Catalog/Patch domain. SQLite remains the implemented transactional adapter.
- Experimental Ed25519 report signing, explicit trusted-key policy, Linux bounded replay, and key-generation/signing/verification commands. Verification keeps trusted origin, reproduced decision, and real target effects separate.

The evidence workflow requires the optional `evidence` dependency. POSIX key files are unencrypted and owner-only; full signing and combined verification require Linux. The worker has resource limits but is not a general OS sandbox. Signatures and replay do not establish that model calls, database observations, or target effects happened in the real world. The internal review is available in [evidence-review.md](evidence-review.md); it is not an independent security audit.

Compatibility notes: existing unsigned replay remains unauthenticated. Combined verification results require explicit `.requirements_satisfied` checks; implicit boolean conversion raises `TypeError`. Native compiler limits and supported syntax remain as documented in the compiler preview report. This is a preview, not a production-stability promise.

Validation at the preparation stage: 212 Python tests in the suite; six are Linux-only and skipped on macOS. The complete Verify workflow also checks native compiler parity/fuzzing, editor integration, Python package installation, the runtime container, and both native archive targets. A final release description must link to the successful workflow for the exact release commit and report that run's results, not reuse this draft as evidence.

## Source preflight

MIT has been selected and candidate metadata applied. From the clean committed candidate:

```sh
python tools/check_release_source.py \
  --python-version 0.2.0a1 \
  --native-version 0.2.0-alpha.1 \
  --license-id MIT
```

MIT is the owner-selected license; the tool does not select or recommend one. It checks exact declaration equality, not SPDX syntax validity, legal suitability, or license-text authenticity. It requires a nonempty tracked regular `LICENSE` file, explicit Python `project.license-files` inclusion, consistent declarations across the explicit Rust workspace members, consistent versions in Cargo.lock, and a clean checkout. Metadata inheritance and workspace globs are not supported by this repository-specific preflight.

Exit 0 means only `source_ready=true`. Exit 1 means source prerequisites failed or could not be read. `publication_authorized` is always false. The tool performs no writes, builds, network calls, tags, or publication. Omitting `--license-id` intentionally fails the license-selection check.

## Remaining concrete work

1. Completed: owner selected MIT; LICENSE names Satwik Singh, and Python/Rust declarations are aligned. NOTICE retains upstream Cargo and Rust standard-library notices.
2. Confirm release versions and update Python/native metadata and Cargo.lock together. Include LICENSE/notices in wheel, source distribution, and both native archives. The native archive builder now includes root LICENSE and NOTICE when present and records the unanimous workspace license declaration. Its strict release verifier checks expected commit/version/license and a clean source manifest. Python wheel/source inclusion and any additional required notice files still need checking; the candidate now carries MIT and upstream notices.
3. Inspect the native SBOM workspace declaration and dependency declarations/notices; inconsistent or missing workspace licenses remain explicitly undeclared. The SBOM covers the Cargo graph, not Python dependencies, OS libraries, or binary linkage. The optional crypto backend also needs its distribution notices checked.
4. Commit the complete candidate and run source preflight from a clean checkout. Require all ten Verify jobs to pass on that exact commit. Download that run's artifacts, inspect packaged metadata/licenses and native manifests, and retain their checksums/provenance.
5. Finalize these notes using the exact tested version, commit, workflow, and artifacts. Create a new prerelease and attach those artifacts without rebuilding from a different checkout or replacing the existing alpha.

A future release tool must enforce these artifact and hosted-CI gates before publication. This source preflight intentionally does not imply those checks have happened.

## Native candidate verification

Added on 7 November. Run on each archive's matching host after setting the actual candidate values:

```sh
python tools/verify_native.py PATH_TO_ARCHIVE.tar.gz --release \
  --expected-commit FULL_40_CHARACTER_COMMIT \
  --expected-version 0.2.0-alpha.1 --license-id MIT
```

The verifier checks candidate metadata and nonempty LICENSE before extraction/execution, in addition to normal archive member and checksum validation. It requires `source_dirty` to be the actual JSON boolean false and `preview` to be true. Expectations must come from the release operator, not be copied automatically from an untrusted archive. The archive itself must be trusted: matching self-reported provenance and recomputable checksums is not an authenticated build attestation. This command executes bundled binaries after inspection, as the existing preview verifier does.

Optional LICENSE/NOTICE members are bounded and covered by the manifest hashes. This checks presence, byte integrity, and declared license equality, not legal-text correctness, sufficiency of dependency notices, or publication approval. Native CI now invokes strict release verification with MIT and the exact GitHub commit. No released version is inferred from this test.

## Python candidate verification

Added on 9 November. With the operator-selected version/license and a trusted reviewed directory containing LICENSE and any NOTICE:

```sh
python tools/verify_python_release.py PATH_TO_WHEEL.whl PATH_TO_SOURCE.tar.gz \
  --expected-version 0.2.0a1 --license-id MIT \
  --legal-dir /path/to/reviewed/legal/files
```

The checker reads both formats without extraction, installation, or execution. It requires the expected project name/version, one matching `License-Expression`, supported metadata version 2.4 through 2.6, and exact `License-File` declarations for the supplied LICENSE and optional NOTICE. It compares their archived contents byte-for-byte with the reviewed files. Wheel legal files reside under `.dist-info/licenses/`; source legal files reside under the expected distribution root. These checks follow the [Python core metadata](https://packaging.python.org/en/latest/specifications/core-metadata/) and [wheel license-file layout](https://packaging.python.org/en/latest/specifications/binary-distribution-format/) specifications.

This repository-specific checker rejects duplicate or unsafe member paths, links/special files, additional wheel package metadata, unexpected source roots, and oversized archives/text. Limits are 128 MiB compressed and summed expanded size, 10,000 members, and 2 MB per inspected metadata/legal file. Only LICENSE and NOTICE are supported legal-file names; extend the checker and tests if the selected license requires other paths. A selected license's legal sufficiency, copyright ownership, dependency obligations, and SPDX expression validity are not determined by string equality.

Exit 0 means the requested package checks passed. The JSON includes each artifact's SHA-256 and always reports `publication_authorized=false`. A failure returns exit 1 and no successful artifact result. The command does not verify wheel RECORD entries, package code integrity, build provenance, signatures, or hosted CI. It is not a general wheel validator or an upload service for arbitrary hostile archives. Retain the hashes with the exact CI artifact provenance, and still run the installed-package tests.

Seven focused tests cover both formats and rejection paths. A local fixture built with the pinned setuptools/wheel backend also passed both format checks; its temporary LicenseRef-Test material was never added to the project. Historical unlicensed packages fail this gate; current candidate CI requires MIT and exact LICENSE/NOTICE bytes.
