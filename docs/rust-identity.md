# Native canonical program identity

The native compiler now produces complete schema 0.0.3 IR with the same program digest as the Python reference for the tested shared subset.

```sh
cargo run -p foresee-semantics -- identity examples/repair.fore
python tools/check_identity.py
```

The development command returns `ok`, `checked_phase: "identity"`, `executable: false`, `canonical_json`, and `ir`. The envelope is for inspection and does not execute anything. Its `ir` field contains the complete checked document with `program_digest`; its `canonical_json` field contains the exact ASCII JSON string hashed before the digest is inserted. Decode the envelope before inspecting these bytes: the outer JSON encoding escapes this string a second time.

The library entry point is `canonical::compile_source`. It first lowers checked source using the ownership stage, then serializes and hashes that body. The resulting `CompiledProgram` has private fields, supports serialization of the full IR, and exposes the preimage through `canonical_json()`. Rejected source returns diagnostics without an artifact. It does not accept arbitrary external JSON.

## Byte contract

Canonical bytes match Python `json.dumps(body, sort_keys=True, separators=(",", ":"))` with its default ASCII escaping. Object keys sort recursively by Unicode scalar order. Array order is preserved. Strings escape quotes, backslashes, control characters, DEL, and non-ASCII scalars; supplementary scalars use lowercase hexadecimal UTF-16 surrogate pairs. Slashes remain literal. No Unicode normalization is performed.

Integers retain their full decimal precision. The serializer rejects non-integer numeric forms, which cannot occur in successfully lowered source. Compact separators introduce no whitespace. SHA-256 hashes the ASCII bytes and produces 64 lowercase hexadecimal characters. The digest field is inserted only afterward, so it never hashes itself. Ordinary JSON serialization of the final artifact is not the canonical preimage.

Hashing uses the `sha2` crate, with the resolved dependency graph recorded in Cargo.lock. No subprocess, Python interpreter, network service, clock, or runtime resource participates in native compilation.

## Identity rules

Whitespace, comments, line endings, checked annotations, redundant effect declarations, effect order, and leading zeros on equivalent integer literals preserve identity. Changes to prompts, candidate limits, binding or metric names, check messages, and ordered statements change it. This is structural identity, not proof that two programs behave equivalently. It also does not authenticate an artifact or authorize a live effect.

## Evidence and scope

Twenty-seven stored fixtures include source, expected canonical text, and expected digest. They cover unchanged and changed identities, Unicode, all ASCII controls, escaped strings, large integers, and multiple explorations. The runner also checks 182 earlier cases. Accepted programs must match Python canonical bytes, SHA-256 digests, and full IR; rejected programs must match diagnostic codes, order, and spans without IR or canonical output.

Five Rust unit tests cover exact escape bytes and Unicode key ordering, large numbers, object and array ordering, a standard SHA-256 vector, and exclusion of the digest from its preimage. Three Python tests protect frozen expectations, dictionary insertion-order independence, and statement-order sensitivity. Hosted CI runs the native comparisons on Linux and macOS.

The earlier `ir` command intentionally continues to emit only the digest-free body. Python remains the runtime. Native user-facing `check` and `build` commands, distribution, and broader generated-program coverage remain subsequent milestones; this change does not publish a new release.
