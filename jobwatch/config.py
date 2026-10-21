"""Load the YAML config files. Paths can be overridden with environment variables:

JOBWATCH_CONFIG_DIR  directory holding jobwatch.yaml, rules.yaml, searches.yaml, feeds.yaml
JOBWATCH_EMPLOYERS   employers file (default <config>/employers.yaml, falling back to
                     employers.example.yaml when the real registry is absent)
JOBWATCH_DB          SQLite path (default from jobwatch.yaml, ~/.local/share/jobwatch/jobwatch.db)
"""
from __future__ import annotations

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


def _load(path: Path) -> Any:
    if not path.is_file():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


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
        from . import users
        if users.current() != users.DEFAULT_USER:       # another person: their own DB
            return users.db_path()
        return Path(os.path.expanduser(_setting("JOBWATCH_DB") or self.settings["db_path"]))

    def employers_for(self, provider: str) -> list[dict]:
        return [e for e in self.employers
                if e.get("enabled", True) and str(e.get("provider", "")).lower() == provider]


def load_config(config_dir: str | Path | None = None) -> Config:
    cdir = Path(config_dir or os.environ.get("JOBWATCH_CONFIG_DIR") or DEFAULT_CONFIG_DIR).expanduser()
    settings = _merge(DEFAULT_SETTINGS, _load(cdir / "jobwatch.yaml"))
    emp_env = os.environ.get("JOBWATCH_EMPLOYERS")
    if emp_env:
        emp_path: Path | None = Path(emp_env).expanduser()
    elif (cdir / "employers.yaml").is_file():
        emp_path = cdir / "employers.yaml"
    elif (cdir / "employers.example.yaml").is_file():
        emp_path = cdir / "employers.example.yaml"
    else:
        emp_path = None
    employers_doc = _load(emp_path) if emp_path else {}
    employers = employers_doc.get("employers", employers_doc) if isinstance(employers_doc, dict) else employers_doc
    from . import users           # another person's own rules/searches (TASK-111)
    ucdir = users.config_dir() if users.current() != users.DEFAULT_USER and not config_dir else None
    return Config(
        config_dir=cdir,
        settings=settings,
        rules=_load((ucdir or cdir) / "rules.yaml"),
        searches=_load((ucdir or cdir) / "searches.yaml"),
        feeds=_load(cdir / "feeds.yaml"),
        employers=[e for e in (employers or []) if isinstance(e, dict)],
        employers_path=emp_path,
    )
