"""Who is using Jobwatch right now (multi-person, TASK-111).

One folder + one DB per person. The first person ("owner", the default user) keeps the
existing data dir untouched; everyone else lives in <data>/users/<name>/ with their own
jobwatch.db, profile/, ledger/, drafts/, config/ and browser/ folders.

The current person is a context variable: the web sign-in sets it per request, the CLI
sets it with --user. paths.data_dir() and Config.db_path follow it.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import re
from pathlib import Path

DEFAULT_USER = os.environ.get("JOBWATCH_DEFAULT_USER", "owner")
_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
_current: contextvars.ContextVar[str] = contextvars.ContextVar("jobwatch_user", default=DEFAULT_USER)


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def current() -> str:
    return _current.get()


def scoped(*ids) -> tuple:
    """(current person, *ids): the key for any in-process registry of running work. Ids (posting, application) are
    per person, so a bare id would let one person's run block or show up as another's."""
    return (current(), *ids)


@contextlib.contextmanager
def use(name: str):
    """Run a block as this person."""
    if not valid_name(name):
        raise ValueError(f"bad user name: {name!r}")
    token = _current.set(name)
    try:
        yield name
    finally:
        _current.reset(token)


def base_dir() -> Path:
    from .apply.paths import DEFAULT_DATA_DIR
    from .settings import get as get_setting
    return Path(os.path.expanduser(get_setting("JOBWATCH_DATA_DIR") or DEFAULT_DATA_DIR))


def user_dir(name: str | None = None) -> Path:
    name = name or current()
    if name == DEFAULT_USER:
        return base_dir()
    if not valid_name(name):
        raise ValueError(f"bad user name: {name!r}")
    return base_dir() / "users" / name


def db_path(name: str | None = None) -> Path:
    return user_dir(name) / "jobwatch.db"


def config_dir(name: str | None = None, default: Path | None = None) -> Path | None:
    """The person's own config/ (searches.yaml, rules.yaml) if they have one, else `default`."""
    p = user_dir(name) / "config"
    return p if p.is_dir() else default


def list_users() -> list[str]:
    out = [DEFAULT_USER]
    root = base_dir() / "users"
    if root.is_dir():
        out += sorted(p.name for p in root.iterdir() if p.is_dir() and valid_name(p.name))
    return out


def create_user_dirs(name: str) -> Path:
    d = user_dir(name)
    for sub in ("profile", "ledger", "drafts", "config", "browser"):
        (d / sub).mkdir(parents=True, exist_ok=True, mode=0o700)

    if d != base_dir():
        from . import db as dbm
        from pipeline import store as pstore
        from .preferences import PreferenceStore
        c = dbm.connect(d / "jobwatch.db")           # create + migrate the person's own DB
        pstore.ensure(c)
        PreferenceStore(c).ensure()
        c.close()
    return d
