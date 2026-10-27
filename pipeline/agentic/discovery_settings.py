"""Per-person operational settings for job discovery."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from jobwatch import users
from jobwatch.candidate import intake


class DailySettings(intake._Model):
    daily_token_ceiling: int | None = Field(gt=0)


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


def get_settings(person: str, config) -> dict:
    """Return the effective token cap; null means unlimited daily tokens."""
    override = _override(person)
    if override is not None:
        return override.model_dump(mode="json")

    confirmed = intake._confirmed_scope(person)
    if confirmed is not None:
        ceiling = confirmed.daily_token_ceiling
    else:
        from pipeline.agentic.service import _config
        with users.use(person):
            ceiling = _config(config)["batch_token_ceiling"]
    return {"daily_token_ceiling": ceiling}


def set_settings(person: str, config, daily_token_ceiling: int | None) -> dict:
    """Persist exactly one strictly validated daily-token setting for this person."""
    value = DailySettings.model_validate({"daily_token_ceiling": daily_token_ceiling}, strict=True)
    path = _path(person)
    intake._write_private(path, json.dumps(value.model_dump(mode="json"), sort_keys=True,
                                           separators=(",", ":")).encode("utf-8"))
    return value.model_dump(mode="json")


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
