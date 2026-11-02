"""Sign-in for multi-person Jobwatch: /login, /signup, /logout and the middleware behind them.

Off unless JOBWATCH_SESSION_SECRET is set (then the site behaves as before, owner only).
Passwords: scrypt in <base_dir>/users.json (mode 600). Session: HMAC-signed cookie.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import users

HERE = Path(__file__).parent
COOKIE = "jw_session"
MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = ("/login", "/signup", "/static", "/healthz")   # the health check needs no sign-in


def _secret() -> bytes | None:
    s = os.environ.get("JOBWATCH_SESSION_SECRET")
    return s.encode() if s else None


# -- passwords ---------------------------------------------------------------------------------
def _users_file() -> Path:
    return users.base_dir() / "users.json"


def _load() -> dict:
    try:
        return json.loads(_users_file().read_text())
    except (OSError, ValueError):
        return {}


def _hash(pw: str, salt: bytes) -> str:
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, maxmem=64 * 1024 * 1024).hex()


def set_password(name: str, pw: str) -> None:
    if not users.valid_name(name):
        raise ValueError(f"bad user name: {name!r}")
    salt = secrets.token_bytes(16)
    data = _load()
    data[name] = {"salt": salt.hex(), "hash": _hash(pw, salt)}
    f = _users_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    os.replace(tmp, f)


def check_password(name: str, pw: str) -> bool:
    data = _load()
    rec = data.get(name)
    if rec is None and name == users.DEFAULT_USER and os.environ.get("JOBWATCH_OWNER_PASSWORD"):
        # first account: the env password becomes its stored password
        if hmac.compare_digest(pw, os.environ["JOBWATCH_OWNER_PASSWORD"]):
            set_password(name, pw)
            return True
        return False
    if rec is None:
        _hash(pw, b"0" * 16)  # same time whether or not the name exists
        return False
    return hmac.compare_digest(_hash(pw, bytes.fromhex(rec["salt"])), rec["hash"])


# -- session cookie ----------------------------------------------------------------------------
def make_cookie(name: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"u": name, "exp": int(time.time()) + MAX_AGE}).encode()).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_cookie(value: str | None) -> str | None:
    secret = _secret()
    if not value or not secret or "." not in value:
        return None
    body, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(body.encode()))
    except ValueError:
        return None
    name = d.get("u")
    return name if d.get("exp", 0) > time.time() and users.valid_name(name) else None


# -- pages + middleware ------------------------------------------------------------------------
def install_auth(app: FastAPI) -> None:
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    mode = os.environ.get("JOBWATCH_WEB_AUTH_MODE", "").strip().lower()
    if mode not in {"", "single_user"}:
        raise RuntimeError("invalid_jobwatch_web_auth_mode")
    single_user = mode == "single_user"

    def page(request: Request, name: str, error: str = "", status: int = 200, **ctx):
        return templates.TemplateResponse(request, name, {"error": error, **ctx}, status_code=status)

    def sign_in(request: Request, name: str) -> RedirectResponse:
        r = RedirectResponse("/", status_code=303)
        r.set_cookie(COOKIE, make_cookie(name), max_age=MAX_AGE, httponly=True, samesite="lax",
                     secure=request.url.scheme == "https")
        return r

    @app.get("/login")
    async def login_form(request: Request):
        return page(request, "login.html", signup_open=bool(os.environ.get("JOBWATCH_INVITE_CODE")))

    @app.post("/login")
    async def login(request: Request, username: str = Form(""), password: str = Form("")):
        name = username.strip().lower()
        if _secret() and users.valid_name(name) and check_password(name, password):
            return sign_in(request, name)
        return page(request, "login.html", "That name and password do not match. Try again.", 401,
                    username=username, signup_open=bool(os.environ.get("JOBWATCH_INVITE_CODE")))

    @app.get("/signup")
    async def signup_form(request: Request):
        return page(request, "signup.html", open=bool(os.environ.get("JOBWATCH_INVITE_CODE")))

    @app.post("/signup")
    async def signup(request: Request, username: str = Form(""), password: str = Form(""),
                     invite: str = Form("")):
        code, name = os.environ.get("JOBWATCH_INVITE_CODE"), username.strip().lower()
        def fail(msg, status=400):
            return page(request, "signup.html", msg, status, username=username, open=bool(code))
        if not code:
            return fail("Sign-up is closed right now.", 403)
        if not _secret():
            return fail("Sign-in is not switched on yet.", 403)
        if not hmac.compare_digest(invite.strip(), code):
            return fail("That invite code is not right.", 403)
        if not users.valid_name(name):
            return fail("Pick a name of 2 to 31 letters, numbers, - or _, starting with a letter.")
        if len(password) < 8:
            return fail("Use a password of at least 8 characters.")
        if name in _load() or name == users.DEFAULT_USER:
            return fail("That name is taken. Try another.", 409)
        set_password(name, password)
        users.create_user_dirs(name)
        return sign_in(request, name)

    @app.post("/logout")
    async def logout():
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie(COOKIE)
        return r

    @app.middleware("http")
    async def auth(request, call_next):
        if single_user:
            if request.url.path in {"/login", "/signup", "/logout"}:
                return RedirectResponse("/", status_code=303)
            # Use only the configured stable owner. Never map client headers or cookies to a person.
            with users.use(users.DEFAULT_USER):
                return await call_next(request)
        if not _secret():                                   # auth off: exactly as before
            return await call_next(request)
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in OPEN_PATHS):
            return await call_next(request)
        name = read_cookie(request.cookies.get(COOKIE))
        if name is None:
            if (request.headers.get("hx-request") or path.startswith("/api/")     # fetch sends */*: a redirect reads as success
                    or "application/json" in request.headers.get("accept", "")):
                return JSONResponse({"error": "sign in required"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        with users.use(name):
            return await call_next(request)
