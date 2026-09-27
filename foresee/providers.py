"""Small provider contracts for the supported local execution domain."""
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from .catalog import Snapshot, fixture_plans


class ProviderError(RuntimeError):
    pass


class ModelProvider(Protocol):
    def propose(self, base: Snapshot, prompt: str, limit: int) -> list[dict]: ...


class ResourceProvider(Protocol):
    path: Path
    @property
    def target_id(self) -> str: ...
    def snapshot(self) -> Snapshot: ...
    def commit(self, selection: dict, program_digest: str, *, operation_id=None, fault_hook=None) -> dict: ...


class JournalProvider(Protocol):
    path: Path
    def start(self) -> str: ...
    def prepare(self, run_id, catalog, program_digest, payload) -> str: ...
    def record(self, operation_id, outcome) -> None: ...
    def complete(self, run_id, outcome) -> None: ...


class ClockProvider(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self):
        import time
        return time.time()


class FixedClock:
    def __init__(self, value=0):
        self.value = value

    def now(self):
        return self.value


class FixtureProvider:
    def __init__(self, generator=None):
        self.generator = generator or fixture_plans

    def propose(self, base, prompt, limit):
        return self.generator(base, limit)


class CandidateProvider:
    def __init__(self, plans):
        self.plans = deepcopy(plans)

    def propose(self, base, prompt, limit):
        return deepcopy(self.plans[:limit])
