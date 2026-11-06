"""Jobwatch has one owner. This module only names the owner and the folders that belong to them."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_USER = "owner"


def current() -> str:
    return DEFAULT_USER


def base_dir() -> Path:
    from .apply.paths import DEFAULT_DATA_DIR
    from .settings import get as get_setting
    return Path(os.path.expanduser(get_setting("JOBWATCH_DATA_DIR") or DEFAULT_DATA_DIR))


def user_dir(name: str | None = None) -> Path:
    return base_dir()


def db_path(name: str | None = None) -> Path:
    return user_dir() / "jobwatch.db"


def config_dir(name: str | None = None, default: Path | None = None) -> Path | None:
    p = user_dir() / "config"
    return p if p.is_dir() else default
