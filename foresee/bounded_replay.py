"""Linux resource-bounded replay of complete reports in a fixed worker.

This is a resource boundary for the trusted interpreter, not an OS sandbox.
"""
from dataclasses import dataclass, field
import math
from pathlib import Path
import sys

from .model_provider import ProcessTransport, ProposalFailure

MAX_REPORT_BYTES = 8_000_000


class ReplayFailure(ValueError):
    """Safe stable failure code, without report contents or child diagnostics."""
    def __init__(self, code):
        self.code = code
        super().__init__(f'bounded replay failed: {code}')


@dataclass(frozen=True)
class ReplayBudget:
    max_report_bytes: int = MAX_REPORT_BYTES
    wall_seconds: float = 10.0
    cpu_seconds: int = 3
    memory_bytes: int = 512 * 1024 * 1024

    def __post_init__(self):
        for name, minimum, maximum in (('max_report_bytes', 1, MAX_REPORT_BYTES),
                                        ('cpu_seconds', 1, 30),
                                        ('memory_bytes', 64 * 1024 * 1024, 1024 * 1024 * 1024)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'invalid replay budget: {name}')
        if (type(self.wall_seconds) not in (int, float) or not math.isfinite(self.wall_seconds)
                or not 0 < self.wall_seconds <= 60):
            raise ValueError('invalid replay budget: wall_seconds')


@dataclass(frozen=True)
class ReplayedReport:
    checksum_valid: bool = field(default=True, init=False)
    decision_reproduced: bool = field(default=True, init=False)
    origin_authenticated: bool = field(default=False, init=False)
    target_effect_verified: bool = field(default=False, init=False)


_SUCCESS = b'{"version":1,"decision_reproduced":true}'
_ERRORS = {b'{"error":"invalid_report"}': 'invalid_report',
           b'{"error":"resource_limit"}': 'resource_limit',
           b'{"error":"limits_unavailable"}': 'limits_unavailable'}


def replay_bounded(report, *, budget=None):
    """Replay exact report bytes without inheriting application credentials.

    Requires Linux, fails closed on unavailable limits, and never falls back to
    in-process replay. Only the fixed, installed worker is launched. No signing
    key is supplied to it. Caller-owned bytes must already fit the input cap.
    """
    budget = ReplayBudget() if budget is None else budget
    if type(budget) is not ReplayBudget:
        raise ValueError('budget must be a ReplayBudget')
    if type(report) is not bytes or len(report) > budget.max_report_bytes:
        raise ReplayFailure('input_limit')
    if sys.platform != 'linux':
        raise ReplayFailure('unsupported_platform')
    worker = Path(__file__).with_name('replay_worker.py').resolve()
    argv = [sys.executable, '-I', '-S', '-B', str(worker), str(budget.max_report_bytes),
            str(budget.cpu_seconds), str(budget.memory_bytes)]
    # No credential, PYTHONPATH, loader, or user-site environment inheritance.
    transport = ProcessTransport(argv, env={})
    try:
        response = transport.exchange(report, timeout_seconds=budget.wall_seconds, max_response_bytes=128)
    except ProposalFailure as error:
        code = {'timeout': 'timeout', 'response_limit': 'worker_protocol'}.get(error.code, 'worker_failed')
        raise ReplayFailure(code) from None
    if response == _SUCCESS:
        return ReplayedReport()
    raise ReplayFailure(_ERRORS.get(response, 'worker_protocol'))
