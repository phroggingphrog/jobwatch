"""Discovery status stays registered, identity-bound, and read-only."""
import asyncio
import hashlib
import sqlite3

import pytest

pytest.importorskip('fastmcp')
from fastmcp import Client
from fastapi.testclient import TestClient

from conftest import make_config
from jobwatch import users, db
from pipeline.agentic import connector_http, discovery_ops, mcp_server, service
from pipeline.agentic.api_store import APIStore

TOKEN = 'x' * 40


def test_registry_and_dispatch_share_rest_operation(monkeypatch):
    seen = []
    monkeypatch.setattr(mcp_server, '_person_from_request', lambda: 'fixture-a')
    monkeypatch.setattr(connector_http, 'discovery_status_operation',
                        lambda person: seen.append(person) or {'enabled': False})
    server = mcp_server.create_server(token=TOKEN, person='fixture-a')

    async def check():
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            tool = tools['discovery_status']
            assert tool.input_schema.get('properties', {}) == {}
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
            result = await client.call_tool('discovery_status', {})
            assert result.structured_content == {'enabled': False}
    asyncio.run(check())
    assert seen == ['fixture-a']


def test_authentication_and_scope_reject_before_status(monkeypatch):
    def forbidden(*args):
        pytest.fail('unauthenticated status dispatched')
    monkeypatch.setattr(connector_http, 'discovery_status_operation', forbidden)
    server = mcp_server.create_server(token=TOKEN, person='fixture-a')
    assert server.auth.required_scopes == ['jobwatch']

    async def check():
        assert await server.auth.verify_token('wrong') is None
        verified = await server.auth.verify_token(TOKEN)
        assert verified.scopes == ['jobwatch']
    asyncio.run(check())
    with TestClient(server.http_app()) as client:
        for headers in ({}, {'Authorization': 'Bearer wrong'}):
            response = client.post('/mcp', headers={**headers, 'Accept': 'application/json, text/event-stream'},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                      'params': {'name': 'discovery_status', 'arguments': {}}})
            assert response.status_code == 401


@pytest.mark.parametrize('initialized', [False, True])
def test_status_never_creates_or_changes_runtime_files(tmp_path, monkeypatch, initialized):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(users, 'base_dir', lambda: tmp_path)
    monkeypatch.setattr(discovery_ops.intake, 'discovery_scope', lambda person: None)
    config = make_config(tmp_path=tmp_path)
    if initialized:
        with users.use('fixture-a'):
            conn = db.connect(users.db_path())
            service.AgenticStore(conn).ensure()
            conn.commit()
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.close()
        with APIStore('fixture-a') as store:
            store.enqueue_discovery({'discovery': True}, 'fixture-request', 'fixture-skill')
            store.conn.execute('PRAGMA journal_mode=DELETE')
    def snapshot():
        return {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in tmp_path.rglob('*') if p.is_file()}
    before = snapshot()
    monkeypatch.setattr(connector_http, 'discovery_status_operation',
                        lambda person: discovery_ops.status(person, config))
    monkeypatch.setattr(mcp_server, '_person_from_request', lambda: 'fixture-a')
    server = mcp_server.create_server(token=TOKEN, person='fixture-a')
    async def check():
        async with Client(server) as client:
            result = await client.call_tool('discovery_status', {})
            assert result.structured_content['enabled'] is False
            assert bool(result.structured_content['latest_run']) is initialized
    asyncio.run(check())
    assert snapshot() == before


def test_readonly_api_store_cannot_write(tmp_path, monkeypatch):
    monkeypatch.setattr(users, 'base_dir', lambda: tmp_path)
    with APIStore('fixture-a'):
        pass
    with APIStore('fixture-a', readonly=True) as store:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            store.conn.execute('DELETE FROM api_runs')
