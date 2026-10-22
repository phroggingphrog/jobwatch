"""Data contract paths (PLAN-apply D2) and the profile write guard.

User layer   <data>/profile/   read-only to code (only scripts/seed_profile.py writes it, once)
System layer <data>/ledger/    append-only JSONL, canonical
             <data>/drafts/    drafts/<application_id>/v<n>/
SQLite is a derived index (`jobwatch reindex`).

Overrides (settings.env or environment): JOBWATCH_DATA_DIR, JOBWATCH_PROFILE_DIR.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

DEFAULT_DATA_DIR = "~/.local/share/jobwatch"  # override: JOBWATCH_DATA_DIR in settings.env


class ProfileWriteError(PermissionError):
    """Raised when code tries to write inside the user layer (profile/)."""


_pinned_profile: contextvars.ContextVar[Path | None] = contextvars.ContextVar("jobwatch_pinned_profile", default=None)


@contextlib.contextmanager
def pin_profile_dir(path: str | Path) -> Iterator[Path]:
    """Make profile_dir() return `path` for the block, ahead of any environment or person logic.

    A context variable: synchronous code only, and threads started inside the block do not inherit it. The pinned
    folder is the profile folder for guard_write too, so it is read-only to code while pinned. Pins nest."""
    folder = Path(path)
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError(f"pinned profile folder must be an existing absolute directory: {folder.name}")
    token = _pinned_profile.set(folder)
    try:
        yield folder
    finally:
        _pinned_profile.reset(token)


def data_dir() -> Path:
    from .. import users  # multi-person: the signed-in person's folder
    return users.user_dir()


def profile_dir() -> Path:
    """The signed-in person's profile folder. JOBWATCH_PROFILE_DIR may move only the main user's folder; every other
    person always gets their own (a server-wide setting once pointed everyone at the owner's profile, 2026-10-20).
    Inside pin_profile_dir() the pinned folder wins over both."""
    pinned = _pinned_profile.get()
    if pinned is not None:
        return pinned
    from .. import users
    from ..settings import get
    env = get("JOBWATCH_PROFILE_DIR") if users.current() == users.DEFAULT_USER else ""
    return Path(os.path.expanduser(env)) if env else data_dir() / "profile"


def ledger_dir() -> Path:
    return data_dir() / "ledger"


def drafts_dir() -> Path:
    return data_dir() / "drafts"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def guard_write(path: str | Path) -> Path:
    """Refuse any write under profile/ (resolves symlinks and `..`)."""
    p = Path(path)
    if _inside(p, profile_dir()) or _inside(p.parent, profile_dir()):
        raise ProfileWriteError(f"profile/ is read-only to code (data contract): {p.name}")
    return p


def ensure_dir(path: str | Path) -> Path:
    """mkdir -p with mode 700 on every directory we create."""
    p = guard_write(Path(path))
    missing = []
    cur = p
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    for d in reversed(missing):
        d.mkdir(mode=0o700, exist_ok=True)
    return p


def safe_write_bytes(path: str | Path, data: bytes) -> Path:
    """Atomic write (tmp + fsync + rename), mode 600, never under profile/."""
    p = guard_write(Path(path))
    ensure_dir(p.parent)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return p


def safe_write_text(path: str | Path, text: str) -> Path:
    return safe_write_bytes(path, text.encode("utf-8"))
