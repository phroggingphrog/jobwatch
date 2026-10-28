"""Shared JSON gateway transport for conversation and bounded role models."""
from __future__ import annotations

import json
import time

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.embeddings import Embeddings

from pipeline.agentic import execution
from pipeline.agentic.runtime import RuntimeErrorSafe, _json_bytes

QUERY_INSTRUCTIONS = {
    'requirement': 'Given a job requirement, retrieve candidate career evidence demonstrating relevant skills or experience.',
    'field_from_evidence': "Given a statement of a person's work experience or skills, retrieve the occupations whose duties and required skills it relates to.",
}


class PaidGatewayEmbeddings(Embeddings):
    """LangChain interface with the same private route, identity and job budgets."""

    def __init__(self, llm, model, budget):
        execution.require_route(llm, model, embedding=True)
        self.llm, self.model, self.budget = llm, model, budget

    def embed_query(self, text):
        return self.embed_queries([text])[0]

    def embed_queries(self, texts, kind='requirement'):
        if kind not in QUERY_INSTRUCTIONS:
            raise RuntimeErrorSafe('invalid_request')
        # Qwen's official retrieval format: instruct queries, leave documents plain.
        if self.model == execution.QWEN_EMBEDDING_MODEL:
            instruction = QUERY_INSTRUCTIONS[kind]
            texts = [f'Instruct: {instruction}\nQuery:{text}' for text in texts]
        return self.embed_documents(texts)

    def embed_documents(self, texts):
        # Bound batches without truncating source text. No vectors leave this job.
        batches, batch, size = [], [], 0
        for text in texts:
            length = len(text.encode('utf-8'))
            if batch and (len(batch) >= 32 or size + length > 48_000):
                batches.append(batch)
                batch, size = [], 0
            batch.append(text)
            size += length
        if batch:
            batches.append(batch)
        return [vector for part in batches for vector in self._embed(part)]

    def _embed(self, texts):
        from jobwatch.llm import SafeLLMError
        from pipeline.agentic.runtime import _usage_total
        execution.require_route(self.llm, self.model, embedding=True)
        self.budget.ensure_live()
        prompt_size = _json_bytes({'model': self.model, 'input': texts})
        reservation = self.budget.reserve('evaluator', prompt_size, 1)
        scope, scope_reservation, result = execution.current(), None, None
        try:
            deadline = time.monotonic() + self.budget.remaining_seconds()
            if scope:
                scope_reservation = scope.reserve(self.model, 'evidence_embeddings', prompt_size, 1)
                deadline = min(deadline, scope.deadline)
            self.budget.dispatched(reservation)
            result = self.llm.embed_once(self.model, texts, timeout=min(30, max(0, deadline - time.monotonic())), deadline=deadline)
            return result.data
        except SafeLLMError as exc:
            self.budget.failed(exc.code)
            raise RuntimeErrorSafe('embedding_' + exc.code) from None
        finally:
            usage = getattr(result, 'usage', None)
            try:
                self.budget.settle(reservation, _usage_total(usage))
            finally:
                if scope_reservation is not None:
                    scope.settle(scope_reservation, usage)
                    scope.check()
            self.budget.ensure_live()




class LocalOllamaEmbeddings(Embeddings):
    """Local-only Ollama embeddings; requests are pinned to loopback."""

    URL = 'http://127.0.0.1:11434/api/embed'

    def __init__(self, model, budget, *, session_factory=None):
        if execution.ollama_embedding_model('ollama/' + model) != model:
            raise RuntimeErrorSafe('model_not_allowed')
        self.model, self.budget = model, budget
        self.session_factory = session_factory

    def embed_query(self, text):
        return self.embed_queries([text])[0]

    def embed_queries(self, texts, kind='requirement'):
        if kind not in QUERY_INSTRUCTIONS:
            raise RuntimeErrorSafe('invalid_request')
        return self.embed_documents(texts)

    def embed_documents(self, texts):
        batches, batch, size = [], [], 0
        for text in texts:
            if type(text) is not str:
                raise RuntimeErrorSafe('invalid_request')
            length = len(text.encode('utf-8'))
            if batch and (len(batch) >= 32 or size + length > 48_000):
                batches.append(batch)
                batch, size = [], 0
            batch.append(text)
            size += length
        if batch:
            batches.append(batch)
        return [vector for part in batches for vector in self._embed(part)]

    def _embed(self, texts):
        import requests
        from pipeline.agentic.runtime import _json_bytes

        body = {'model': self.model, 'input': texts}
        request_size = _json_bytes(body)
        estimated_tokens = max(1, request_size // 4)
        self.budget.ensure_live()
        reservation = self.budget.reserve('evaluator', request_size, estimated_tokens)
        scope, scope_reservation = execution.current(), None
        dispatched = successful = False
        try:
            deadline = time.monotonic() + self.budget.remaining_seconds()
            if scope:
                scope_reservation = scope.reserve(self.model, 'evidence_embeddings', request_size, 1)
                deadline = min(deadline, scope.deadline)
            self.budget.dispatched(reservation)
            dispatched = True
            factory = self.session_factory or requests.Session
            with factory() as session:
                session.trust_env = False
                response = session.post(self.URL, json=body,
                    timeout=min(30.0, max(0.1, deadline - time.monotonic())), allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeErrorSafe('embedding_unavailable')
            payload = response.json()
            vectors = payload.get('embeddings') if type(payload) is dict else None
            if type(vectors) is not list or len(vectors) != len(texts):
                raise RuntimeErrorSafe('invalid_vector')
            successful = True
            return vectors
        except RuntimeErrorSafe as exc:
            if dispatched:
                self.budget.failed(exc.code)
            raise
        except (requests.RequestException, ValueError, TypeError):
            if dispatched:
                self.budget.failed('unavailable')
            raise RuntimeErrorSafe('embedding_unavailable') from None
        finally:
            usage = request_size if successful else (None if dispatched else 0)
            try:
                self.budget.settle(reservation, usage)
            finally:
                if scope_reservation is not None:
                    scope.settle(scope_reservation, usage)
                    scope.check()
            self.budget.ensure_live()


def make_embedding_adapter(llm, model, budget):
    """Select an adapter only from an explicit configured embedding model."""
    local_model = execution.ollama_embedding_model(model)
    if local_model is not None:
        return LocalOllamaEmbeddings(local_model, budget)
    return PaidGatewayEmbeddings(llm, model, budget)


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
