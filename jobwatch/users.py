"""Jobwatch has one owner. This module names the owner and the folders that belong to them.

Every path helper accepts the caller's person name and refuses any name but the owner, so
a leftover multi-person credential cannot silently read or write the owner's storage.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_USER = "owner"

class OwnerError(ValueError):
    """A caller named someone other than the single owner."""

    def __init__(self, code: str = "owner_required"):
        self.code = code
        super().__init__(code)

def current() -> str:
    return DEFAULT_USER

def require_owner(name: str | None) -> str:
    """The owner name, or a refusal. ``None`` and ``""`` mean the configured owner."""
    if name is None or name == "" or name == DEFAULT_USER:
        return DEFAULT_USER
    raise OwnerError()

def base_dir() -> Path:
    from .apply.paths import DEFAULT_DATA_DIR
    from .settings import get as get_setting
    return Path(os.path.expanduser(get_setting("JOBWATCH_DATA_DIR") or DEFAULT_DATA_DIR))

def user_dir(name: str | None = None) -> Path:
    require_owner(name)
    return base_dir()

def db_path(name: str | None = None) -> Path:
    return user_dir(name) / "jobwatch.db"

def config_dir(name: str | None = None, default: Path | None = None) -> Path | None:
    p = user_dir(name) / "config"
    return p if p.is_dir() else default
