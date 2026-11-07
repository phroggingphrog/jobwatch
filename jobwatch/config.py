"""Load the YAML config files. Paths can be overridden with environment variables:

JOBWATCH_CONFIG_DIR  exact config directory holding jobwatch.yaml, rules.yaml,
                     searches.yaml, feeds.yaml (no owner-runtime overlay)
JOBWATCH_EMPLOYERS   employers file (default: the first employers.yaml, then
                     employers.example.yaml, across the active config sources)
JOBWATCH_DB          SQLite path (default from jobwatch.yaml, ~/.local/share/jobwatch/jobwatch.db)

Without an explicit argument or JOBWATCH_CONFIG_DIR, the owner's runtime config directory
(users.config_dir()) is the first source and the repository defaults fill only the files it
does not contain. An explicit directory or JOBWATCH_CONFIG_DIR remains exact.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .settings import get as _setting

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_DIR = PACKAGE_ROOT / "config"

DEFAULT_SETTINGS: dict[str, Any] = {
    "db_path": "~/.local/share/jobwatch/jobwatch.db",
    "timezone": "Australia/Sydney",  # last resort; the install sets its own in jobwatch.yaml, the person in profile.yaml
    "http": {"timeout": 20, "min_delay": 1.5},
    "alerts": {"max_age_hours": 72},
    "retention_days": 90,
    "tiers": {
        "fast": ["ats_greenhouse", "ats_lever", "ats_ashby", "ats_workable", "ats_smartrecruiters",
                 "ats_workday", "ats_pageup", "ats_employmenthero", "ats_scouttalent", "ats_oracle",
                 "careers_vic", "ats_pulse", "ats_recruitmenthub", "ats_jobs_search", "ats_elmo", "ats_techone",
                 "rss", "reddit"],
        "slow": ["jobspy_src", "seek", "careers_vic", "ats_successfactors", "ats_phenom", "ats_atlassian",
                 "jsonld_pages"],
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_parsed: dict[Path, tuple[tuple[int, int], Any]] = {}


def _load(path: Path) -> Any:
    # The agent worker reloads config on every poll; re-parse only files that changed.
    try:
        st = path.stat()
    except OSError:
        return {}
    if not path.is_file():
        return {}
    key = (st.st_mtime_ns, st.st_size)
    hit = _parsed.get(path)
    if hit is None or hit[0] != key:
        with path.open() as fh:
            hit = _parsed[path] = (key, yaml.load(fh, Loader=_Loader) or {})
    return copy.deepcopy(hit[1])


@dataclass
class Config:
    config_dir: Path
    settings: dict
    rules: dict
    searches: dict
    feeds: dict
    employers: list[dict]
    employers_path: Path | None = None
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return Path(os.path.expanduser(_setting("JOBWATCH_DB") or self.settings["db_path"]))

    def employers_for(self, provider: str) -> list[dict]:
        return [e for e in self.employers
                if e.get("enabled", True) and str(e.get("provider", "")).lower() == provider]


def _config_sources(config_dir: str | Path | None) -> list[Path]:
    """Explicit argument/env are exact; the default owner layer overlays repository defaults."""
    if config_dir is not None:
        return [Path(config_dir).expanduser()]
    env = os.environ.get("JOBWATCH_CONFIG_DIR")
    if env:
        return [Path(env).expanduser()]
    from . import users
    runtime = users.config_dir()
    return [runtime, DEFAULT_CONFIG_DIR] if runtime is not None else [DEFAULT_CONFIG_DIR]

def _first_file(sources: list[Path], name: str) -> Path | None:
    return next((source / name for source in sources if (source / name).is_file()), None)

def _load_first(sources: list[Path], name: str) -> Any:
    path = _first_file(sources, name)
    return _load(path) if path is not None else {}

def load_config(config_dir: str | Path | None = None) -> Config:
    sources = _config_sources(config_dir)
    cdir = sources[0]
    settings = _merge(DEFAULT_SETTINGS, _load_first(sources, "jobwatch.yaml"))
    emp_env = os.environ.get("JOBWATCH_EMPLOYERS")
    if emp_env:
        emp_path: Path | None = Path(emp_env).expanduser()
    else:
        emp_path = next((path for source in sources
                         for path in (source / "employers.yaml", source / "employers.example.yaml")
                         if path.is_file()), None)
    employers_doc = _load(emp_path) if emp_path else {}
    employers = employers_doc.get("employers", employers_doc) if isinstance(employers_doc, dict) else employers_doc
    return Config(
        config_dir=cdir,
        settings=settings,
        rules=_load_first(sources, "rules.yaml"),
        searches=_load_first(sources, "searches.yaml"),
        feeds=_load_first(sources, "feeds.yaml"),
        employers=[e for e in (employers or []) if isinstance(e, dict)],
        employers_path=emp_path,
    )
