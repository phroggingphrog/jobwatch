"""Behavioral tests for the bounded, model-selected runtime."""
from __future__ import annotations

from jobwatch import model_choice

from pydantic import BaseModel, ConfigDict
import pytest

from pipeline.agentic.runtime import BatchBudget, JobBudget, RoleSpec, Tool, run_role


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: int


class Terminal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str


class FakeModel:
    base_url = model_choice.SERVER_URL
    def __init__(self, choices):
        self.choices = iter(choices)
        self.seen = []

    def chat_once(self, model, messages, **kwargs):
        self.seen.append((model, messages, kwargs))
        return next(self.choices)


def budget(key="a" * 64, *, persistence=None):
    return JobBudget(run_key=key, batch=BatchBudget(batch_id="b", clock=lambda: 1000),
                     clock=lambda: 1000, deadline=1800, persist=persistence)


def test_model_selects_multiple_real_tools_until_typed_terminal():
    calls = []
    tools = (
        Tool("first", Args, lambda args, context: calls.append(("first", args.value, context)) or {"n": args.value + 1}),
        Tool("second", Args, lambda args, context: calls.append(("second", args.value, context)) or {"n": args.value * 2}),
        Tool("finish", Terminal, lambda args, context: args),
    )
    model = FakeModel([
        {"tool": "first", "arguments": {"value": 3}},
        {"tool": "second", "arguments": {"value": 4}},
        {"tool": "finish", "arguments": {"answer": "completed"}},
    ])
    b = budget()
    role = RoleSpec(name="evaluator", model="claude/haiku", tools=tools,
                    system_prompt="synthetic", terminal_tools=("finish",))
    result = run_role(role, {"private": "synthetic"}, b, model)
    assert result.output == Terminal(answer="completed")
    assert result.tool_trace == ("first", "second", "finish")
    assert calls == [("first", 3, {"private": "synthetic"}), ("second", 4, {"private": "synthetic"})]
    assert len(model.seen) == 3 and b.snapshot().role_turns["evaluator"] == 3
    assert all("synthetic" not in repr(event) for event in b.events)


def test_invalid_tool_arguments_fail_closed_without_calling_handler():
    called = []
    model = FakeModel([{"tool": "finish", "arguments": {"answer": "secret", "extra": "secret"}}])
    b = budget()
    role = RoleSpec(name="reviewer", model="claude/haiku", tools=(Tool("finish", Terminal, lambda a, c: called.append(a)),),
                    system_prompt="synthetic", terminal_tools=("finish",))
    with pytest.raises(Exception) as caught: run_role(role, {}, b, model)
    assert not called and "secret" not in str(caught.value) and caught.value.__context__ is None
    assert b.snapshot().failed_attempts == 1


def test_batch_budget_two_thread_race_never_oversubscribes():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    batch = BatchBudget(batch_id="batch", token_ceiling=100, clock=lambda: 1000)
    barrier = Barrier(2)
    def reserve(label):
        job = JobBudget(run_key=(label * 64)[:64], batch=batch, token_ceiling=60,
                        clock=lambda: 1000, deadline=1800)
        barrier.wait()
        try: return job.reserve("evaluator", 40, 20)
        except Exception: return None
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(reserve, ("a", "c")))
    assert sum(item is not None for item in outcomes) == 1 and batch.charged_tokens == 60


def test_batch_admission_caps_active_jobs_at_two():
    batch = BatchBudget(batch_id="b", clock=lambda: 1000)
    jobs = [JobBudget(run_key=(char * 64), batch=batch, clock=lambda: 1000, deadline=1800)
            for char in ("a", "b")]
    with pytest.raises(Exception):
        JobBudget(run_key="c" * 64, batch=batch, clock=lambda: 1000, deadline=1800)
    batch.release(jobs[0])
    assert JobBudget(run_key="c" * 64, batch=batch, clock=lambda: 1000, deadline=1800)


def test_checkpoint_restore_retains_unknown_dispatch_maximum_and_deadline():
    b = budget()
    rid = b.reserve("drafter", 20, 30); b.dispatched(rid)
    restored_batch = BatchBudget(batch_id="b", token_ceiling=2_000_000, clock=lambda: 1000)
    restored = JobBudget.restore(b.snapshot(), batch=restored_batch, clock=lambda: 1000)
    assert restored.charged_tokens == restored_batch.charged_tokens == 50
    assert restored.snapshot().job_deadline == 1800
    with pytest.raises(Exception): restored.ensure_live(now=1801)


def test_persistence_callback_runs_before_transport_and_failure_blocks_dispatch():
    events = []
    def callback(checkpoint, *, expected_revision, reservation_id, operation):
        events.append((operation, expected_revision, checkpoint.job_charged))
        if operation == "reserve": raise OSError("private callback detail")
    model = FakeModel([{"tool": "finish", "arguments": {"answer": "no"}}])
    role = RoleSpec(name="reviewer", model="claude/haiku", tools=(Tool("finish", Terminal, lambda a, c: a),),
                    system_prompt="synthetic", terminal_tools=("finish",))
    b = budget(persistence=callback)
    with pytest.raises(Exception) as caught: run_role(role, {}, b, model)
    assert events[0][0] == "reserve" and not model.seen
    assert "private callback detail" not in str(caught.value) and caught.value.__context__ is None
    assert b.charged_tokens > 0


