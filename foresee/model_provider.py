"""Bounded proposal protocol and an opt-in, trusted subprocess transport."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from typing import Protocol

from .catalog import Catalog
from .providers import ProviderError


class ProposalFailure(ProviderError):
    """Stable error code and safe message; never expose transport exception text."""
    def __init__(self, code):
        self.code = code
        super().__init__(f'model proposal failed: {code}')


@dataclass(frozen=True)
class ProposalBudget:
    max_calls: int = 1
    max_candidates: int = 4
    max_patches: int = 1000
    max_request_bytes: int = 262144
    max_response_bytes: int = 262144
    timeout_seconds: float = 10.0

    def __post_init__(self):
        for name, ceiling in [('max_calls', 100), ('max_candidates', 4), ('max_patches', 1000),
                              ('max_request_bytes', 2_000_000), ('max_response_bytes', 2_000_000)]:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f'{name} must be an integer from 1 to {ceiling}')
        if type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ValueError('timeout_seconds must be finite, positive, and at most 120')


class ProposalTransport(Protocol):
    def exchange(self, request: bytes, *, timeout_seconds: float, max_response_bytes: int) -> bytes:
        """Return bounded bytes or raise; implementations must enforce the deadline."""
        ...


class ProcessTransport:
    """POSIX process boundary, not a sandbox. Only run explicitly trusted commands."""
    def __init__(self, argv):
        if os.name != 'posix':
            raise ValueError('process transport requires POSIX')
        if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(x, str) or not x or '\0' in x for x in argv):
            raise ValueError('argv must contain nonempty command arguments')
        self.argv = tuple(argv)

    def exchange(self, request, *, timeout_seconds, max_response_bytes):
        deadline = time.monotonic() + timeout_seconds
        # Bounded input is delivered as a file so a child that never reads stdin
        # cannot block the parent in a pipe write before deadline enforcement.
        with tempfile.TemporaryFile() as source:
            source.write(request)
            source.seek(0)
            try:
                process = subprocess.Popen(self.argv, stdin=source, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                raise ProposalFailure('transport_error') from None
            try:
                output = bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise ProposalFailure('timeout')
                        chunk = os.read(process.stdout.fileno(), min(65536, max_response_bytes + 1 - len(output)))
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > max_response_bytes:
                            raise ProposalFailure('response_limit')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProposalFailure('timeout')
                if process.wait(timeout=remaining) != 0:
                    raise ProposalFailure('transport_error')
                return bytes(output)
            except subprocess.TimeoutExpired:
                raise ProposalFailure('timeout') from None
            except OSError:
                raise ProposalFailure('transport_error') from None
            finally:
                # Kill the session's process group, including children holding
                # stdout open. A deliberately detached process is outside this contract.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdout.close()


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('non-finite JSON number')


class BoundedModelProvider:
    """One instance owns a call budget. Failed exchanges consume calls; no retries."""
    def __init__(self, transport: ProposalTransport, budget=None):
        self.transport = transport
        self.budget = budget or ProposalBudget()
        self._calls = 0
        self._lock = threading.Lock()

    def propose(self, base, prompt, limit):
        if not self._lock.acquire(blocking=False):
            raise ProposalFailure('busy')
        try:
            return self._propose(base, prompt, limit)
        finally:
            self._lock.release()

    def _propose(self, base, prompt, limit):
        budget = self.budget
        if type(limit) is not int or not 1 <= limit <= budget.max_candidates or not isinstance(prompt, str):
            raise ProposalFailure('invalid_request')
        if len(prompt) > budget.max_request_bytes:
            raise ProposalFailure('request_limit')
        request_value = {'version': 1, 'snapshot': {'revision': base.revision, 'digest': base.digest,
                         'rows': [dict(row) for row in base.rows]}, 'prompt': prompt, 'limit': limit}
        request = bytearray()
        try:
            for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(request_value):
                request.extend(chunk.encode('utf-8'))
                if len(request) > budget.max_request_bytes:
                    raise ProposalFailure('request_limit')
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ProposalFailure('invalid_request') from None
        if self._calls >= budget.max_calls:
            raise ProposalFailure('call_limit')
        self._calls += 1
        started = time.monotonic()
        try:
            response = self.transport.exchange(bytes(request), timeout_seconds=budget.timeout_seconds,
                                               max_response_bytes=budget.max_response_bytes)
        except ProposalFailure:
            raise
        except TimeoutError:
            raise ProposalFailure('timeout') from None
        except Exception:
            raise ProposalFailure('transport_error') from None
        # Defense in depth for custom transports. This rejects a late result;
        # only a deadline-aware transport can stop a blocked exchange.
        if time.monotonic() - started >= budget.timeout_seconds:
            raise ProposalFailure('timeout')
        if type(response) is not bytes:
            raise ProposalFailure('invalid_response')
        if len(response) > budget.max_response_bytes:
            raise ProposalFailure('response_limit')
        try:
            value = json.loads(response.decode('utf-8'), object_pairs_hook=strict_object, parse_constant=reject_constant)
            if (type(value) is not dict or set(value) != {'version', 'request_digest', 'plans'}
                    or type(value['version']) is not int or value['version'] != 1
                    or value['request_digest'] != hashlib.sha256(request).hexdigest()
                    or type(value['plans']) is not list or len(value['plans']) > limit):
                raise ValueError('invalid response envelope')
            ids = set()
            for plan in value['plans']:
                if type(plan) is not dict or type(plan.get('patches')) is not list or len(plan['patches']) > budget.max_patches:
                    raise ValueError('invalid patch count')
                Catalog._validate_plan(plan)
                if plan['id'] in ids:
                    raise ValueError('duplicate candidate')
                ids.add(plan['id'])
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ProposalFailure('invalid_response') from None
        return value['plans']
