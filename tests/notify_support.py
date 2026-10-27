"""A fake notification channel for offline tests: `sender(lines)` decides if a delivery worked."""
import time

from jobwatch import notifier
from jobwatch.notifier import channels, service


class FakeChannel:
    kind = 'fake'
    sender = staticmethod(lambda lines: True)

    def __init__(self, name='fake', config=None):
        self.name = name

    def healthy(self):
        return True

    def send(self, event):
        ok = bool(FakeChannel.sender([event.line]))
        return channels.Receipt('delivered' if ok else 'failed', 'ok' if ok else 'fake_failure', time.time())


def use_fake_channel(monkeypatch, sender, *, digest=None):
    """Every person has one enabled 'fake' channel that calls sender(lines)."""
    monkeypatch.setattr(FakeChannel, 'sender', staticmethod(sender))
    monkeypatch.setitem(channels.KINDS, 'fake', FakeChannel)
    monkeypatch.setitem(channels.ALLOWED, 'fake', set())
    cfg = service.ChannelConfig('fake', 'fake', digest=digest if digest is not None else dict(service.DEFAULT_DIGEST))
    monkeypatch.setattr(service, 'channels_for', lambda conn, person=None, include_disabled=False: [cfg])
    return cfg
