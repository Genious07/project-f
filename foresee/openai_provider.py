"""Opt-in OpenAI Responses adapter. No network access occurs on import."""
from dataclasses import asdict, dataclass
import json
import re
import sys
import threading

from .model_provider import BoundedModelProvider, ProcessTransport, ProposalBudget, ProposalFailure, strict_object, reject_constant

ERROR_CODES = frozenset({'missing_credentials', 'authentication_error', 'rate_limit', 'http_error',
    'transport_error', 'timeout', 'response_limit', 'invalid_response', 'input_token_limit',
    'usage_limit', 'model_refusal', 'incomplete_response'})


@dataclass(frozen=True)
class OpenAIConfig:
    model: str
    max_input_tokens: int
    max_output_tokens: int
    # Prices are caller-supplied upper bounds in micro-USD per million tokens.
    input_price_micro_usd_per_million: int
    output_price_micro_usd_per_million: int
    max_reserved_micro_usd: int

    def __post_init__(self):
        if not isinstance(self.model, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:-]{0,199}', self.model):
            raise ValueError('an explicit model ID is required')
        for name, maximum in [('max_input_tokens', 1_000_000), ('max_output_tokens', 100_000),
                              ('input_price_micro_usd_per_million', 10**12),
                              ('output_price_micro_usd_per_million', 10**12),
                              ('max_reserved_micro_usd', 10**12)]:
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= maximum:
                raise ValueError(f'{name} must be a positive integer at most {maximum}')

    @property
    def reservation_per_call(self):
        numerator = (self.max_input_tokens * self.input_price_micro_usd_per_million
                     + self.max_output_tokens * self.output_price_micro_usd_per_million)
        return (numerator + 999_999) // 1_000_000


class OpenAITransport:
    """In-memory reservation ledger; share this instance to share its budget."""
    def __init__(self, config: OpenAIConfig):
        self.config = config
        self._reserved = 0
        self._lock = threading.Lock()
        self._worker = ProcessTransport([sys.executable, '-m', 'foresee.openai_worker'])

    @property
    def reserved_micro_usd(self):
        with self._lock:
            return self._reserved

    def exchange(self, request, *, timeout_seconds, max_response_bytes):
        with self._lock:
            reservation = self.config.reservation_per_call
            if self._reserved + reservation > self.config.max_reserved_micro_usd:
                raise ProposalFailure('spend_limit')
            self._reserved += reservation
        # Never refund: timeout/disconnect can leave a server-side billed request.
        job = json.dumps({'config': asdict(self.config), 'request': request.decode('utf-8'),
                          'timeout_seconds': timeout_seconds}, separators=(',', ':')).encode()
        raw = self._worker.exchange(job, timeout_seconds=timeout_seconds,
                                    max_response_bytes=max_response_bytes + 4096)
        try:
            value = json.loads(raw.decode('utf-8'), object_pairs_hook=strict_object, parse_constant=reject_constant)
            if type(value) is not dict:
                raise ValueError('invalid worker envelope')
            if set(value) == {'error'} and value['error'] in ERROR_CODES:
                raise ProposalFailure(value['error'])
            if set(value) != {'proposal'} or type(value['proposal']) is not dict:
                raise ValueError('invalid worker result')
            result = json.dumps(value['proposal'], separators=(',', ':'), allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ProposalFailure('invalid_response') from None
        if len(result) > max_response_bytes:
            raise ProposalFailure('response_limit')
        return result


def openai_provider(config: OpenAIConfig, budget: ProposalBudget | None = None):
    """Explicit opt-in factory. OPENAI_API_KEY is read only inside the worker."""
    return BoundedModelProvider(OpenAITransport(config), budget)
