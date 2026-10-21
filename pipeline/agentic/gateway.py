"""Shared JSON gateway transport for conversation and bounded role models."""
from __future__ import annotations

import json
import time

from langchain_core.messages import AIMessage, ToolMessage

from pipeline.agentic import execution
from pipeline.agentic.runtime import RuntimeErrorSafe, _json_bytes


def messages_for_gateway(messages):
    result = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            if len(message.tool_calls) != 1:
                raise RuntimeErrorSafe('invalid_tool_call')
            call = message.tool_calls[0]
            role, content = 'assistant', json.dumps({'tool': call['name'], 'arguments': call['args']}, allow_nan=False)
        elif isinstance(message, ToolMessage):
            role, content = 'user', json.dumps({'tool_result': message.name, 'result': message.content}, allow_nan=False)
        else:
            role = {'human': 'user', 'system': 'system', 'ai': 'assistant'}.get(message.type)
            content = message.content
            if isinstance(content, list):
                if any(type(b) is not dict or b.get('type') != 'text' or type(b.get('text')) is not str for b in content):
                    raise RuntimeErrorSafe('unsupported_content')
                content = '\n'.join(b['text'] for b in content)
        if role is None or type(content) is not str:
            raise RuntimeErrorSafe('invalid_request')
        result.append({'role': role, 'content': content})
    return result


def call(llm, model, transcript, *, role, max_tokens, timeout, deadline, reasoning_effort=None):
    execution.require_route(llm, model)
    scope = execution.current()
    reservation = None
    if scope:
        reservation = scope.reserve(model, role, _json_bytes(transcript), max_tokens)
        deadline = min(deadline, scope.deadline)
        timeout = min(timeout, max(0, deadline - time.monotonic()))
    result = None
    try:
        result = llm.chat_once(model, transcript, json_mode=True, max_tokens=max_tokens,
            timeout=timeout, deadline=deadline, reasoning_effort=reasoning_effort)
        return result
    finally:
        if scope:
            scope.settle(reservation, getattr(result, 'usage', None))
            scope.check()
