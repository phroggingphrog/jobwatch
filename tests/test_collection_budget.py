"""Deterministic deadline tests; no network or real alarm delivery."""
import pytest
from jobwatch.util import deadline
from jobwatch.util.http import Fetcher, Blocked


def test_budget_interrupts_retry_and_restores_alarm(monkeypatch):
    handlers, timers = {}, []
    monkeypatch.setattr(deadline.signal, 'getsignal', lambda _: 'previous')
    monkeypatch.setattr(deadline.signal, 'getitimer', lambda _: (0, 0))
    monkeypatch.setattr(deadline.signal, 'signal', lambda sig, handler: handlers.update(handler=handler))
    monkeypatch.setattr(deadline.signal, 'setitimer', lambda *args: timers.append(args))
    attempts = []
    with pytest.raises(deadline.CollectionDeadline):
        with deadline.collection_budget(15):
            try:
                attempts.append('fetch')
                handlers['handler'](None, None)
            except Exception:
                attempts.append('retry')
    assert attempts == ['fetch']
    assert timers[0][1] == 15
    assert timers[-1][1] == 0
    assert handlers['handler'] == 'previous'


def test_expired_budget_never_starts_transport():
    with pytest.raises(deadline.CollectionDeadline):
        with deadline.collection_budget(0):
            pytest.fail('expired collector started')


def test_fetch_deadline_is_monotonic(monkeypatch):
    from jobwatch.util import http
    clock = [10]
    monkeypatch.setattr(http.time, 'time', lambda: 100)
    fetcher = Fetcher(clock=lambda: clock[0], deadline=105)
    assert fetcher._remaining_timeout('https://example.invalid') == 5
    monkeypatch.setattr(http.time, 'time', lambda: -1000)
    clock[0] = 15
    with pytest.raises(Blocked, match='collection_deadline'):
        fetcher.request('GET', 'https://example.invalid')
    assert fetcher.requests_made == 0
    fetcher.close()
