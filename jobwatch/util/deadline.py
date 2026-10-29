"""Interrupt synchronous collector work, including blocking transports and retry sleeps."""
from contextlib import contextmanager
import signal
import threading
import time


class CollectionDeadline(BaseException):
    """Not a source error: retries must not swallow the run deadline."""


@contextmanager
def collection_budget(seconds):
    # Collectors run synchronously in the CLI's main thread. Refuse to silently
    # promise a hard deadline in a worker thread, where SIGALRM cannot be used.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('collection budget requires the main thread')
    if seconds <= 0:
        raise CollectionDeadline('collection_deadline')
    def expired(signum, frame):
        raise CollectionDeadline('collection_deadline')
    previous = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, old_timer[0]) if old_timer[0] else seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if old_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(1e-6, old_timer[0] - (time.monotonic() - started)), old_timer[1])
