"""Cooperative, monotonic collection budget; never interrupts writes."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_current = ContextVar('collection_budget', default=None)


class CollectionDeadline(RuntimeError):
    """The current source exhausted the collection budget."""


class Budget:
    def __init__(self, deadline, clock=time.monotonic, sleep=time.sleep):
        self.deadline, self.clock, self.sleeper = deadline, clock, sleep
        self.exhausted = False

    def remaining(self):
        left = self.deadline - self.clock()
        if left <= 0:
            self.exhausted = True
            raise CollectionDeadline('collection_deadline')
        return left

    def pause(self, seconds):
        self.sleeper(min(seconds, self.remaining()))
        self.remaining()


@contextmanager
def collection_budget(budget):
    token = _current.set(budget)
    try:
        yield
    finally:
        _current.reset(token)


def pause(seconds):
    budget = _current.get()
    if budget is None:
        time.sleep(seconds)
    else:
        budget.pause(seconds)


def timeout(seconds):
    budget = _current.get()
    return seconds if budget is None else min(seconds, budget.remaining())
