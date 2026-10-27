"""Notification channels: outbox, dedupe, digest window, secrets, settings alias, CLI. Offline, fake transports."""
import json
import logging
import re
import sqlite3
import subprocess
import urllib.error
from pathlib import Path

import pytest

from jobwatch import db as dbm
from jobwatch import notifier
from jobwatch.notifier import channels, legacy, service
from tests.notify_support import FakeChannel, use_fake_channel

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def conn():
    with sqlite3.connect(':memory:') as value:
        yield value


def event(key='k1', text='Jobwatch: something broke', **kw):
    return notifier.Event(notifier.FAILURE, text, key, notifier.FailurePayload(reason='execution_failed'), **kw)


def test_outbox_retries_with_backoff_then_gives_up(conn, monkeypatch):
    sent = []
    use_fake_channel(monkeypatch, lambda lines: sent.extend(lines) and False)
    assert notifier.enqueue(conn, event(), now=1000) == 1
    assert notifier.dispatch(conn, now=1000) == 0
    row = conn.execute('SELECT state,attempts,next_attempt_at,last_error FROM notify_outbox').fetchone()
    assert row == ('pending', 1, 1060, 'fake_failure')
    assert notifier.dispatch(conn, now=1059) == 0 and len(sent) == 1          # still backing off
    FakeChannel.sender = staticmethod(lambda lines: sent.extend(lines) or True)
    assert notifier.dispatch(conn, now=1060) == 1
    assert conn.execute('SELECT state,attempts FROM notify_outbox').fetchone() == ('delivered', 2)
    assert notifier.dispatch(conn, now=99999) == 0 and len(sent) == 2          # delivered once
    assert [r[0] for r in conn.execute('SELECT status FROM notify_receipts ORDER BY id')] == ['failed', 'delivered']


def test_outbox_stops_after_max_attempts(conn, monkeypatch):
    use_fake_channel(monkeypatch, lambda lines: False)
    notifier.enqueue(conn, event(), now=0)
    now = 0
    for _ in range(service.MAX_ATTEMPTS + 3):
        now += 10 ** 5
        notifier.dispatch(conn, now=now)
    assert conn.execute('SELECT state,attempts FROM notify_outbox').fetchone() == ('failed', service.MAX_ATTEMPTS)


def test_same_key_is_sent_once_per_window(conn, monkeypatch):
    use_fake_channel(monkeypatch, lambda lines: True)
    assert notifier.enqueue(conn, event('a'), now=100) == 1
    assert notifier.enqueue(conn, event('a'), now=100 + 86399) == 0            # a day per key
    assert notifier.enqueue(conn, event('b'), now=100 + 5) == 1
    assert notifier.enqueue(conn, event('a'), now=100 + 86401) == 1
    assert notifier.enqueue(conn, event('c', dedupe_window=0), now=1) == 1
    assert notifier.enqueue(conn, event('c', dedupe_window=0), now=1) == 1


def test_event_filter_and_none_channel(conn):
    notifier.add_channel(conn, 'quiet', 'command', {'argv': ['true']}, events=['failure'])
    notifier.add_channel(conn, 'off', 'none')
    completion = notifier.Event(notifier.COMPLETION, 'done', 'c1', notifier.CompletionPayload(posting_id=1))
    assert notifier.enqueue(conn, completion) == 0
    assert notifier.enqueue(conn, event()) == 1
    assert [c.name for c in notifier.channels_for(conn)] == ['quiet']
    with pytest.raises(ValueError):
        notifier.Event(notifier.FAILURE, 'x', 'k', notifier.CompletionPayload())


def test_digest_window_is_per_channel_policy(conn, monkeypatch):
    monkeypatch.delenv(legacy.SSH_ENV, raising=False)
    assert notifier.digest_window(conn, 'incident') == 6 * 3600                     # no channel: the usual window
    notifier.add_channel(conn, 'slow', 'command', {'argv': ['true']})
    assert notifier.digest_window(conn, 'incident') == 6 * 3600
    notifier.add_channel(conn, 'fast', 'command', {'argv': ['true']}, digest={'incident': 600})
    assert notifier.digest_window(conn, 'incident') == 600
    notifier.disable_channel(conn, 'fast')
    assert notifier.digest_window(conn, 'incident') == 6 * 3600


