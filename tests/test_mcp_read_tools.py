"""The two read-only MCP additions: the stored advertisement and the follow-up cadence.

Both must read stored rows inside the token's person and must never start a chat turn, call a model
or ask for an approval. The tool set is also pinned: no read name may duplicate an existing one.
"""
import asyncio
from datetime import UTC, datetime, timedelta
import types

import pytest

pytest.importorskip('fastmcp')

from jobwatch import db, ledger, users                                          # noqa: E402
from jobwatch.followup.events import record_event                              # noqa: E402
from pipeline.agentic import mcp_server                                        # noqa: E402
from pipeline.agentic.runtime import RuntimeErrorSafe                          # noqa: E402

NOW = datetime(2026, 10, 11, 1, tzinfo=UTC)
TOKEN = 'x' * 40
AD = 'Synthetic advertisement. Answer phones and process invoices. ' * 20

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    path = tmp_path / 'jobwatch.db'
    conn = db.connect(path)
    conn.execute('INSERT INTO postings(id,source,source_id,url,url_hash,dedupe_key,title,company,location,'
                 'description,first_seen_at,last_seen_at) VALUES(1,?,?,?,?,?,?,?,?,?,?,?)',
                 ('test', '1', 'https://example.test/job', 'h', 'd', 'Synthetic role', 'Synthetic Co',
                  'Melbourne VIC', AD, NOW.isoformat(), NOW.isoformat()))
    ledger.upsert(conn, 'applications', 'applications',
                  {'id': 1, 'posting_id': 1, 'status': 'applied', 'created_at': NOW.isoformat(),
                   'updated_at': NOW.isoformat(), 'applied_at': (NOW - timedelta(days=14)).isoformat()})
    record_event(conn, 1, 'applied_confirmed', operation_id='apply1', owner_confirmed=True,
                 occurred_at=NOW - timedelta(days=14), now=NOW)
    conn.commit()
    import jobwatch.config as config_module
    monkeypatch.setattr(config_module, 'load_config',
                        lambda: types.SimpleNamespace(db_path=path, settings={}))
    monkeypatch.setattr(mcp_server, 'get_access_token', lambda: types.SimpleNamespace(subject=users.current()))
    def refuse(*args, **kwargs):
        raise AssertionError('a read must not call a model')
    from jobwatch.util.llm import LLM
    for name in ('chat_once', 'chat'):
        monkeypatch.setattr(LLM, name, refuse)
    yield types.SimpleNamespace(server=mcp_server.create_server(token=TOKEN, person=users.current()),
                                path=path, conn=conn)
    conn.close()

def call(server, name, arguments):
    return asyncio.run(server.call_tool(name, arguments))

def payload(result):
    """The structured content of a tool result, or the first text block parsed as JSON."""
    structured = getattr(result, 'structuredContent', None) or getattr(result, 'structured_content', None)
    if structured is not None:
        return structured
    for block in getattr(result, 'content', result):
        text = getattr(block, 'text', None)
        if text:
            import json
            return json.loads(text)
    raise AssertionError(f'no payload in {result!r}')

def test_career_reader_returns_the_stored_ad_and_a_status_for_a_missing_posting(env):
    found = payload(call(env.server, 'career_reader', {'posting_id': 1}))
    assert found['status'] == 'ok' and found['posting_id'] == 1
    assert found['posting']['title'] == 'Synthetic role' and found['posting']['company'] == 'Synthetic Co'
    assert 'Synthetic advertisement' in found['full_ad'] and found['text_kind'] in {'full', 'partial', 'teaser'}
    assert str(env.path.parent) not in repr(found)               # no host path in the payload
    missing = payload(call(env.server, 'career_reader', {'posting_id': 404}))
    assert missing == {'posting_id': 404, 'status': 'missing'}

def test_followup_history_returns_recorded_cadence(env):
    result = payload(call(env.server, 'followup_history', {'application_id': 1}))
    assert result['status'] == 'ok' and result['application_status'] == 'applied'
    assert result['applied_on'] == (NOW - timedelta(days=14)).date().isoformat()
    assert result['sent_on'] == [] and result['pin_active'] is False
    assert result['cadence']['state'] in {'due', 'urgent', 'overdue', 'waiting', 'cold'}
    assert result['cadence']['sent_count'] == 0
    assert result['cadence']['draft_allowed'] == (result['cadence']['state'] in {'urgent', 'overdue'})

def test_followup_history_reports_a_missing_application(env):
    assert payload(call(env.server, 'followup_history', {'application_id': 999})) == \
        {'application_id': 999, 'status': 'missing'}

def test_a_read_writes_nothing(env):
    before = env.conn.execute('PRAGMA data_version').fetchone()[0]
    call(env.server, 'career_reader', {'posting_id': 1})
    call(env.server, 'followup_history', {'application_id': 1})
    after = env.conn.execute('PRAGMA data_version').fetchone()[0]
    assert before == after                                      # no other connection committed

def test_the_person_comes_from_the_token_not_from_the_arguments(monkeypatch):
    monkeypatch.setattr(mcp_server, 'get_access_token', lambda: None)
    # No valid token: the read refuses before it opens a row.
    with pytest.raises(RuntimeErrorSafe, match='mcp_auth_required'):
        with mcp_server._read():
            pass
    # The tool schema has no person argument, so a model cannot name another account.
    server = mcp_server.create_server(token=TOKEN, person=users.current())
    with pytest.raises(Exception, match='person'):
        call(server, 'career_reader', {'posting_id': 1, 'person': 'someone-else'})

def test_the_tool_set_adds_two_reads_and_no_second_name_for_an_existing_read(env):
    tools = {t.name: t for t in asyncio.run(env.server.list_tools())}
    for name in ('career_reader', 'followup_history'):
        assert getattr(tools[name].annotations, 'read_only_hint', None) is True
        assert getattr(tools[name].annotations, 'destructive_hint', None) is False
    assert getattr(tools['submit_reviewed'].annotations, 'destructive_hint', None) is True
    reads = {'jobs_overview', 'applications_overview', 'assessment_detail', 'application_detail',
             'job_detail', 'task_status', 'career_reader', 'followup_history'}
    assert reads <= set(tools)
    assert 'find_jobs' not in tools and 'application_status' not in tools   # jobs_overview/job_detail cover them

def test_a_short_token_is_refused():
    with pytest.raises(RuntimeErrorSafe):
        mcp_server.create_server(token='short', person=users.current())
