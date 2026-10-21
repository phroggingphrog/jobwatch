"""Real Deep Agents graph acceptance with deterministic local-gateway transport."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from pipeline.agentic.runtime import MAX_FAILED_ATTEMPTS, MAX_ROLE_TURNS
from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.globals import set_debug
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict

from jobwatch.llm import BASE_URL, LLM
from pipeline.agentic import deepagents_runtime as runtime
from pipeline.agentic.contracts import BudgetCheckpoint, RequirementSet, StrictFrozen
from pipeline.agentic.runtime import (BatchBudget, JobBudget, RoleSpec, RuntimeErrorSafe,
                                     Tool, run_role)


class ReadArgs(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source: str


class Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    answer: str
    citations: tuple[str, ...] = ()


def budget(*, token_ceiling=100_000, clock=lambda: 1000, persistence=None):
    return JobBudget("a" * 64, BatchBudget("b", clock=clock), clock=clock,
                     deadline=1800, token_ceiling=token_ceiling, persist=persistence)


def role(*, name="evaluator", handler=lambda args, context: {"text": "verified synthetic evidence"},
         model="claude/sonnet"):
    return RoleSpec(name=name, model=model, system_prompt="Synthetic private role",
                    tools=(Tool("read_evidence", ReadArgs, handler),
                           Tool("finish", Answer, lambda a, c: a)), terminal_tools=("finish",))


def choice(name="finish", **args):
    return {"tool": name, "arguments": args or {"answer": "complete"}}


def transport_llm(choices, *, usage=None):
    pending = iter(choices)
    seen = []

    def transport(url, headers, body, timeout):
        seen.append((url, body, timeout))
        payload = next(pending)
        if isinstance(payload, tuple):
            return payload
        return 200, {"choices": [{"message": {"content": json.dumps(payload)}}],
                     "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7}}

    return LLM(transport=transport, keys=["synthetic-key"]), seen


def test_backend_chat_dispatch_synthetic(tmp_path, monkeypatch):
    """One backend conversation through the real graph, with no network/live data."""
    import sqlite3
    from jobwatch import users, model_choice
    from pipeline.agentic.chat import dispatch
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role: 'claude/sonnet')
    choices = [
        choice('write_todos', todos=[{'content': 'Inspect then request preparation', 'status': 'in_progress'}]),
        choice('read_file', file_path='/skills/career-ops/SKILL.md'),
        choice('write_file', file_path='/memories/AGENTS.md', content='Synthetic preference: concise answers.'),
        choice('task', subagent_type='career-reader', description='Inspect synthetic job 7'),
        choice('inspect_job', posting_id=7),
        {'answer': 'Job 7 is missing; no invented facts.'},
        choice('run_career_ops', posting_id=7),
        {'answer': 'Deferred: agentic_disabled. No application submitted.'},
        choice('read_file', file_path='/memories/AGENTS.md'),
        {'answer': 'Your synthetic preference is concise answers.'},
        {'answer': 'Separate person; no previous messages.'},
    ]
    llm, seen = transport_llm(choices)
    llm.base_url = model_choice.SERVER_URL
    for person in ('fixture-a', 'fixture-b'):
        root = users.user_dir(person)
        root.mkdir(parents=True)
        with sqlite3.connect(root / 'jobwatch.db') as conn:
            conn.execute('CREATE TABLE postings(id INTEGER PRIMARY KEY)')
    cfg = {'agentic': {'enabled': False}}
    def turn(person='fixture-a', thread_id='conversation', **kwargs):
        return dispatch(person=person, thread_id=thread_id, config=cfg, llm=llm, **kwargs)
    first = turn(message='Inspect job 7 and prepare it')
    print('FIRST', json.dumps(first))
    assert first['status'] == 'interrupted'
    assert first['tools'] == ['write_todos', 'read_file', 'write_file', 'task']
    assert first['interrupts'][0]['action_requests'][0]['name'] == 'run_career_ops'
    assert_safe_failure('human_decision_required', lambda: turn(decisions=[{'type': 'approve'}]))
    resumed = turn(decisions=[{'type': 'approve'}], human_decision=True)
    print('RESUMED', json.dumps(resumed))
    assert resumed['status'] == 'complete' and 'agentic_disabled' in resumed['answer']
    memory = turn(thread_id='new-thread', message='Recall my preference')
    print('MEMORY', json.dumps(memory))
    assert 'Synthetic preference: concise answers.' in json.dumps(seen[-1])
    other = turn(person='fixture-b', message='Hello')
    print('ISOLATION', json.dumps(other))
    assert other['tools'] == [] and 'Synthetic preference' not in json.dumps(seen[-1])
    assert 'Inspect job 7' not in json.dumps(seen[-1])
    print('RESULT: planning, skill read, specialist, SQLite reopen/resume, approval, defer, cross-thread memory and person isolation exercised; synthetic transport only.')


def assert_safe_failure(code, run):
    with pytest.raises(RuntimeErrorSafe) as caught:
        run()
    assert caught.value.code == code
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    return caught.value


@pytest.mark.parametrize('bad', [choice(answer=123),
    (200, {'choices': [{'message': {'content': '{broken json'}}]})])
def test_one_opted_in_validation_correction_uses_same_budget(bad):
    llm,seen=transport_llm([bad,choice(answer='corrected')])
    b=budget()
    result=run_role(replace(role(),validation_corrections=1),{},b,llm)
    reservations=b.snapshot().reservations
    assert result.output.answer=='corrected' and result.turns==2
    assert len(seen)==2 and b.failed_attempts==1 and len(reservations)==2
    assert reservations[0].actual_usage is None
    assert reservations[1].actual_usage==18
    assert 'correct' in seen[1][1]['messages'][-1]['content'].lower()


def test_validation_correction_stops_after_second_invalid_response():
    llm,seen=transport_llm([choice(answer=123)]*3)
    b=budget()
    assert_safe_failure('invalid_tool_arguments',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==2 and b.failed_attempts==2
    assert all(r.state=='settled' and r.actual_usage is None for r in b.snapshot().reservations)


@pytest.mark.parametrize('bad,code', [(choice('execute'),'unknown_tool'),
    ((401,{'error':{}}),'model_auth'),((429,{'error':{}}),'model_rate_limited')])
def test_opted_in_correction_never_retries_nonvalidation_failures(bad,code):
    llm,seen=transport_llm([bad,choice()]);b=budget()
    assert_safe_failure(code,lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1 and b.failed_attempts==1


def test_one_transient_provider_error_is_retried_once(monkeypatch):
    monkeypatch.setattr('pipeline.agentic.deepagents_runtime.time.sleep',lambda s:None)
    llm,seen=transport_llm([(500,{'error':{}}),choice(),choice()]);b=budget()
    run_role(role(),{},b,llm)
    assert len(seen)==2 and b.failed_attempts==1
    llm,seen=transport_llm([(500,{'error':{}})]*3);b=budget()
    assert_safe_failure('model_transient',lambda:run_role(role(),{},b,llm))
    assert len(seen)==2 and b.failed_attempts==2


def test_validation_correction_cannot_renew_turn_limit():
    llm,seen=transport_llm([choice(answer=123),choice()]);b=budget()
    assert_safe_failure('turn_limit',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm,max_turns=1))
    assert len(seen)==1 and b.failed_attempts==1


def test_validation_correction_retains_failed_reservation_when_budget_runs_out():
    llm,seen=transport_llm([choice(answer=123),choice()]);b=budget(token_ceiling=20_000)
    assert_safe_failure('token_limit',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1 and b.failed_attempts==1
    assert len(b.snapshot().reservations)==1 and b.snapshot().reservations[0].actual_usage is None


def test_validation_correction_cannot_renew_deadline():
    now=[1000]
    def persist(checkpoint, **kwargs):
        if any(r.state=='settled' for r in checkpoint.reservations):now[0]=1900
    b=budget(clock=lambda:now[0],persistence=persist)
    llm,seen=transport_llm([choice(answer=123),choice()])
    assert_safe_failure('deadline_exceeded',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1


def test_invalid_tool_is_never_executed_during_correction():
    invoked=[]
    spec=replace(role(handler=lambda *args:invoked.append(True)),validation_corrections=1)
    llm,seen=transport_llm([choice('read_evidence',source=123),choice()])
    result=run_role(spec,{},budget(),llm)
    assert not invoked and result.tool_trace==('finish',) and len(seen)==2


def test_validation_correction_cannot_reset_existing_failure_limit():
    b=budget()
    for _ in range(MAX_FAILED_ATTEMPTS-1):b.failed('invalid_tool_arguments')
    llm,seen=transport_llm([choice(answer=123),choice()])
    assert_safe_failure('failed_attempt_limit',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1 and b.failed_attempts==MAX_FAILED_ATTEMPTS


def test_correction_is_once_per_role_not_once_per_tool():
    llm,seen=transport_llm([choice('read_evidence',source=123),
        choice('read_evidence',source='verified'),choice(answer=123),choice()])
    b=budget()
    assert_safe_failure('invalid_tool_arguments',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==3 and b.failed_attempts==2


def test_correction_does_not_retry_a_clipped_response():
    clipped=(200,{'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})
    llm,seen=transport_llm([clipped,choice()]);b=budget()
    assert_safe_failure('model_truncated_response',lambda:run_role(replace(role(),validation_corrections=1),{},b,llm))
    assert len(seen)==1


@pytest.mark.parametrize('value',[-1,2,True,'1'])
def test_correction_limit_configuration_is_strict(value):
    with pytest.raises(ValueError,match='invalid_validation_corrections'):
        replace(role(),validation_corrections=value)


@pytest.mark.parametrize("remaining,expected", [(800, 180), (35, 35)])
def test_structured_response_timeout_preserves_job_deadline(remaining, expected):
    llm, seen = transport_llm([choice(answer="supported")])
    b = budget(clock=lambda: 1800 - remaining)
    run_role(role(), {}, b, llm)
    assert seen[0][2] == pytest.approx(expected, abs=0.1)


def test_actual_deepagent_compiles_invokes_and_selects_native_tools(monkeypatch):
    built = []
    original = runtime.create_deep_agent

    def build(**kwargs):
        graph = original(**kwargs)
        built.append({"kwargs": kwargs, "invoked": False})

        def invoke(*args, **invoke_kwargs):
            built[-1]["invoked"] = True
            return graph.invoke(*args, **invoke_kwargs)

        return SimpleNamespace(invoke=invoke)

    monkeypatch.setattr(runtime, "create_deep_agent", build)
    calls = []
    llm, seen = transport_llm([choice("read_evidence", source="cv"),
                              choice(answer="supported", citations=["cv"])])
    b = budget()
    result = run_role(role(handler=lambda a, c: calls.append(a.source) or {"verified": "synthetic"}),
                      {"job": "synthetic"}, b, llm)
    assert len(built) == 1 and built[0]["invoked"]
    assert isinstance(built[0]["kwargs"]["model"], BaseChatModel)
    assert [t.name for t in built[0]["kwargs"]["tools"]] == ["read_evidence", "finish"]
    assert built[0]["kwargs"]["tools"][-1].return_direct is True
    assert built[0]["kwargs"]["subagents"] == []
    assert result.output == Answer(answer="supported", citations=("cv",))
    assert result.tool_trace == ("read_evidence", "finish") and calls == ["cv"]
    assert result.turns == len(seen) == b.snapshot().role_turns["evaluator"] == 2
    assert b.charged_tokens == 36
    assert all(r.state == "settled" for r in b.snapshot().reservations)
    assert all(url == BASE_URL + "/chat/completions" for url, _, _ in seen)
    assert '"tool_result": "read_evidence"' in seen[1][1]["messages"][-1]["content"]
    schema_text = seen[0][1]["messages"][0]["content"].split("JSON response): ", 1)[1]
    assert [entry["name"] for entry in json.loads(schema_text)] == ["read_evidence", "finish"]


def test_nested_strict_contract_tuple_fields_accept_json_without_scalar_coercion():
    class NestedTerminal(StrictFrozen):
        extracted: RequirementSet
        nested: tuple[tuple[str, ...], ...]

    payload = {"extracted": {"ad_hash": "a" * 64, "requirements": []},
               "nested": [["cv"]]}
    spec = RoleSpec(name="jd_requirements", model="claude/sonnet", system_prompt="Synthetic",
                    tools=(Tool("finish", NestedTerminal, lambda a, c: a),), terminal_tools=("finish",))
    llm, seen = transport_llm([choice(**payload)])
    result = run_role(spec, {}, budget(), llm)
    assert result.output.extracted.requirements == () and result.output.nested == (("cv",),)
    payload["nested"] = [[42]]
    invalid_llm, _ = transport_llm([choice(**payload)])
    assert_safe_failure("invalid_tool_arguments", lambda: run_role(spec, {}, budget(), invalid_llm))


@pytest.mark.parametrize("tool_name", ["execute", "read_file", "write_file", "edit_file", "delete",
                                        "ls", "glob", "grep", "task", "write_todos", "unknown"])
def test_default_and_unknown_tools_fail_before_execution(tool_name):
    llm, seen = transport_llm([choice(tool_name, private="never execute")])
    b = budget()
    assert_safe_failure("unknown_tool", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == 1 and b.failed_attempts == 1
    assert b.snapshot().reservations[0].actual_usage is None


def test_framework_injected_tool_cannot_reach_model_or_execute(monkeypatch):
    original = runtime.create_deep_agent
    called = []

    @tool
    def execute(command: str) -> str:
        """A forbidden injected shell tool."""
        called.append(command)
        return "forbidden"

    class InjectTool(AgentMiddleware):
        tools = [execute]

    def build(**kwargs):
        kwargs["middleware"].append(InjectTool())
        return original(**kwargs)

    monkeypatch.setattr(runtime, "create_deep_agent", build)
    llm, seen = transport_llm([choice()])
    assert_safe_failure("invalid_registry", lambda: run_role(role(), {}, budget(), llm))
    assert not called and not seen


def test_framework_extra_model_call_is_reserved_and_respects_total_turn_limit(monkeypatch):
    original = runtime.create_deep_agent

    class ExtraModelCall(AgentMiddleware):
        def before_agent(self, state, runtime):
            self.model.invoke([HumanMessage(content="framework maintenance")])

    def build(**kwargs):
        middleware = ExtraModelCall()
        middleware.model = kwargs["model"]
        kwargs["middleware"].append(middleware)
        return original(**kwargs)

    monkeypatch.setattr(runtime, "create_deep_agent", build)
    llm, seen = transport_llm([choice(), choice()])
    b = budget()
    assert_safe_failure("turn_limit", lambda: run_role(role(), {}, b, llm, max_turns=1))
    assert len(seen) == len(b.snapshot().reservations) == 1
    assert b.charged_tokens == 18 and b.snapshot().reservations[0].state == "settled"


@pytest.mark.parametrize("payload,code", [
    ({"answer": "prose completion is insufficient"}, "invalid_tool_call"),
    ({"tool": "finish", "arguments": {"answer": 1}}, "invalid_tool_arguments"),
    ({"tool": "finish", "arguments": {"answer": "private", "extra": "private"}}, "invalid_tool_arguments"),
])
def test_nonterminal_or_wrong_schema_cannot_become_result(payload, code):
    llm, seen = transport_llm([payload])
    assert_safe_failure(code, lambda: run_role(role(), {}, budget(), llm))
    assert len(seen) == 1


def test_exhausted_turns_and_tokens_never_make_an_extra_transport():
    llm, seen = transport_llm([choice("read_evidence", source="cv")] * (MAX_ROLE_TURNS + 1))
    b = budget()
    assert_safe_failure("turn_limit", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == MAX_ROLE_TURNS and b.snapshot().role_turns["evaluator"] == MAX_ROLE_TURNS
    tiny_llm, tiny_seen = transport_llm([choice()])
    assert_safe_failure("token_limit", lambda: run_role(role(), {}, budget(token_ceiling=10), tiny_llm))
    assert not tiny_seen


def test_environment_tracing_and_inherited_callbacks_are_isolated(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    observed = []

    class InheritedCallback(BaseCallbackHandler):
        def on_chain_start(self, *args, **kwargs):
            observed.append("private data escaped")

    def forbidden(*args, **kwargs):
        observed.append("tracer created")
        raise AssertionError("external trace created")

    from langchain_core.tracers.langchain import LangChainTracer
    monkeypatch.setattr(LangChainTracer, "__init__", forbidden)
    token = var_child_runnable_config.set({"callbacks": [InheritedCallback()]})
    try:
        llm, seen = transport_llm([choice()])
        assert run_role(role(), {"private": "synthetic"}, budget(), llm).output.answer == "complete"
    finally:
        var_child_runnable_config.reset(token)
    assert not observed and len(seen) == 1


def test_global_debug_and_legacy_tracing_fail_before_private_input(monkeypatch, capsys):
    llm, seen = transport_llm([choice()])
    set_debug(True)
    try:
        assert_safe_failure("tracing_not_allowed", lambda: run_role(role(), {"private": "synthetic"}, budget(), llm))
    finally:
        set_debug(False)
    monkeypatch.setenv("LANGCHAIN_TRACING", "true")
    assert_safe_failure("tracing_not_allowed", lambda: run_role(role(), {}, budget(), llm))
    assert not seen and "synthetic" not in capsys.readouterr().out


def test_429_settles_reservation_and_opens_shared_circuit_without_retry():
    llm, seen = transport_llm([(429, {"error": {"message": "private provider details"}})])
    b = budget()
    assert_safe_failure("model_rate_limited", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == 1 and b.failed_attempts == 1
    assert b.snapshot().reservations[0].state == "settled"
    assert_safe_failure("batch_paused", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == 1


def test_third_failed_call_still_settles_before_failed_attempt_limit(monkeypatch):
    monkeypatch.setattr("pipeline.agentic.deepagents_runtime.time.sleep", lambda s: None)
    llm, seen = transport_llm([(500, {"error": {"message": "private"}})] * MAX_FAILED_ATTEMPTS)
    b = budget()
    for _ in range(MAX_FAILED_ATTEMPTS // 2 - 1):  # each run makes the call and one transient retry
        assert_safe_failure("model_transient", lambda: run_role(role(), {}, b, llm))
    assert_safe_failure("failed_attempt_limit", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == MAX_FAILED_ATTEMPTS and all(r.state == "settled" for r in b.snapshot().reservations)
    assert_safe_failure("failed_attempt_limit", lambda: run_role(role(), {}, b, llm))
    assert len(seen) == MAX_FAILED_ATTEMPTS


def test_reservation_and_dispatch_are_durable_before_each_transport():
    events = []

    def persist(checkpoint, *, expected_revision, reservation_id, operation):
        events.append(operation)

    llm, seen = transport_llm([choice("read_evidence", source="cv"), choice()])
    transport = llm.transport

    def record_transport(*args):
        assert events[-2:] == ["reserve", "dispatched"]
        events.append("transport")
        return transport(*args)

    llm.transport = record_transport
    run_role(role(), {}, budget(persistence=persist), llm)
    assert events == ["reserve", "dispatched", "transport", "settle"] * 2


def test_late_gateway_result_is_charged_and_never_executes_tool():
    clock = [1000]
    called = []
    llm, seen = transport_llm([choice("read_evidence", source="cv")])
    transport = llm.transport

    def late_transport(*args):
        result = transport(*args)
        clock[0] = 1801
        return result

    llm.transport = late_transport
    b = budget(clock=lambda: clock[0])
    assert_safe_failure("deadline_exceeded", lambda: run_role(
        role(handler=lambda a, c: called.append(a)), {}, b, llm))
    assert len(seen) == 1 and not called
    assert b.snapshot().reservations[0].actual_usage is None
    assert b.snapshot().reservations[0].state == "settled"


@pytest.mark.parametrize("kwargs", [{"max_turns": 0}, {"max_turns": "eight"},
                                    {"max_output_tokens": True}, {"max_output_tokens": 0}])
def test_invalid_limits_fail_before_transport(kwargs):
    llm, seen = transport_llm([choice()])
    assert_safe_failure("invalid_request", lambda: run_role(role(), {}, budget(), llm, **kwargs))
    assert not seen


@pytest.mark.parametrize("name", ["candidate_evaluator", "prefill_answers"])
def test_additional_roles_roundtrip_budget_checkpoint(name):
    llm, seen = transport_llm([choice()])
    b = budget()
    run_role(role(name=name), {}, b, llm)
    checkpoint = BudgetCheckpoint.model_validate(b.snapshot().model_dump())
    restored = JobBudget.restore(checkpoint, batch=BatchBudget("b", clock=lambda: 1000), clock=lambda: 1000)
    assert restored.snapshot().role_turns[name] == 1 and restored.charged_tokens == 18


def test_upstream_overload_503_waits_and_retries_same_call(monkeypatch):
    import jobwatch.llm as L
    monkeypatch.setattr(L.time, 'sleep', lambda s: None)
    busy = (503, {'error': {'message': 'auth_unavailable: no auth available (last upstream error: server_is_overloaded)'}})
    llm, seen = transport_llm([busy, choice()]); b = budget()
    run_role(role(), {}, b, llm)
    assert len(seen) == 2 and b.failed_attempts == 0


def test_upstream_overload_never_falls_back_to_claude(monkeypatch):  # owner 2026-10-19: no Claude subscription
    import jobwatch.llm as L
    monkeypatch.setattr(L.time, 'sleep', lambda s: None)
    busy = (503, {'error': {'message': 'server_is_overloaded'}})
    models = []
    llm, seen = transport_llm([busy, busy, busy, choice()]); b = budget()
    inner = llm.transport
    llm.transport = lambda url, h, body, t: (models.append(body['model']), inner(url, h, body, t))[1]
    try:
        run_role(replace(role(), model='openai/sol'), {}, b, llm)
    except Exception:
        pass
    assert models and all(m == 'openai/sol' for m in models)
