"""Offline regressions for notifier delivery and deduplication."""
import sqlite3

from jobwatch import notifier
from jobwatch.notifier import channels, service
from tests.notify_support import FakeChannel


def test_disabled_channel_rows_do_not_starve_active_channel(monkeypatch):
    conn = sqlite3.connect(':memory:')
    sent = []
    monkeypatch.setitem(channels.KINDS, 'fake', FakeChannel)
    monkeypatch.setattr(FakeChannel, 'sender', staticmethod(lambda lines: sent.extend(lines) or True))
    disabled = service.ChannelConfig('disabled', 'fake')
    active = service.ChannelConfig('active', 'fake')
    selected = [disabled]
    monkeypatch.setattr(service, 'channels_for', lambda *args, **kwargs: selected)

    for index in range(50):
        event = notifier.Event(notifier.FAILURE, 'synthetic', f'old-{index}', dedupe_window=0)
        assert notifier.enqueue(conn, event, person='synthetic', now=1) == 1
    selected[:] = [active]
    event = notifier.Event(notifier.FAILURE, 'synthetic', 'new', dedupe_window=0)
    assert notifier.enqueue(conn, event, person='synthetic', now=1) == 1

    assert notifier.dispatch(conn, person='synthetic', now=2) == 1
    assert sent == ['synthetic']
    assert conn.execute("SELECT COUNT(*) FROM notify_outbox WHERE channel='disabled' AND state='pending'").fetchone()[0] == 50
    assert conn.execute("SELECT state,attempts FROM notify_outbox WHERE channel='active'").fetchone() == ('delivered', 1)


def test_deliver_reports_prior_deduplicated_success(monkeypatch):
    conn = sqlite3.connect(':memory:')
    sent = []
    monkeypatch.setitem(channels.KINDS, 'fake', FakeChannel)
    monkeypatch.setattr(FakeChannel, 'sender', staticmethod(lambda lines: sent.extend(lines) or True))
    monkeypatch.setattr(service, 'channels_for', lambda *args, **kwargs: [service.ChannelConfig('active', 'fake')])
    event = notifier.Event(notifier.FAILURE, 'synthetic', 'same-key')

    assert notifier.deliver(conn, event, person='synthetic', now=100).status == 'delivered'
    result = notifier.deliver(conn, event, person='synthetic', now=101)
    assert result.status == 'delivered'
    assert result.receipts == []
    assert sent == ['synthetic']


def test_prior_success_remains_delivered_when_another_channel_fails(monkeypatch):
    conn = sqlite3.connect(':memory:')
    monkeypatch.setitem(channels.KINDS, 'fake', FakeChannel)
    selected = [service.ChannelConfig('good', 'fake')]
    monkeypatch.setattr(service, 'channels_for', lambda *args, **kwargs: selected)
    monkeypatch.setattr(FakeChannel, 'sender', staticmethod(lambda lines: True))
    event = notifier.Event(notifier.FAILURE, 'synthetic', 'partial-success')
    assert notifier.deliver(conn, event, person='synthetic', now=100).status == 'delivered'
    selected.append(service.ChannelConfig('bad', 'fake'))
    monkeypatch.setattr(FakeChannel, 'sender', staticmethod(lambda lines: False))
    result = notifier.deliver(conn, event, person='synthetic', now=101)
    assert result.status == 'delivered'
    assert len(result.receipts) == 1 and not result.receipts[0].ok
    assert conn.execute("SELECT attempts FROM notify_outbox WHERE channel='good'").fetchone()[0] == 1
