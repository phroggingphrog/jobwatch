"""The LangGraph-server entry builds Jobwatch's chat graph with a stub model (no gateway call)."""


def test_fake_graph_answers_without_a_model(monkeypatch, tmp_path):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBWATCH_LANGGRAPH_FAKE', '1')
    from pipeline.agentic.langgraph_entry import make_graph
    out = make_graph().invoke({'messages': [{'role': 'user', 'content': 'hello'}]},
                              {'configurable': {'thread_id': 't1'}})
    assert out['messages'][-1].content == 'Fake Jobwatch (no model call) heard: hello'


def test_private_boundary_runs_async_tool_calls_in_person_scope():
    import asyncio
    from types import SimpleNamespace
    from jobwatch import users
    from pipeline.agentic.chat import _PrivateBoundary
    seen = []
    async def handler(request):
        seen.append(users.current())
        return 'ok'
    boundary = _PrivateBoundary('friend')
    boundary.execution = None
    request = SimpleNamespace(tool_call={'name': 'inspect_job'})
    assert asyncio.run(boundary.awrap_tool_call(request, handler)) == 'ok'
    assert seen == ['friend']


def _server_graph(monkeypatch, tmp_path):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBWATCH_LANGGRAPH_FAKE', '1')
    from pipeline.agentic.langgraph_entry import make_graph
    return make_graph()


def test_server_path_submit_interrupts_and_approve_never_runs_it(monkeypatch, tmp_path):
    import pytest
    from langgraph.types import Command
    from pipeline.agentic.runtime import RuntimeErrorSafe
    graph, config = _server_graph(monkeypatch, tmp_path), {'configurable': {'thread_id': 'sub'}}
    out = graph.invoke({'messages': [{'role': 'user', 'content': 'submit 42'}]}, config)
    assert out['__interrupt__'][0].value['action_requests'][0]['name'] == 'submit_application'
    with pytest.raises(RuntimeErrorSafe, match='approval_required_via_jobwatch_client'):
        graph.invoke(Command(resume={'decisions': [{'type': 'approve'}]}), config)
    import sqlite3
    from jobwatch import users
    for db in tmp_path.rglob('*.sqlite'):
        c = sqlite3.connect(db)
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='submit_requests'").fetchone():
            assert c.execute('SELECT COUNT(*) FROM submit_requests').fetchone()[0] == 0


def test_server_path_prepare_application_interrupts(monkeypatch, tmp_path):
    from pipeline.agentic import langgraph_entry
    original = langgraph_entry._FakeModel._generate
    def generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        if isinstance(messages[-1], HumanMessage):
            m = AIMessage(content='', tool_calls=[{'name': 'prepare_application', 'args': {'posting_id': 42}, 'id': 'p1', 'type': 'tool_call'}])
            return ChatResult(generations=[ChatGeneration(message=m)])
        return original(self, messages, stop, run_manager, **kwargs)
    monkeypatch.setattr(langgraph_entry._FakeModel, '_generate', generate)
    out = _server_graph(monkeypatch, tmp_path).invoke({'messages': [{'role': 'user', 'content': 'go'}]},
                                                      {'configurable': {'thread_id': 'prep'}})
    assert out['__interrupt__'][0].value['action_requests'][0]['name'] == 'prepare_application'
