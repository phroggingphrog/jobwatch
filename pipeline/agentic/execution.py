"""Shared invocation identity, cancellation and payload-free local activity."""
from __future__ import annotations

import contextlib
import contextvars
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from jobwatch import model_choice
from pipeline.agentic.runtime import RuntimeErrorSafe, _usage_total

_CURRENT = contextvars.ContextVar('jobwatch_execution', default=None)
_PAID = re.compile(r'^(?:openai|claude|google)/[A-Za-z0-9._-]+$')
QWEN_EMBEDDING_MODEL = 'openrouter/qwen/qwen3-embedding-8b'


def embedding_model_allowed(model):
    """Owner-approved paid Qwen exception applies only to embedding operations."""
    return (type(model) is str and (bool(_PAID.fullmatch(model)) or model == QWEN_EMBEDDING_MODEL)
            and not any(x in model.lower() for x in ('free', 'stealth', 'opus', 'astra')))


def require_route(llm, model, *, embedding=False):
    base_url = getattr(llm, 'base_url', None)
    if type(base_url) is not str:
        raise RuntimeErrorSafe('gateway_not_allowed')
    url = urlparse(base_url)
    if (url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or base_url.rstrip('/') != model_choice.SERVER_URL.rstrip('/')):
        raise RuntimeErrorSafe('gateway_not_allowed')
    allowed = embedding_model_allowed(model) if embedding else (
        type(model) is str and model_choice.refusal(model) is None
        and model != QWEN_EMBEDDING_MODEL
        and not any(x in model.lower() for x in ('free', 'stealth', 'opus', 'astra')))
    if not allowed:
        raise RuntimeErrorSafe('model_not_allowed')


@dataclass
class Execution:
    run_id: str
    seconds: float = 900
    token_ceiling: int = 250_000
    max_calls: int = 64
    emit: object = None
    cancelled: object = None
    deadline: float = field(init=False)
    calls: int = 0
    charged_tokens: int = 0
    token_limit_reason: str = 'run_budget'
    actual_tokens: int = 0
    unknown_usage_calls: int = 0
    approvals: dict = field(default_factory=dict)
    human_texts: tuple = ()          # what the person wrote this turn (server-set); profile tools may record only these words
    parse_starts: int = 0
    outcomes: list = field(default_factory=list)
    deliverables: list = field(default_factory=list)
    lock: object = field(default_factory=threading.RLock)

    def __post_init__(self):
        self.deadline = time.monotonic() + self.seconds

    def check(self):
        if self.cancelled and self.cancelled():
            raise RuntimeErrorSafe('cancelled')
        if time.monotonic() >= self.deadline:
            raise RuntimeErrorSafe('deadline_exceeded')

    def event(self, kind, **data):
        if self.emit:
            self.emit(kind, data)

    def reserve(self, model, role, prompt_size, output_tokens):
        with self.lock:
            self.check()
            reserve = prompt_size + output_tokens
            if self.calls >= self.max_calls:
                raise RuntimeErrorSafe('invocation_call_limit')
            if self.charged_tokens + reserve > self.token_ceiling:
                raise RuntimeErrorSafe('invocation_budget_exhausted')
            self.calls += 1
            self.charged_tokens += reserve
            self.event('model_started', model=model, role=role, attempt=self.calls,
                       reserved_tokens=reserve)
            return reserve

    def settle(self, reserve, usage):
        with self.lock:
            actual = _usage_total(usage)
            if actual is None:
                self.unknown_usage_calls += 1
            else:
                self.actual_tokens += actual
                self.charged_tokens += max(0, actual) - reserve
            self.event('model_finished', actual_tokens=actual,
                       charged_tokens=self.charged_tokens, reserved_tokens=reserve)
            if self.charged_tokens > self.token_ceiling:
                raise RuntimeErrorSafe('invocation_budget_exhausted')

    def usage(self):
        return dict(model_calls=self.calls, charged_tokens=self.charged_tokens,
                    actual_tokens=self.actual_tokens, unknown_usage_calls=self.unknown_usage_calls)


def current():
    return _CURRENT.get()


@contextlib.contextmanager
def use(execution):
    token = _CURRENT.set(execution)
    try:
        yield execution
    finally:
        _CURRENT.reset(token)