def test_deliver_is_one_attempt_and_reports_no_channel(conn, monkeypatch):
    monkeypatch.delenv(legacy.SSH_ENV, raising=False)
    assert notifier.deliver(conn, event()).status == 'no_channel'
    use_fake_channel(monkeypatch, lambda lines: False)
    result = notifier.deliver(conn, event(dedupe_window=0))
    assert (result.status, result.error) == ('failed', 'delivery_failed')
    assert notifier.dispatch(conn, now=10 ** 9) == 0                                # the caller owns the retry


def test_secret_references_only_and_nothing_secret_is_logged(conn, monkeypatch, caplog, capsys):
    secret = 'https://hooks.example.invalid/T0K3N-9f3a'
    monkeypatch.setenv('SYNTHETIC_HOOK', secret)
    for bad in ({'url': secret}, {'url_ref': secret}, {'url_ref': 'env:A', 'token': 'x'}):
        with pytest.raises(ValueError) as err:
            notifier.add_channel(conn, 'hook', 'webhook', bad)
        assert 'T0K3N' not in str(err.value)
    with pytest.raises(ValueError):
        notifier.add_channel(conn, 'ssh', 'ssh_append', {'host': 'a@b', 'file': '/x', 'password': 'p'})
    notifier.add_channel(conn, 'hook', 'webhook', {'url_ref': 'env:SYNTHETIC_HOOK'})
    seen = {}

    def boom(req, timeout):
        seen['url'] = req.full_url
        raise urllib.error.HTTPError(req.full_url, 502, 'bad', {}, None)
    monkeypatch.setattr(channels.urllib.request, 'urlopen', boom)
    caplog.set_level(logging.DEBUG)
    notifier.enqueue(conn, event())
    notifier.dispatch(conn)
    cfg, receipt, healthy = notifier.test_channel(conn, 'hook')
    assert seen['url'] == secret and receipt.detail == 'http_502' and healthy
    stored = json.dumps([conn.execute(f'SELECT * FROM {t}').fetchall() for t in
                         ('notify_channels', 'notify_outbox', 'notify_receipts')])
    assert 'T0K3N' not in stored and 'T0K3N' not in caplog.text and 'env:SYNTHETIC_HOOK' in stored


def test_command_channel_gets_stdin_and_no_shell(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(channels.shutil, 'which', lambda name: '/bin/' + name)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: calls.append((a, k)) or subprocess.CompletedProcess(a, 0, '', ''))
    notifier.add_channel(conn, 'cmd', 'command', {'argv': ['tell', '--to', '$(whoami); rm -rf /']})
    assert notifier.deliver(conn, event('x', 'a  message\nwith lines')).delivered
    (args, kwargs), = calls
    assert args[0] == ['tell', '--to', '$(whoami); rm -rf /'] and not kwargs.get('shell')
    assert kwargs['input'] == 'a message with lines\n'


def test_webhook_posts_json(conn, monkeypatch):
    monkeypatch.setenv('SYNTHETIC_HOOK', 'https://hooks.example.invalid/x')
    notifier.add_channel(conn, 'hook', 'webhook', {'url_ref': 'env:SYNTHETIC_HOOK'})
    got = {}

    class Resp:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(channels.urllib.request, 'urlopen', lambda req, timeout: got.update(body=json.loads(req.data)) or Resp())
    assert notifier.deliver(conn, event()).delivered
    assert got['body']['kind'] == 'failure' and got['body']['payload']['reason'] == 'execution_failed'


