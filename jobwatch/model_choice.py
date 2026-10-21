"""Which model does which job, per person (Models settings page).

get_model(role, user) answers in this order: the person's own pick (<their folder>/config/models.json),
then config/jobwatch.yaml, then the built-in default. Each person can also bring their own gateway
(base URL + API key, OpenAI-compatible) kept in <their folder>/config/gateway.json, mode 0600.
The key is never logged and never shown back in full.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import users
from .settings import get as _setting

from .settings import DEFAULT_MODEL  # noqa: E402
SERVER_URL = _setting("JOBWATCH_LLM_BASE_URL", "https://api.openai.com/v1")

# role -> (words on the page, where config/jobwatch.yaml keeps it)
ROLES = {
    "reader": ("Reads and scores ads", ("reader", "model")),
    "evaluator": ("Judges how well you fit", ("pipeline", "agentic", "evaluator_model")),
    "writer": ("Writes CV + letter", ("pipeline", "agentic", "worker_model")),
    "reviewer": ("Checks the letter", ("pipeline", "agentic", "reviewer_model")),
    "chat": ("Answers chat", ("chat", "model")),
    "answers": ("Fills form answers", ("pipeline", "agentic", "answer_model")),
}

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,120}$")


class ModelRefused(ValueError):
    pass


def _cfg_dir(user: str | None) -> Path:
    return users.user_dir(user) / "config"


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


# -- id check (no blocking: any person can pick any model) -------------------------------------
def refusal(model: str, role: str | None = None, user: str | None = None) -> str | None:
    """Plain-words reason this is not a usable model id, or None."""
    m = (model or "").strip()
    if not _ID.match(m) or ".." in m:
        return "Not a valid model id."
    return None


def check(model: str, role: str | None = None, user: str | None = None) -> str:
    why = refusal(model, role, user)
    if why:
        raise ModelRefused(why)
    return model.strip()


# -- choices -----------------------------------------------------------------------------------
def _from_config(role: str) -> str | None:
    try:
        from .config import load_config
        node = load_config().settings or {}
        for key in ROLES[role][1]:
            node = node.get(key) if isinstance(node, dict) else None
        return node if isinstance(node, str) and node else None
    except Exception:
        return None


def chosen(user: str | None = None) -> dict:
    return {k: v for k, v in _read(_cfg_dir(user) / "models.json").items() if k in ROLES and isinstance(v, str)}


def get_model(role: str, user: str | None = None) -> str:
    if role not in ROLES:
        raise KeyError(role)
    return chosen(user).get(role) or _from_config(role) or DEFAULT_MODEL


def set_models(picks: dict, user: str | None = None) -> None:
    """Save picks (role -> model). An empty value clears the pick. Raises ModelRefused on a blocked one."""
    cur = chosen(user)
    for role, model in picks.items():
        if role not in ROLES:
            continue
        model = (model or "").strip()
        if not model or model == (_from_config(role) or DEFAULT_MODEL):   # same as the default = no pick
            cur.pop(role, None)
        else:
            cur[role] = check(model, role, user)
    _write_private(_cfg_dir(user) / "models.json", cur)


# -- own gateway + key -------------------------------------------------------------------------
def valid_url(url: str) -> bool:
    return bool(re.match(r"^(https://[A-Za-z0-9.-]+|http://(127\.0\.0\.1|localhost))(:\d+)?(/[A-Za-z0-9._~/-]*)?$", url or ""))


def own_gateway(user: str | None = None) -> tuple[str, str] | None:
    d = _read(_cfg_dir(user) / "gateway.json")
    if d.get("base_url") and d.get("api_key"):
        return d["base_url"].rstrip("/"), d["api_key"]
    return None


def gateway_url(user: str | None = None) -> str:
    g = own_gateway(user)
    return g[0] if g else SERVER_URL


def own_key(user: str | None = None) -> str | None:
    g = own_gateway(user)
    return g[1] if g else None


def set_gateway(base_url: str, api_key: str, user: str | None = None) -> None:
    """Save the person's own gateway. Empty key keeps the old key; both empty removes it."""
    base_url = (base_url or "").strip().rstrip("/")
    path = _cfg_dir(user) / "gateway.json"
    if not base_url and not api_key.strip():
        path.unlink(missing_ok=True)
        return
    if not valid_url(base_url):
        raise ValueError("Base URL must start with https:// (or be a local http://127.0.0.1 address).")
    key = api_key.strip() or (_read(path).get("api_key") or "")
    if not key or any(c.isspace() for c in key):
        raise ValueError("Enter your API key.")
    _write_private(path, {"base_url": base_url, "api_key": key})


def gateway_view(user: str | None = None) -> dict:
    g = own_gateway(user)
    return {"own": bool(g), "base_url": g[0] if g else SERVER_URL, "key_tail": g[1][-4:] if g else ""}
