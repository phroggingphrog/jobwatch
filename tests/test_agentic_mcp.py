"""MCP client support is optional, namespaced, gated and off by default."""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from jobwatch.util import model_choice as model_choice
from jobwatch import users
from jobwatch.util.llm import LLM
from pipeline.agentic.mcp_client import load_mcp_tools

STUB_SERVER = '''
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

COUNT = Path(sys.argv[1])
mcp = MCPServer("stub")


@mcp.tool()
def lookup(query: str) -> str:
    """Look up a synthetic public fact."""
    return "safe result for " + query


@mcp.tool()
def mutate(value: str) -> str:
    """Synthetic write tool; records every call."""
    with COUNT.open("a") as fh:
        fh.write("called\\n")
    return "mutated " + value


mcp.run()
'''


def stub_server(tmp_path):
    script = tmp_path / 'stub_mcp.py'
    script.write_text(STUB_SERVER)
    count = tmp_path / 'calls.txt'
    return script, count


def stub_config(script, count, *, read_only=('lookup',), startup=20, tool=20):
    return {'agentic': {'enabled': False}, 'mcp_client': {'enabled': True, 'servers': [{
        'name': 'stub',
        'enabled': True,
        'transport': 'stdio',
        'command': sys.executable,
        'args': [str(script), str(count)],
        'read_only_tools': list(read_only),
        'startup_timeout_seconds': startup,
        'tool_timeout_seconds': tool,
    }]}}


def choice(name, **arguments):
    return {'tool': name, 'arguments': arguments}


def transport_llm(choices):
    pending = iter(choices)
    seen = []

    def transport(url, headers, body, timeout):
        seen.append((url, body, timeout))
        payload = next(pending)
        return 200, {'choices': [{'message': {'content': json.dumps(payload)}}],
                     'usage': {'prompt_tokens': 11, 'completion_tokens': 7}}

    return LLM(transport=transport, keys=['synthetic-key']), seen


def prepare_person(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(model_choice, 'SERVER_URL', 'http://127.0.0.1:20128/v1')
    monkeypatch.setattr(model_choice, 'get_model', lambda role, *args: 'claude/sonnet')
    users.create_user_dirs('fixture-mcp')
    root = users.user_dir('fixture-mcp')
    with sqlite3.connect(root / 'jobwatch.db') as conn:
        # create_user_dirs() already migrated the real schema; keep this idempotent.
        conn.execute('CREATE TABLE IF NOT EXISTS postings(id INTEGER PRIMARY KEY)')


def test_mcp_is_off_by_default():
    assert not load_mcp_tools('person', {})
    assert not load_mcp_tools('person', {'mcp_client': {'enabled': False, 'servers': [{
        'name': 'never', 'enabled': True, 'command': sys.executable,
        'args': ['-c', 'raise SystemExit(9)']}]}})


def test_broken_and_malformed_servers_degrade_without_raising():
    broken = {'mcp_client': {'enabled': True, 'servers': [{
        'name': 'broken', 'enabled': True, 'transport': 'stdio',
        'command': sys.executable, 'args': ['-c', 'import sys; sys.exit(3)'],
        'startup_timeout_seconds': 5}]}}
    result = load_mcp_tools('person', broken)
    assert not result.tools and result.degraded == ['broken']

    malformed = {'mcp_client': {'enabled': True, 'servers': [{
        'name': 'bad config', 'enabled': True, 'transport': 'stdio'}]}}
    result = load_mcp_tools('person', malformed)
    assert not result.tools and result.degraded == ['bad config']


def test_stub_tools_are_namespaced_and_write_tools_are_gated(tmp_path):
    script, count = stub_server(tmp_path)
    result = load_mcp_tools('person', stub_config(script, count))
    assert [tool.name for tool in result.tools] == ['stub__lookup', 'stub__mutate']
    assert result.gated == {'stub__mutate'}
    assert result.degraded == []

    lookup = next(tool for tool in result.tools if tool.name == 'stub__lookup')
    assert 'safe result for synthetic' in json.dumps(lookup.invoke({'query': 'synthetic'}))
    assert not count.exists()


def test_read_tool_result_reaches_the_model(tmp_path, monkeypatch):
    from pipeline.agentic.chat import dispatch

    script, count = stub_server(tmp_path)
    prepare_person(tmp_path, monkeypatch)
    llm, seen = transport_llm([
        choice('stub__lookup', query='synthetic'),
        {'answer': 'Used the external lookup.'},
    ])
    llm.base_url = model_choice.SERVER_URL
    result = dispatch(person='fixture-mcp', thread_id='mcp-read', message='Look it up',
                      config=stub_config(script, count), llm=llm)
    assert result['status'] == 'complete'
    assert result['tools'] == ['stub__lookup']
    assert 'safe result for synthetic' in json.dumps(seen[-1])


def test_write_tool_pauses_and_never_runs(tmp_path, monkeypatch):
    from pipeline.agentic.chat import dispatch

    script, count = stub_server(tmp_path)
    prepare_person(tmp_path, monkeypatch)
    llm, _ = transport_llm([choice('stub__mutate', value='x')])
    llm.base_url = model_choice.SERVER_URL
    result = dispatch(person='fixture-mcp', thread_id='mcp-write', message='Change it',
                      config=stub_config(script, count), llm=llm)
    assert result['status'] == 'interrupted'
    assert result['interrupts'][0]['action_requests'][0]['name'] == 'stub__mutate'
    assert not count.exists()
