from pipeline.agentic.runtime import JobBudget, BatchBudget
from pipeline.agentic.service import _digest_budget_usage


def paid(budget, count, tokens):
    ids = []
    for _ in range(count):
        rid = budget.reserve('evaluator', 100, 100)
        budget.dispatched(rid)
        budget.settle(rid, tokens)
        ids.append(rid)
    return ids


def test_expired_budget_does_not_subtract_historical_candidate_work():
    old = JobBudget('a' * 64, BatchBudget('old'))
    ids = paid(old, 2, 18)
    attribution = {'calls': 2, 'charged_tokens': 36, 'budget_reservations': ids}
    fresh = JobBudget('a' * 64, BatchBudget('new'))
    paid(fresh, 6, 30)
    calls, tokens = _digest_budget_usage(fresh, attribution)
    assert sum(fresh.snapshot().role_turns.values()) - calls == 6
    assert fresh.charged_tokens - tokens == 180
    # A live resumed budget still excludes exactly its digest operations.
    paid(old, 6, 30)
    calls, tokens = _digest_budget_usage(old, attribution)
    assert sum(old.snapshot().role_turns.values()) - calls == 6
    assert old.charged_tokens - tokens == 180
