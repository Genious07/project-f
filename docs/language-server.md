# Native language server foundation

Foresee now includes a standalone `foresee-lsp` binary:

```sh
cargo build --workspace --locked
./target/debug/foresee-lsp
```

The process waits for framed language-server messages on stdin. It is intended to be launched by an editor client, not used as an interactive terminal prompt. Configure an LSP-capable editor adapter to run the absolute binary path over stdio for `.fore` documents, using language ID `foresee`. No arguments, Python interpreter, model credentials, or running database are required. A packaged editor extension and automatic file associations are not included.

The server follows the [Language Server Protocol 3.17 specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) for its supported stdio, lifecycle, document, and language-feature messages. It advertises UTF-16 positions, open/close notifications, full-document synchronization, document symbols, and hover. Other features are not advertised.

## Supported session

1. Send `initialize` as a request, then `initialized` as a notification.
2. Send `textDocument/didOpen` with URI, version, and complete text. The server publishes compiler diagnostics with the same URI and version.
3. Send `textDocument/didChange` with a greater version and full-text changes. If multiple full-text changes are supplied, the last is the final document state. Successful checking publishes an empty diagnostic list, clearing old errors.
4. Request `textDocument/documentSymbol` or `textDocument/hover` for an open document.
5. Send `textDocument/didClose` to release document state and clear diagnostics.
6. Request `shutdown`, wait for the null response, then notify `exit`.

The process returns 0 after shutdown, 1 on exit/EOF without shutdown, and 2 on a framing or transport failure. Unknown request methods return JSON-RPC -32601. Requests before initialization return -32002. Malformed JSON within a complete frame receives -32700 and the next frame can still be processed. Invalid requests and parameters receive their corresponding JSON-RPC errors. Notifications do not receive response objects; invalid document notifications are logged or reported as limit diagnostics.

## Editor behavior

Diagnostics come from the native ownership checker, including syntax, declarations, types, effects, origins, and single-use selections. Compiler character offsets are converted to zero-based UTF-16 positions. LF, CRLF, and CR line endings are handled by the position conversion. A non-BMP character such as an emoji counts as two UTF-16 units. Diagnostic severity is error and source is `foresee`.

Document symbols list resource, model, and decision declarations when syntax parses, even if semantic checking fails. Their ranges span declarations; selection ranges cover identifier tokens. Local bindings and nested outline items are not included yet.

Hover is available only when the current document passes complete semantic checking. It returns plain-text inferred type metadata, including resource, trial metrics, and snapshot lineage. Current compiler expression spans identify leading tokens: hover over a variable reference or operation keyword, rather than an arbitrary point inside a compound expression. Hover over an invalid, unopened, closed, oversized, or unrelated position returns null.

The server never reads a document URI from disk and never builds or executes source. Unsaved editor buffers are authoritative. Versions must increase; stale or equal-version changes are ignored. Incremental range edits are unsupported and logged without applying them. Duplicate opens and changes for unopened documents are also logged. An oversized accepted-version edit replaces the previous content with unavailable state and publishes F0001, preventing old hover/type information from surviving that edit.

## Limits and scope

| Limit | Value |
| --- | ---: |
| Header bytes | 8,192 |
| JSON frame body bytes | 8,000,000 |
| Open documents | 16 |
| URI UTF-8 bytes on document notifications | 4,096 |
| Source UTF-8 bytes per document | 1,000,000 |

The existing [compiler budgets](compiler-limits.md) apply to document analysis. Oversized document text is not retained. An extra open beyond the document limit receives a limit diagnostic; close another document and resend the open to retry. Headers and frame sizes are checked before body allocation; duplicate or invalid content lengths, truncated frames, and oversized headers terminate the transport cleanly. Stdout is reserved for framed messages; transport failures go to stderr.

This first server is synchronous. It analyzes open documents in notification order and recomputes type information for hover requests. It does not perform background workspace indexing, incremental parsing, completion, rename, formatting, code actions, filesystem watching, or asynchronous cancellation. Cancellation notifications are accepted but do not interrupt an in-progress bounded computation. Only advertised capabilities should be used by clients.

## Verification

```sh
python tools/check_lsp.py
```

The integration runner copies the server into a temporary directory and launches it with an empty PATH. It opens broken source at a URI that does not exist on disk, checks a diagnostic after an emoji, edits the source, and observes diagnostics clear. It then verifies document symbols, a selected-value hover and its lineage, stale-version handling, diagnostic clearing on close, unknown-method rejection, and clean shutdown. This is a real subprocess protocol test, not an installed GUI-editor test.

Seven Rust tests cover framing bounds and recovery, lifecycle, UTF-16 conversion, document edits, limits, unavailable state after oversized changes, and symbol ranges (including brace characters inside strings). Two Python tests protect client framing byte counts and position expectations. Linux and macOS CI run the same standalone session.

The existing `foresee-semantics` compiler remains the package's default Cargo run target. Native archives and installation are the next milestone; this change does not publish a release or install an editor extension.
