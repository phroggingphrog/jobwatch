"""Private, bounded Deep Agents execution using Jobwatch's local paid gateway.

The graph owns tool selection and execution. The chat adapter translates the
existing gateway's JSON tool-choice protocol to LangChain tool-call messages;
no provider client, credential fallback, or hosted tracing is used. Assessment
roles may opt into one validation correction. Every dispatch passes the same budget.
"""
from __future__ import annotations

import json
import traceback
import os
import time
from contextvars import Context
from dataclasses import dataclass, field
from typing import Any

from deepagents import (GeneralPurposeSubagentProfile, HarnessProfile,
                        create_deep_agent, register_harness_profile)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.globals import get_debug, get_verbose
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError
from langsmith import tracing_context
from pydantic import BaseModel, Field

from jobwatch import model_choice
from jobwatch.llm import BASE_URL, LLM, SafeLLMError
from pipeline.agentic.runtime import (MAX_ROLE_TURNS, JobBudget, RoleResult, RoleSpec,
                                     RuntimeErrorSafe, _json_bytes, _usage_total, validate_model_payload)


# This profile applies only to this adapter, never to other LangChain users.
# Whole job ads must not be silently summarized or offloaded into inaccessible
# files. Eight-turn roles do not require automatic conversation compaction.
register_harness_profile("jobwatch_gateway", HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    excluded_middleware=frozenset({"SummarizationMiddleware"}),
))


class _NoFilesystem(AgentMiddleware):
    """Replace Deep Agents' filesystem slot using its same-name override API."""

    @property
    def name(self) -> str:
        return "FilesystemMiddleware"


@dataclass
class _Execution:
    role: RoleSpec
    context: Any
    budget: JobBudget
    llm: Any
    max_turns: int
    max_output_tokens: int
    calls: int = 0
    trace: list[str] = field(default_factory=list)
    output: BaseModel | None = None
    failure_recorded: bool = False
    corrections: int = 0
    transient_retried: bool = False
    last_error: str = ""

    def fail(self, code: str) -> None:
        if not self.failure_recorded:
            self.failure_recorded = True
            self.budget.failed(code)

    def validate(self, name: str, arguments: Any) -> BaseModel:
        tool = next((t for t in self.role.tools if t.name == name), None)
        if tool is None:
            raise RuntimeErrorSafe("unknown_tool")
        invalid = False
        try:
            value = validate_model_payload(tool.arguments_model, arguments)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:4000]
            invalid = True
        if invalid:
            raise RuntimeErrorSafe("invalid_tool_arguments")
        return value


