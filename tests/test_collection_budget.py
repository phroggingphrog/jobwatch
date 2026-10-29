import pytest
from jobwatch.util.deadline import Budget, CollectionDeadline, collection_budget, pause
from jobwatch.util.http import Fetcher


class Clock:
    now = 0.0
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


def test_retry_pause_clamped():
    clock = Clock()
    budget = Budget(0.25, clock, clock.sleep)
    with collection_budget(budget), pytest.raises(CollectionDeadline):
        pause(5)
    assert clock.now == 0.25
    assert budget.exhausted


def test_slow_transport_timeout_clamped():
    clock = Clock()
    fetcher = Fetcher(deadline=0.25, clock=clock, sleep=clock.sleep)
    def request(*args, timeout, **kwargs):
        clock.sleep(timeout)
        return type('Response', (), {'status_code': 200})()
    fetcher.session.request = request
    with pytest.raises(CollectionDeadline):
        fetcher.request('GET', 'https://synthetic.invalid/')
    assert clock.now == 0.25
    assert fetcher.budget.exhausted