def test_settings_alias_is_an_equivalent_ssh_append_channel(conn, monkeypatch):
    monkeypatch.setenv(legacy.SSH_ENV, 'owner@assistant.example')
    monkeypatch.setenv(legacy.FILE_ENV, '~/inbox/jobwatch notify.txt')
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: calls.append((a, k)) or subprocess.CompletedProcess(a, 0, '', ''))
    found = notifier.channels_for(conn)
    assert [(c.name, c.kind, c.source) for c in found] == [(legacy.ALIAS_CHANNEL, 'ssh_append', 'env-alias')]
    assert notifier.enqueue(conn, event(text='Jobwatch: Error: x [k]')) == 1 and notifier.dispatch(conn) == 1
    (args, kwargs), = calls
    assert args[0][:5] == ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8']
    assert args[0][-2:] == ['owner@assistant.example', "cat >> ~/'inbox/jobwatch notify.txt'"]
    assert kwargs['input'] == 'Jobwatch: Error: x [k]\n'
    # the person's own channel replaces the alias; disabling the alias turns it off
    notifier.add_channel(conn, 'mine', 'command', {'argv': ['true']})
    assert [c.name for c in notifier.channels_for(conn)] == ['mine']
    notifier.disable_channel(conn, 'mine')
    assert [c.name for c in notifier.channels_for(conn)] == [legacy.ALIAS_CHANNEL]
    notifier.disable_channel(conn, legacy.ALIAS_CHANNEL)
    assert notifier.channels_for(conn) == []


def test_alias_needs_both_settings_and_the_owner(conn, monkeypatch):
    from jobwatch import users
    monkeypatch.setenv(legacy.SSH_ENV, 'owner@assistant.example')
    monkeypatch.delenv(legacy.FILE_ENV, raising=False)
    assert notifier.channels_for(conn) == []
    monkeypatch.setenv(legacy.FILE_ENV, '/x')
    with users.use('someone-else'):
        assert notifier.channels_for(conn) == []


def test_migration_creates_tables_and_ensure_is_idempotent(tmp_path):
    conn = dbm.connect(tmp_path / 'x.db')
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'notify_channels', 'notify_outbox', 'notify_receipts'} <= names
    notifier.ensure(conn)
    notifier.ensure(conn)
    # an older database (before the migration) upgrades without losing rows
    old = sqlite3.connect(tmp_path / 'old.db')
    for i, script in enumerate(dbm.MIGRATIONS[:-1], start=1):
        for stmt in dbm._statements(script):
            old.execute(stmt)
        old.execute(f'PRAGMA user_version={i}')
    old.commit()
    old.close()
    assert dbm.connect(tmp_path / 'old.db').execute('SELECT COUNT(*) FROM notify_channels').fetchone()[0] == 0


def test_cli_add_list_test_disable(tmp_path, monkeypatch, capsys):
    from jobwatch import cli
    monkeypatch.setenv('JOBWATCH_DB', str(tmp_path / 'cli.db'))
    monkeypatch.setenv('SYNTHETIC_HOOK', 'https://hooks.example.invalid/T0K3N')
    assert cli.main(['notify', 'channels', 'add', 'hook', '--kind', 'webhook', '--set', 'url_ref=env:SYNTHETIC_HOOK']) == 0
    assert cli.main(['notify', 'channels', 'add', 'bad', '--kind', 'webhook', '--set', 'url=https://x.example/T0K3N']) == 2
    capsys.readouterr()
    assert cli.main(['notify', 'channels', 'list']) == 0
    out = capsys.readouterr().out
    assert 'hook\twebhook\tenabled' in out and 'url_ref=env:SYNTHETIC_HOOK' in out and 'T0K3N' not in out

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(channels.urllib.request, 'urlopen', lambda req, timeout: Resp())
    assert cli.main(['notify', 'channels', 'test', 'hook']) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {'channel': 'hook', 'kind': 'webhook', 'healthy': True, 'status': 'delivered', 'detail': 'http_200'}
    assert cli.main(['notify', 'channels', 'disable', 'hook']) == 0
    assert cli.main(['notify', 'channels', 'disable', 'nope']) == 1
    capsys.readouterr()
    assert cli.main(['notify', 'channels', 'list']) == 0
    assert 'disabled' in capsys.readouterr().out


def test_no_private_assistant_name_in_code_paths():
    allowed = {ROOT / 'jobwatch' / 'notifier' / 'legacy.py'}
    hits = []
    for folder in ('jobwatch', 'pipeline'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and path.suffix in {'.py', '.html', '.md', '.js', '.css', '.txt', '.json', '.yaml'} \
                    and path not in allowed and re.search('hermes', path.read_text(errors='ignore'), re.I):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []
