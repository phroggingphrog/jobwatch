"""Per-person Google OAuth 2.0 web flow (TASK-111 child 4). Plain HTTP, no google libs.

Needs env GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI. Tokens live in
users.user_dir()/google.json (mode 0600). There is no send scope, on purpose.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import requests

from jobwatch import users
from jobwatch.settings import load as _load_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/drive.file", "openid", "email"]
FORBIDDEN = ("gmail.send", "https://mail.google.com/")
assert not any(f in s for s in SCOPES for f in FORBIDDEN), "send / full-mail scopes are not allowed"
STATE_TTL = 600


class GoogleNotConfigured(RuntimeError):
    pass


def _env() -> tuple[str, str, str]:
    _load_settings()                       # reads settings.env and google.env next to it
    vals = [os.environ.get(k, "").strip() for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                                                    "GOOGLE_REDIRECT_URI")]
    if not all(vals):
        raise GoogleNotConfigured("needs GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI "
                                  "in .env (see SETUP.md)")
    return vals[0], vals[1], vals[2]


def configured() -> bool:
    try:
        _env()
        return True
    except GoogleNotConfigured:
        return False


# -- signed state, bound to the person ---------------------------------------------------------
def _key() -> bytes:
    return (os.environ.get("SESSION_SECRET") or _env()[1]).encode()


def make_state(user: str | None = None, now: float | None = None) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"u": user or users.current(),
                                                "t": int(now or time.time())}).encode()).decode()
    return body + "." + hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()


def check_state(state: str, now: float | None = None) -> str:
    """Return the person the state was made for, or raise ValueError."""
    try:
        body, sig = state.rsplit(".", 1)
        good = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            raise ValueError("bad signature")
        data = json.loads(base64.urlsafe_b64decode(body))
        if (now or time.time()) - int(data["t"]) > STATE_TTL:
            raise ValueError("expired")
        if not users.valid_name(data["u"]):
            raise ValueError("bad user")
        return data["u"]
    except (KeyError, TypeError, binascii_error) as exc:
        raise ValueError("bad state") from exc


try:
    from binascii import Error as binascii_error
except ImportError:  # pragma: no cover
    binascii_error = ValueError


# -- flow ------------------------------------------------------------------------------------------
def build_consent_url(state: str) -> str:
    cid, _, redirect = _env()
    scope = " ".join(SCOPES)
    assert not any(f in scope for f in FORBIDDEN)
    return AUTH_URL + "?" + urlencode({"client_id": cid, "redirect_uri": redirect, "response_type": "code",
                                       "scope": scope, "access_type": "offline", "prompt": "consent",
                                       "state": state})


def token_path(user: str | None = None):
    return users.user_dir(user) / "google.json"


def load(user: str | None = None) -> dict | None:
    try:
        return json.loads(token_path(user).read_text())
    except (OSError, ValueError):
        return None


def _save(data: dict, user: str | None = None) -> None:
    p = token_path(user)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _email_from_id_token(id_token: str) -> str:
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("email", "")
    except (IndexError, ValueError):
        return ""


def _token_request(payload: dict) -> dict:
    r = requests.post(TOKEN_URL, data=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Google token endpoint returned {r.status_code}")
    return r.json()


def exchange_code(code: str, user: str | None = None) -> dict:
    cid, secret, redirect = _env()
    tok = _token_request({"code": code, "client_id": cid, "client_secret": secret,
                          "redirect_uri": redirect, "grant_type": "authorization_code"})
    data = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", ""),
            "expires_at": int(time.time()) + int(tok.get("expires_in", 3600)),
            "scope": tok.get("scope", ""), "email": _email_from_id_token(tok.get("id_token", ""))}
    _save(data, user)
    return data


def refresh(user: str | None = None) -> dict:
    cid, secret, _ = _env()
    data = load(user) or {}
    if not data.get("refresh_token"):
        raise RuntimeError("Google is not connected for this person")
    tok = _token_request({"refresh_token": data["refresh_token"], "client_id": cid,
                          "client_secret": secret, "grant_type": "refresh_token"})
    data["access_token"] = tok["access_token"]
    data["expires_at"] = int(time.time()) + int(tok.get("expires_in", 3600))
    _save(data, user)
    return data


def access_token(user: str | None = None) -> str:
    data = load(user)
    if not data:
        raise RuntimeError("Google is not connected for this person")
    if data.get("expires_at", 0) < time.time() + 60:
        data = refresh(user)
    return data["access_token"]


def disconnect(user: str | None = None) -> None:
    try:
        token_path(user).unlink()
    except FileNotFoundError:
        pass