def test_model_can_choose_different_tool_sequence():
    called = []
    tools = (Tool("alpha", Args, lambda a, c: called.append("alpha") or {"ok": True}),
             Tool("beta", Args, lambda a, c: called.append("beta") or {"ok": True}),
             Tool("finish", Terminal, lambda a, c: a))
    model = FakeModel([{"tool": "beta", "arguments": {"value": 8}},
                       {"tool": "finish", "arguments": {"answer": "done"}}])
    result = run_role(RoleSpec(name="researcher", model="claude/haiku", tools=tools,
                               system_prompt="synthetic", terminal_tools=("finish",)), {}, budget("c"*64), model)
    assert result.tool_trace == ("beta", "finish") and called == ["beta"]


def test_429_opens_batch_circuit_and_no_credential_retry():
    from jobwatch.llm import LLM, SafeLLMError
    calls = []
    llm = LLM(transport=lambda *args: calls.append(args) or (429, {"error": {"message": "secret"}}),
              keys=["synthetic-one", "synthetic-two"])
    with pytest.raises(SafeLLMError) as caught:
        llm.chat_once("claude/haiku", [{"role": "user", "content": "private"}], key_index=0)
    assert caught.value.code == "rate_limited" and len(calls) == 1
    b = budget(); b.failed("rate_limited")
    with pytest.raises(Exception): b.ensure_live()


def test_missing_boolean_or_oversized_usage_does_not_refund():
    from pipeline.agentic.runtime import _usage_total
    for usage in (None, {"prompt_tokens": True, "completion_tokens": 0},
                  {"prompt_tokens": 1000, "completion_tokens": 1000}):
        b = budget(); rid = b.reserve("drafter", 10, 5); b.dispatched(rid)
        b.settle(rid, _usage_total(usage))
        assert b.charged_tokens == b.batch.charged_tokens == 15


def test_transport_and_handler_exceptions_have_no_raw_context_or_private_payload():
    secret = "private-marker-7c"
    def handler(args, context): raise RuntimeError(secret)
    model = FakeModel([{"tool": "work", "arguments": {"value": 1}}])
    role = RoleSpec(name="researcher", model="claude/haiku",
                    tools=(Tool("work", Args, handler), Tool("finish", Terminal, lambda a,c: a)),
                    system_prompt="synthetic", terminal_tools=("finish",))
    with pytest.raises(Exception) as caught: run_role(role, {}, budget(), model)
    assert secret not in str(caught.value)
    assert caught.value.__context__ is None


def test_chat_once_without_explicit_test_key_never_loads_keyfiles():
    from jobwatch.llm import LLM, SafeLLMError
    calls = []
    llm = LLM(transport=lambda *args: calls.append(args) or (200, {}), keys=None)
    with pytest.raises(SafeLLMError) as caught:
        llm.chat_once("claude/haiku", [{"role": "user", "content": "synthetic"}])
    assert caught.value.code == "auth" and not calls


def test_authentication_failure_does_not_retry_keys_or_leak_response():
    from jobwatch.llm import LLM, SafeLLMError
    calls = []
    llm = LLM(transport=lambda *args: calls.append(args) or (401, {"error": {"message": "private"}}),
              keys=["fake-key-one", "fake-key-two"])
    with pytest.raises(SafeLLMError) as caught:
        llm.chat_once("claude/haiku", [{"role": "user", "content": "private"}], key_index=0)
    assert caught.value.code == "auth" and len(calls) == 1
    assert "private" not in str(caught.value) and caught.value.__context__ is None


@pytest.mark.parametrize("code", ["auth", "rate_limited"])
def test_gateway_failure_pauses_other_jobs_in_same_batch(code):
    b = budget()
    other = JobBudget(run_key="f" * 64, batch=b.batch, clock=lambda: 1000, deadline=1800)
    rid = b.reserve("evaluator", 10, 5)
    b.dispatched(rid)
    b.failed(code)
    with pytest.raises(Exception, match="batch_paused"):
        other.reserve("evaluator", 10, 5)
    assert b.batch.charged_tokens == 15


def test_a_call_cut_off_by_the_run_clock_is_a_deadline_not_an_outage():
    import time
    from jobwatch.llm import LLM, SafeLLMError
    def slow(url, headers, body, timeout):
        raise TimeoutError()
    llm = LLM(transport=slow, keys=['k'])
    try:
        llm.chat_once('openai/sol', [{'role': 'user', 'content': 'x'}], timeout=5, deadline=time.monotonic() + 5)
    except SafeLLMError as exc:
        assert exc.code == 'deadline'
    else:
        raise AssertionError('expected SafeLLMError')
