"""A short remaining budget shrinks the requested answer instead of stopping the job with zero spend.

Before the change, reserve() added the requested maximum output to the prompt and raised when the sum did not fit,
so a job stopped with invocation_budget_exhausted at turn 0 although a smaller reply would have fitted."""
import pytest
from langgraph.errors import GraphRecursionError

from pipeline.agentic import deepagents_runtime as runtime
from pipeline.agentic.execution import Execution, use
from pipeline.agentic.runtime import BatchBudget, JobBudget, RuntimeErrorSafe, run_role
from test_deepagents_runtime import assert_safe_failure, budget, choice, role, transport_llm

def job(ceiling):
    return JobBudget("a" * 64, BatchBudget("b", clock=lambda: 1000), clock=lambda: 1000, token_ceiling=ceiling)

def test_job_ceiling_shrinks_the_requested_answer():
    b = job(5_000)
    rid = b.reserve('evaluator', 1_000, 12_000)
    assert b.requested_output(rid) == 4_000
    assert b.charged_tokens == 5_000

def test_invocation_ceiling_shrinks_the_requested_answer():
    b = job(100_000)
    with use(Execution('synthetic-clamp', token_ceiling=9_000)):
        rid = b.reserve('evaluator', 1_000, 12_000)
    assert b.requested_output(rid) == 8_000

def test_batch_ceiling_shrinks_the_requested_answer():
    b = JobBudget("a" * 64, BatchBudget("b", clock=lambda: 1000, token_ceiling=7_000), clock=lambda: 1000,
                  token_ceiling=100_000)
    rid = b.reserve('evaluator', 1_000, 12_000)
    assert b.requested_output(rid) == 6_000

def test_no_room_for_the_floor_still_stops_with_the_same_codes():
    b = job(1_500)
    with pytest.raises(RuntimeErrorSafe) as caught:
        b.reserve('evaluator', 1_000, 12_000)
    assert caught.value.code == 'token_limit'
    with use(Execution('synthetic-floor', token_ceiling=1_500)):
        with pytest.raises(RuntimeErrorSafe) as caught:
            b.reserve('evaluator', 1_000, 12_000)
    assert caught.value.code == 'invocation_budget_exhausted'
    assert b.charged_tokens == 0

def test_graph_asks_for_the_clamped_answer_and_completes():
    llm, seen = transport_llm([choice()])
    b = job(5_000)
    assert run_role(role(), {}, b, llm, max_output_tokens=12_000).output.answer == 'complete'
    reservation = b.snapshot().reservations[0]
    assert seen[0][1]['max_tokens'] == b.requested_output(reservation.reservation_id)
    assert seen[0][1]['max_tokens'] < 12_000

def test_graph_recursion_stop_reports_step_limit(monkeypatch):
    def exhausted(execution):
        raise GraphRecursionError('synthetic graph recursion')
    monkeypatch.setattr(runtime, '_invoke', exhausted)
    assert_safe_failure('step_limit', lambda: run_role(role(), {}, budget(), transport_llm([choice()])[0]))

def test_role_turn_cap_still_reports_turn_limit():
    assert_safe_failure('turn_limit', lambda: run_role(
        role(), {}, budget(), transport_llm([choice('read_evidence', source='cv')])[0], max_turns=1))
