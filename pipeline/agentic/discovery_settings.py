"""Per-person operational settings for job discovery."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from jobwatch import users
from jobwatch.candidate import intake


# Per-job limits that can pause one assessment. In the file: a number = that limit, null = no limit,
# key absent = the install's default (config/jobwatch.yaml, else the built-in value).
JOB_LIMITS = ('job_token_ceiling', 'job_seconds', 'job_max_turns')
DEFAULT_MAX_TURNS = 16


class DailySettings(intake._Model):
    daily_token_ceiling: int | None = Field(gt=0)
    job_token_ceiling: int | None = Field(default=None, gt=0)
    job_seconds: int | None = Field(default=None, gt=0)
    job_max_turns: int | None = Field(default=None, gt=0)


_MISSING = object()


def _path(person: str) -> Path:
    if not users.valid_name(person):
        raise ValueError("invalid_person")
    return users.user_dir(person) / "config" / "discovery.json"


def _override(person: str) -> DailySettings | None:
    """Return a valid explicit setting; only a missing file inherits the confirmed scope."""
    try:
        value = intake._read_json(_path(person), _MISSING)
    except (OSError, ValueError, TypeError):
        raise ValueError("invalid_discovery_settings") from None
    if value is _MISSING:
        return None
    try:
        return DailySettings.model_validate(value, strict=True)
    except ValueError:
        raise ValueError("invalid_discovery_settings") from None


def job_defaults(cfg: dict) -> dict:
    """Built-in per-job limits for a person who has not changed them (cfg = service._config(config))."""
    return {'job_token_ceiling': cfg['job_token_ceiling'], 'job_seconds': int(cfg['job_seconds']),
            'job_max_turns': DEFAULT_MAX_TURNS}


def job_limits(person: str, cfg: dict) -> dict:
    """Effective per-job limits; None means unlimited. A damaged file falls back to the finite defaults."""
    values = job_defaults(cfg)
    try:
        override = _override(person)
    except ValueError:
        return values
    if override is not None:
        for key in override.model_fields_set & set(JOB_LIMITS):
            values[key] = getattr(override, key)
    return values


def get_settings(person: str, config) -> dict:
    """Return the effective daily token cap and per-job limits; null means unlimited."""
    from pipeline.agentic.service import _config
    with users.use(person):
        jobs = job_limits(person, _config(config))
    return {**_daily(person, config), **jobs}


def _daily(person: str, config) -> dict:
    override = _override(person)
    if override is not None:
        return {'daily_token_ceiling': override.daily_token_ceiling}

    confirmed = intake._confirmed_scope(person)
    if confirmed is not None:
        ceiling = confirmed.daily_token_ceiling
    else:
        from pipeline.agentic.service import _config
        with users.use(person):
            ceiling = _config(config)["batch_token_ceiling"]
    return {"daily_token_ceiling": ceiling}


def set_settings(person: str, config, daily_token_ceiling: int | None, **job_limits_: int | None) -> dict:
    """Persist this person's strictly validated settings. A per-job limit that is not passed keeps its
    stored value (or the default); passing None stores "unlimited"."""
    if set(job_limits_) - set(JOB_LIMITS):
        raise ValueError("invalid_discovery_settings")
    stored = {}
    try:
        previous = _override(person)
    except ValueError:
        previous = None
    if previous is not None:
        stored = {k: getattr(previous, k) for k in previous.model_fields_set & set(JOB_LIMITS)}
    stored.update(job_limits_)
    value = DailySettings.model_validate({"daily_token_ceiling": daily_token_ceiling, **stored}, strict=True)
    intake._write_private(_path(person), json.dumps(value.model_dump(mode="json", exclude_unset=True),
                                                    sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return get_settings(person, config)


def allowance(daily_token_ceiling: int | None, spent: int, per_run_cap: int) -> int:
    """Per-run allowance bounded by configuration and, when finite, the remaining daily balance."""
    if (daily_token_ceiling is not None and (type(daily_token_ceiling) is not int or daily_token_ceiling <= 0)
            or type(spent) is not int or spent < 0 or type(per_run_cap) is not int or per_run_cap <= 0):
        raise ValueError("invalid_token_allowance")
    if daily_token_ceiling is None:
        return per_run_cap
    return max(0, min(per_run_cap, daily_token_ceiling - spent))


def allowance_reason(daily_token_ceiling: int | None, spent: int, per_run_cap: int) -> str:
    """Classify which cap sets the effective allowance when a model call is refused."""
    allowance(daily_token_ceiling, spent, per_run_cap)  # validates all three inputs
    if daily_token_ceiling is not None and daily_token_ceiling - spent <= per_run_cap:
        return 'daily_budget'
    return 'run_budget'
