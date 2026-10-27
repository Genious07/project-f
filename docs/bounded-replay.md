# Resource-bounded replay

Implemented on 26 October 2026 as an experimental Linux-only API. This is a separate step toward authenticated evidence. The [evidence workflow APIs](authenticated-evidence.md#composed-report-workflow) compose it with signing and authentication as of 27 October. Key-file handling and CLI signing remain pending.

```python
from foresee.bounded_replay import ReplayBudget, replay_bounded

result = replay_bounded(report_bytes, budget=ReplayBudget(
    max_report_bytes=8_000_000,
    wall_seconds=10,
    cpu_seconds=3,
    memory_bytes=512 * 1024 * 1024,
))
assert result.decision_reproduced
```

Pass already bounded bytes, not a path. Callers reading untrusted files must bound that read before constructing the byte string. The base package needs no optional crypto dependency for replay.

## What runs and what is bounded

The parent checks the byte size before launching a fixed worker from the installed package. It uses the current Python executable with `-I -S -B`, an empty environment, no shell, and a new process group. It passes only public resource budgets as arguments and report bytes on an anonymous temporary input file. It does not pass private signing keys or inherited application credentials. The temporary file is removed automatically but is not a secure-erasure mechanism.

The Linux worker installs hard and soft [resource limits](https://docs.python.org/3/library/resource.html) before importing the replay/compiler modules or reading the report. [Linux RLIMIT_AS](https://man7.org/linux/man-pages/man2/getrlimit.2.html) caps virtual address space, not merely the Python heap or resident memory. RLIMIT_CPU caps CPU seconds; RLIMIT_CORE disables crash dumps. Any stricter inherited limit is retained. If limits cannot be installed, the worker refuses to process the report. The interpreter's startup precedes these limits; the parent deadline also covers startup under normal process scheduling.

| Resource | Default | Allowed budget |
| --- | --- | --- |
| Report bytes | 8,000,000 | 1 through 8,000,000 |
| Wall time | 10 seconds | Positive finite value through 60 seconds |
| CPU time | 3 seconds | Integer 1 through 30 seconds |
| Address space | 512 MiB | Integer 64 MiB through 1 GiB |
| Worker response | 128 bytes | Fixed |
| JSON nesting | 64 levels | Fixed by evidence format |

The worker requires report version 0.0.2, explicitly complete/unredacted evidence, a valid checksum, and successful semantic reproduction. It rejects duplicate JSON keys, invalid UTF-8, non-finite values, excess nesting, malformed reports, and checksum-recomputed reports whose recorded decisions cannot be reproduced. Legacy 0.0.1 reports remain supported by the existing replay API, but are not eligible for this stronger result.

The parent enforces the deadline while reading bounded output. It kills the worker process group and reaps the worker on success or failure. Report contents and child diagnostics are never included in failure messages. Operating system stalls and a compromised interpreter are outside this deadline contract.

## Results and failures

Success returns immutable `checksum_valid=True` and `decision_reproduced=True`, with `origin_authenticated=False` and `target_effect_verified=False`. It neither authenticates the signer nor proves real-world execution. The API never silently upgrades a checksum-only report to reproduced evidence.

`ReplayFailure.code` is one of:

- `input_limit`: wrong input type or bytes exceeding the selected cap.
- `unsupported_platform`: host is not Linux. No weaker automatic fallback.
- `limits_unavailable`: the worker could not install the required resource limits.
- `invalid_report`: structure, checksum, or semantic reproduction failed.
- `resource_limit`: the worker caught memory exhaustion.
- `timeout`: the parent deadline elapsed.
- `worker_failed`: worker startup failure, abnormal exit, or signal termination. A CPU limit or unhandled memory failure may surface here; no unsupported diagnosis is inferred from an exit alone.
- `worker_protocol`: excessive or unexpected worker output.

Invalid budget configuration raises `ValueError` before launch. A caller must treat every replay failure as a failed replay gate. A separate successful signature check must not override it when a workflow requires both.

## Security and platform boundary

This is resource isolation for the trusted Foresee interpreter, not a general-purpose OS sandbox. The worker uses the existing offline replay runtime; no provider or live adapter is invoked by that runtime. It does not install a filesystem/network syscall filter, prevent arbitrary native-code exploitation, or protect against a compromised package or host. Kernel limits constrain this fixed worker, not an arbitrary descendant workload. Application admission control is still required to limit concurrent verification requests.

The memory guarantee is currently supported and tested only on Linux. macOS and Windows receive `unsupported_platform`. Existing in-process replay remains unchanged for compatibility and is not advertised as resource bounded.

Eleven tests cover budget validation, pre-spawn input rejection, unsupported platforms, exact worker protocol, empty environment, real timeout/crash/output overflow, full report reproduction, malformed and tampered reports, and Linux CPU/memory enforcement. GitHub runs these on supported Linux Python versions and against clean installed wheels. macOS runs the portable checks and skips the four Linux-specific tests. Run `python -m unittest discover -s tests -p test_bounded_replay.py -v` to inspect the platform-specific result.
