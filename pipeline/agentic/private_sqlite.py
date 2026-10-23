"""Private SQLite connections without interfering with existing database locks."""
from __future__ import annotations

import errno
import os
import sqlite3
import stat
import threading
from pathlib import Path


_opening = threading.Lock()


def connect(path: Path, *, timeout: float = 10, check_same_thread: bool = True) -> sqlite3.Connection:
    # Closing any ordinary descriptor for a database can release another SQLite
    # connection's process-wide POSIX locks. Never open an existing DB ourselves.
    # Serialize first creation and connect so another local thread cannot attach
    # between creating the empty file and closing its creation descriptor.
    with _opening:
        try:
            info = path.lstat()
        except FileNotFoundError:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass  # Another process created it; verify its type below.
            else:
                os.close(fd)
            info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise OSError(errno.ELOOP, 'database_symlink_refused')
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, 'database_file_required')
        os.chmod(path, 0o600, follow_symlinks=False)
        return sqlite3.connect(path, timeout=timeout, check_same_thread=check_same_thread)
