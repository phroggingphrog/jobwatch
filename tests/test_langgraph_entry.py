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
