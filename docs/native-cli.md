# Native compiler command line

Build the Rust workspace once, then check and compile source without a Python interpreter or model credential:

```sh
cargo build --workspace --locked
./target/debug/foresee-semantics check examples/repair.fore
./target/debug/foresee-semantics build examples/repair.fore -o repair.ir.json
```

The binary name remains `foresee-semantics` so it does not conflict with the Python `foresee` runtime. Compilation is offline. `check` runs declaration, type, effect, lineage, and ownership validation. `build` runs the same checks and writes complete typed IR schema 0.0.3 with its canonical program digest. The file contains IR directly, without the development command's inspection envelope.

Use `--help` or `check --help` / `build --help` for usage. Both commands require exactly one source file. Build additionally requires `-o OUTPUT` or `--output OUTPUT`. Options may precede or follow the source. Use `--` before a source path beginning with a dash; put any options before the separator. Standard input and output streaming are not supported by these two commands.

## Diagnostics and exit codes

Human output is the default. Successful commands print `Checked PATH` or `Built PATH` to stdout. Rejected source prints diagnostics to stderr, each containing a code, message, and `PATH:LINE:COLUMN`. Line and column numbers are one-based character positions, consistent with the compiler's existing spans. Human diagnostics escape control characters in paths and messages.

```sh
./target/debug/foresee-semantics check examples/repair.fore --format json
./target/debug/foresee-semantics build examples/repair.fore -o repair-v2.ir.json --format json
```

JSON mode writes one response object to stdout. A successful response contains `ok`, `command`, `source`, and `output` (null for check). Source rejection contains `ok: false`, `command`, `source`, and `diagnostics`; each diagnostic retains its code, message, and span. It contains no IR. Invocation/input/output/internal failures instead contain `ok: false` and `error: {kind, message}`, where `kind` is `usage`, `input`, `output`, or `internal`. Supported JSON mode is also honored for invalid options when `--format json` is present. Error prose can evolve; automation should use exit codes, diagnostic codes, and error kinds.

| Exit | Meaning |
| --- | --- |
| 0 | Check succeeded, build completed, or help displayed |
| 1 | Source rejected by syntax, semantic, or compiler resource checks |
| 2 | Invocation, input, output, internal, or response-stream failure |

Unreadable input, invalid UTF-8, and files larger than 1,000,000 bytes return 2 before lexing. Other compiler budgets retain the [day 11 limit contract](compiler-limits.md). The commands preserve native paths, including non-UTF-8 paths where the filesystem permits them; display/JSON names use replacement characters when necessary.

## Output publication

Build requires an existing parent directory and a destination that does not exist. Existing files, directories, symlinks, and the source itself are preserved. To rebuild, choose a new destination or explicitly remove the old artifact yourself. A failed source check never creates a destination.

The compiler first serializes the complete IR, writes a uniquely created temporary file in the output directory, flushes it with `sync_all`, and then creates a hard link at the destination. Linking fails if that destination already exists, avoiding a check-then-overwrite race. Temporary-file cleanup is attempted on success and failure. Filesystems that do not support hard links return an output error; there is no overwrite fallback. This provides complete-file publication, not a filesystem crash-recovery protocol or directory durability guarantee.

If publication succeeds but printing the response fails, the process returns 2 and the complete artifact may already exist. Inspect the requested output before retrying. No live resource changes are performed by either command.

## Verification and scope

Ten Rust process tests copy the binary into an isolated temporary directory and exercise it outside the repository. They cover offline check/build, human and JSON rejection, usage/input failures, source size and encoding, existing output/source preservation, missing parent directories, directory and symlink destinations, help, dash-prefixed sources, non-UTF-8 path handling, and escaped human path display.

`python tools/check_cli.py` copies the binary and runs both commands with an empty PATH over 226 stored cases and 32 generated cases. It verifies acceptance, diagnostic codes and spans, complete IR equality, and absence of artifacts on rejected source. The Python interpreter runs this verification harness; the copied native compiler itself has no interpreter dependency. Linux and macOS CI run the same checks.

The earlier `declarations`, `types`, `effects`, `lineage`, `ownership`, `ir`, and `identity` commands retain their development contracts. Execution remains in Python. Native archives and installation support are planned for day 14; this milestone neither publishes a new release nor introduces native runtime effects.
