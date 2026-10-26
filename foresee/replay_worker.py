"""Internal Linux replay worker. Resource limits precede report/module loading."""
import sys


def _install_limits(cpu_seconds, memory_bytes):
    if sys.platform != 'linux':
        raise ValueError('Linux limits required')
    import resource
    # Retain any stricter limits inherited from the operator's process.
    for kind, requested in ((resource.RLIMIT_CORE, 0), (resource.RLIMIT_AS, memory_bytes),
                            (resource.RLIMIT_CPU, cpu_seconds)):
        soft, hard = resource.getrlimit(kind)
        limits = [requested] + [value for value in (soft, hard) if value != resource.RLIM_INFINITY]
        value = min(limits)
        resource.setrlimit(kind, (value, value))
        if resource.getrlimit(kind) != (value, value):
            raise ValueError('resource limit not installed')


def main():
    try:
        if len(sys.argv) != 4:
            raise ValueError('invalid worker arguments')
        maximum, cpu, memory = map(int, sys.argv[1:])
        if not 1 <= maximum <= 8_000_000 or not 1 <= cpu <= 30 or not 64 * 1024**2 <= memory <= 1024**3:
            raise ValueError('invalid worker budget')
        _install_limits(cpu, memory)
    except (ValueError, OSError, ImportError):
        sys.stdout.buffer.write(b'{"error":"limits_unavailable"}')
        return
    try:
        # -I -S excludes the working directory, environment, and site hooks.
        # Only the directory of this trusted installed package is added back.
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from foresee.evidence_format import _json, _report
        from foresee.replay import reproduce
        raw = sys.stdin.buffer.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('input limit')
        _report(raw)
        report = _json(raw, maximum)
        if reproduce(report) is not True:
            raise ValueError('decision not reproduced')
        response = b'{"version":1,"decision_reproduced":true}'
    except MemoryError:
        response = b'{"error":"resource_limit"}'
    except Exception:
        # Do not send source, paths, report content, or exception text to callers.
        response = b'{"error":"invalid_report"}'
    sys.stdout.buffer.write(response)


if __name__ == '__main__':
    main()