def _log_failure(execution, code, raw=None, exc_text=None):
    """Save the raw model reply, the exception text and the role/turn of a failed call (owner 2026-10-19)."""
    try:
        import traceback, datetime
        from jobwatch.apply.paths import data_dir
        ctx = execution.context if isinstance(execution.context, dict) else {}
        posting = (ctx.get("run_key") or {}).get("posting_id", "x") if isinstance(ctx.get("run_key"), dict) else "x"
        out = data_dir() / "agentic-failures"
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (out / f"{posting}-{execution.role.name}-{ts}.json").write_text(json.dumps(
            {"posting_id": posting, "role": execution.role.name, "model": execution.role.model,
             "turn": execution.calls, "error": code, "raw_reply": raw,
             "exception": exc_text if exc_text is not None else traceback.format_exc()},
            indent=1, default=str, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - logging never changes the result
        pass


def _messages_for_gateway(messages: list[BaseMessage]) -> list[dict]:
    """Keep a valid text-only transcript for the gateway JSON protocol."""
    output = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            if len(message.tool_calls) != 1:
                raise RuntimeErrorSafe("invalid_tool_call")
            call = message.tool_calls[0]
            content = json.dumps({"tool": call["name"], "arguments": call["args"]},
                                 ensure_ascii=False, allow_nan=False)
            role = "assistant"
        elif isinstance(message, ToolMessage):
            # The existing gateway uses JSON choices rather than native API
            # function calls, so an API `tool` message would be an orphan.
            content = json.dumps({"tool_result": message.name, "result": message.content},
                                 ensure_ascii=False, allow_nan=False)
            role = "user"
        else:
            role = {"human": "user", "system": "system", "ai": "assistant"}.get(message.type)
            content = message.content
        if role is None or type(content) is not str:
            raise RuntimeErrorSafe("invalid_request")
        output.append({"role": role, "content": content})
    return output


class GatewayChatModel(BaseChatModel):
    """LangChain chat model with exactly one counted local transport per call."""

    execution: Any = Field(exclude=True, repr=False)
    model_name: str = "jobwatch"

    @property
    def _llm_type(self) -> str:
        return "jobwatch_gateway"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "jobwatch_gateway", "ls_model_name": "jobwatch",
                "ls_model_type": "chat"}

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        expected = {tool.name for tool in self.execution.role.tools}
        names = [tool.get("name") if isinstance(tool, dict) else tool.name for tool in tools]
        if len(names) != len(expected) or set(names) != expected:
            raise RuntimeErrorSafe("invalid_registry")
        return self.bind()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        execution = self.execution
        try:
            return self._generate_once(messages, stop, run_manager, **kwargs)
        except RuntimeErrorSafe as exc:
            if exc.code == 'model_transient' and not execution.transient_retried:
                # A one-off provider error (HTTP 5xx / error body): the same request is simply sent once more, with
                # no correction text, because nothing was wrong with the answer. It is counted like any attempt.
                execution.transient_retried = True
                time.sleep(5)
                return self._generate_once(messages, stop, run_manager, **kwargs)
            eligible = exc.code in {'model_invalid_response', 'invalid_tool_call', 'invalid_tool_arguments'}
            if not eligible or execution.corrections >= execution.role.validation_corrections:
                raise
        # The rejected attempt is already settled and counted. Never pass its
        # unvalidated content back as trusted instructions or execute its tool.
        execution.corrections += 1
        correction = HumanMessage(content=(
            'The previous response failed JSON or tool-argument validation and was not executed. '
            'Correct it using the original evidence and the exact allowed tool schema. '
            'Return one valid JSON object with only tool and arguments; escape quotes inside strings. '
            'Do not invent missing facts. Inferred requirements cannot have citations, blockers, '
            'or high/critical importance.'))
        return self._generate_once(list(messages) + [correction], stop, run_manager, **kwargs)

    def _generate_once(self, messages, stop=None, run_manager=None, **kwargs):
        execution = self.execution
        budget = execution.budget
        budget.ensure_live()
        if execution.calls >= execution.max_turns:
            raise RuntimeErrorSafe("turn_limit")
        transcript = _messages_for_gateway(messages)
        reservation = budget.reserve(execution.role.name, _json_bytes(transcript) + 512,
                                     execution.max_output_tokens)
        budget.dispatched(reservation)
        execution.failure_recorded = False
        execution.calls += 1
        error = None
        failure_code = None
        usage = None
        message = None
        raw = None
        exc_text = None
        try:
            remaining = min(600 if execution.role.reasoning else 180, budget.remaining_seconds())  # high reasoning takes longer
            if remaining <= 0:
                raise RuntimeErrorSafe("deadline_exceeded")
            result = execution.llm.chat_once(
                execution.role.model, transcript, json_mode=True,
                max_tokens=execution.max_output_tokens, timeout=remaining,
                deadline=time.monotonic() + remaining, reasoning_effort=execution.role.reasoning)
            budget.ensure_live()
            payload = getattr(result, "data", result)
            raw = payload
            if (type(payload) is not dict or type(payload.get("tool")) is not str
                    or type(payload.get("arguments")) is not dict):
                raise RuntimeErrorSafe("invalid_tool_call")
            execution.validate(payload["tool"], payload["arguments"])
            message = AIMessage(content="", tool_calls=[{
                "name": payload["tool"], "args": payload["arguments"],
                "id": reservation, "type": "tool_call",
            }])
            usage = _usage_total(getattr(result, "usage", None))
        except SafeLLMError as exc:
            exc_text = traceback.format_exc() + str(getattr(exc, 'detail', '') or '')
            failure_code = exc.code if exc.code in {
                "auth", "invalid_response", "truncated_response", "deadline", "unavailable", "rate_limited", "transient"
            } else "unavailable"
            error = "model_" + failure_code
            if failure_code == "deadline":
                # The run's own clock cut the call off (not a provider outage): same outcome as running out of time
                # before the call, so it is not alerted as a model failure and the job simply waits for the next run.
                failure_code, error = None, "deadline_exceeded"
        except RuntimeErrorSafe as exc:
            error = exc.code
            exc_text = execution.last_error + "\n" + traceback.format_exc()
        except Exception:
            error = "invalid_model_response"
            exc_text = traceback.format_exc()
        # Unknown/malformed/late responses retain their entire reservation.
        budget.settle(reservation, usage)
        if error is not None:
            _log_failure(execution, error, raw, exc_text)
            execution.fail(failure_code or error)
            raise RuntimeErrorSafe(error)
        return ChatResult(generations=[ChatGeneration(message=message)])


class _RegistryBoundary(AgentMiddleware):
    """Verify the exact offered and executed registry, including injected tools."""

    def __init__(self, execution):
        self.execution = execution

    def wrap_model_call(self, request, handler):
        expected = {tool.name for tool in self.execution.role.tools}
        names = [tool.get("name") if isinstance(tool, dict) else tool.name for tool in request.tools]
        if len(names) != len(expected) or set(names) != expected:
            raise RuntimeErrorSafe("invalid_registry")
        return handler(request)

    def wrap_tool_call(self, request, handler):
        self.execution.budget.ensure_live()
        self.execution.validate(request.tool_call["name"], request.tool_call["args"])
        if self.execution.output is not None:
            raise RuntimeErrorSafe("terminal_already_selected")
        return handler(request)


def _tool_for_graph(tool, execution):
    terminal = tool.name in execution.role.terminal_tools

    def invoke(**arguments):
        execution.budget.ensure_live()
        args = execution.validate(tool.name, arguments)
        if terminal:
            execution.output = args
            output = {"status": "complete"}
        else:
            failed = False
            try:
                output = tool.handler(args, execution.context)
                if isinstance(output, BaseModel):
                    output = output.model_dump(mode="json")
                output = json.dumps(output, ensure_ascii=False, allow_nan=False)
            except Exception:
                _log_failure(execution, "tool_failed", arguments)
                failed = True
            if failed:
                raise RuntimeErrorSafe("tool_failed")
        execution.budget.ensure_live()
        execution.trace.append(tool.name)
        return output

    # A JSON-schema args_schema leaves validation to the explicit tuple-aware
    # boundary above; LangChain's Python-mode validation rejects JSON arrays.
    return StructuredTool(name=tool.name, description=f"Run the {tool.name} role operation.",
                          args_schema=tool.arguments_model.model_json_schema(),
                          func=invoke, return_direct=terminal)


def _invoke(execution):
    role = execution.role
    registry = [{"name": tool.name, "arguments_schema": tool.arguments_model.model_json_schema(),
                 "terminal": tool.name in role.terminal_tools} for tool in role.tools]
    system = role.system_prompt + '\nRespond only with {"tool": "allowed_name", "arguments": {...}}. Select a terminal tool to finish.'
    system += "\nAllowed tools and exact argument schemas (select one per JSON response): " + json.dumps(registry, sort_keys=True, ensure_ascii=False)
    model = GatewayChatModel(execution=execution, cache=False, verbose=False)
    graph = create_deep_agent(
        model=model, tools=[_tool_for_graph(tool, execution) for tool in role.tools],
        system_prompt=system, middleware=[_NoFilesystem(), _RegistryBoundary(execution)],
        subagents=[], skills=None, memory=None, checkpointer=None, store=None,
        debug=False, name="jobwatch_" + role.name,
    )
    # Explicitly disable environment-driven LangSmith tracing; an empty Context
    # also removes inherited callbacks, parent traces and runnable config.
    with tracing_context(enabled=False):
        graph.invoke({"messages": [HumanMessage(content=json.dumps(execution.context,
                     ensure_ascii=False, allow_nan=False))]},
                     config={"callbacks": [], "recursion_limit": 4 * execution.max_turns + 10})
    if execution.output is None:
        raise RuntimeErrorSafe("missing_terminal")
    return RoleResult(execution.output, tuple(execution.trace), execution.calls)


def run_deepagents_role(role, context, budget, llm, *, max_turns=MAX_ROLE_TURNS, max_output_tokens=12_000):
    error = None
    last_exc = None
    result = None
    execution = _Execution(role, context, budget, llm, MAX_ROLE_TURNS, max_output_tokens)
    try:
        if (type(max_turns) is not int or max_turns < 1
                or type(max_output_tokens) is not int or max_output_tokens < 1):
            raise RuntimeErrorSafe("invalid_request")
        execution.max_turns = min(MAX_ROLE_TURNS, max_turns)
        # Global debug logging happens outside model hooks. Refuse it before
        # any private graph inputs can be emitted; never mutate global settings.
        if get_debug() or get_verbose() or any(os.environ.get(key, "").lower() not in ("", "0", "false")
                for key in ("LANGCHAIN_TRACING", "LANGCHAIN_HANDLER")):
            raise RuntimeErrorSafe("tracing_not_allowed")
        # Clear inherited tracing without reverting worker tools to the default person.
        from jobwatch import users
        person = users.current()
        def private_invoke():
            with users.use(person):
                return _invoke(execution)
        result = Context().run(private_invoke)
    except RuntimeErrorSafe as exc:
        error = exc.code
        last_exc = traceback.format_exc()
    except GraphRecursionError:
        error = "turn_limit"
        last_exc = traceback.format_exc()
    except Exception:
        error = "invalid_model_response"
        last_exc = traceback.format_exc()
    if error is not None:
        if not execution.failure_recorded or error in {"turn_limit", "missing_terminal"}:
            _log_failure(execution, error, None, last_exc)
        # Raise outside handlers so raw framework/validation errors and private
        # exception payloads are absent even from exception.__context__.
        if error not in {"token_limit", "turn_limit", "deadline_exceeded", "batch_paused",
                         "checkpoint_unavailable", "failed_attempt_limit", "invalid_request",
                         "tracing_not_allowed", "model_not_allowed", "gateway_not_allowed"}:
            execution.fail(error)
        raise RuntimeErrorSafe(error) from None
    return result
