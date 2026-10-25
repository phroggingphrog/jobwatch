"""Serve Jobwatch's own chat graph through a LangGraph server (spike for the Deep Agents Code TUI).

`make_graph()` builds the same `create_deep_agent` graph as `chat.dispatch` for one person
(`JOBWATCH_LANGGRAPH_PERSON`, default the current person). With `JOBWATCH_LANGGRAPH_FAKE=1` the model is a
stub that answers without any gateway call, so nothing is paid or sent anywhere. Jobwatch's gates
(interrupt_on, exact-form bindings) are the ones built into the graph; this only changes the front end.
Not wired into the product; point a `langgraph.json` at `pipeline.agentic.langgraph_entry:make_graph`.
"""
from __future__ import annotations

import os
import threading
from copy import deepcopy

from jobwatch import model_choice, users
from jobwatch.apply.paths import ensure_dir
from jobwatch.config import load_config
from pipeline.agentic import chat
from pipeline.agentic.chat_storage import ChatSaver, ChatStore
from pipeline.agentic.private_sqlite import connect


class _FakeModel(chat.ConversationModel):
    """Answers with a fixed sentence; 'submit N' calls the gated submit tool so an approval shows up."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        last = messages[-1]
        text = last.content if isinstance(last.content, str) else str(last.content)
        if isinstance(last, HumanMessage) and text.lower().startswith('submit '):
            number = int(''.join(c for c in text if c.isdigit()) or 0)
            message = AIMessage(content='', tool_calls=[{'name': 'submit_application', 'args': {'posting_id': number},
                                                         'id': 'fake-1', 'type': 'tool_call'}])
        elif isinstance(last, ToolMessage):
            message = AIMessage(content='Fake Jobwatch: that tool call finished.')
        else:
            message = AIMessage(content=f'Fake Jobwatch (no model call) heard: {text[:200]}')
        return ChatResult(generations=[ChatGeneration(message=message)])


def make_graph():
    person = os.environ.get('JOBWATCH_LANGGRAPH_PERSON') or users.current()
    cfg = load_config()
    with users.use(person):
        root = ensure_dir(users.user_dir() / 'career-chat')
        connection = connect(root / 'state-langgraph.sqlite', timeout=5, check_same_thread=False)
        lock = threading.RLock()
        saver, store = ChatSaver(connection, lock), ChatStore(connection, lock)
        from pipeline.agentic.service import configured_llm, settings
        settings_copy = deepcopy(settings(cfg))
        settings_copy['_agent_db_path'] = str(chat.job_database(cfg))
        settings_copy['openrouter_extras'] = {'enabled': False}
        if os.environ.get('JOBWATCH_LANGGRAPH_FAKE') == '1':
            original = chat.ConversationModel
            chat.ConversationModel = _FakeModel
            try:
                return chat._build(person, connection, settings_copy, object(), 'fake/stub', saver, store)
            finally:
                chat.ConversationModel = original
        transport = configured_llm(cfg)
        selected = model_choice.get_model('chat')
        chat._route(transport, selected)
        return chat._build(person, connection, settings_copy, transport, selected, saver, store)
