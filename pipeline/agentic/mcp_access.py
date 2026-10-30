"""Cloudflare Access identity for the Jobwatch MCP server.

Two proofs, one boundary. A client that arrives through the Cloudflare tunnel presents a short-lived Access
assertion as its bearer token, and the person comes from the verified email claim. A local client may present the
long-lived static token instead. Nothing else is accepted.

The Access JWT is verified, never trusted: signature against the team key set, audience, issuer and expiry. An
unmapped email is refused rather than guessed, because guessing would hand one person's career data to another.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from dataclasses import dataclass

JWKS_PATH = "/cdn-cgi/access/certs"
_CACHE_SECONDS = 600


class AccessError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AccessIdentity:
    email: str
    subject: str


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def keys_from_jwks(document: dict) -> dict:
    """kid -> RSA public key. Unknown or malformed entries are skipped, never guessed."""
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    keys = {}
    for entry in (document or {}).get("keys", []):
        try:
            if entry.get("kty") != "RSA":
                continue
            numbers = RSAPublicNumbers(int.from_bytes(_b64(entry["e"]), "big"),
                                       int.from_bytes(_b64(entry["n"]), "big"))
            keys[str(entry["kid"])] = numbers.public_key()
        except Exception:                                  # noqa: BLE001 - one bad key must not lose the set
            continue
    return keys


def fetch_keys(team_domain: str, *, timeout: float = 8.0, opener=None) -> dict:
    """The team's current signing keys. One bounded request; a failure is raised, not retried in a loop."""
    url = f"https://{team_domain}{JWKS_PATH}"
    get = opener or urllib.request.urlopen
    try:
        with get(url, timeout=timeout) as response:
            return keys_from_jwks(json.loads(response.read()))
    except Exception as exc:                               # noqa: BLE001
        raise AccessError("access_keys_unavailable") from None


def verify_access_jwt(token: str, *, keys: dict, audience: str | None, issuer: str,
                      now: float | None = None, leeway: int = 60) -> AccessIdentity:
    """Verify one Access assertion and return the identity it proves."""
    import jwt

    try:
        header = jwt.get_unverified_header(token)
    except Exception:                                      # noqa: BLE001
        raise AccessError("access_token_malformed") from None
    key = keys.get(str(header.get("kid"))) if keys else None
    if key is None:
        raise AccessError("access_key_unknown")
    try:
        # An empty audience is an explicit operator choice (JOBWATCH_MCP_ACCESS_ANY_AUD): the signature and the
        # issuer still prove Cloudflare minted it for this team. See README of this module for the trade-off.
        options = {"require": ["exp", "iat", "iss"] + (["aud"] if audience else []),
                   "verify_aud": bool(audience)}
        claims = jwt.decode(token, key=key, algorithms=["RS256"], audience=audience or None, issuer=issuer,
                            leeway=leeway, options=options)
    except jwt.ExpiredSignatureError:
        raise AccessError("access_token_expired") from None
    except jwt.InvalidAudienceError:
        raise AccessError("access_audience_invalid") from None
    except jwt.InvalidIssuerError:
        raise AccessError("access_issuer_invalid") from None
    except Exception:                                      # noqa: BLE001
        raise AccessError("access_token_invalid") from None
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise AccessError("access_email_missing")
    return AccessIdentity(email=email.strip().lower(), subject=str(claims.get("sub") or ""))


def person_for_email(email: str, mapping: dict) -> str:
    """The Jobwatch person this address may act as. An unmapped address is refused, never defaulted."""
    from jobwatch import users

    person = (mapping or {}).get((email or "").strip().lower())
    if not users.valid_name(person):
        raise AccessError("access_person_unmapped")
    return person


def _mapping(raw: str) -> dict:
    out = {}
    for pair in (raw or "").split(","):
        if "=" in pair:
            email, person = pair.split("=", 1)
            if email.strip() and person.strip():
                out[email.strip().lower()] = person.strip()
    return out


@dataclass(frozen=True)
class AccessSettings:
    mode: str                 # off | auto | jwt
    team_domain: str
    audience: str
    mapping: dict
    keys: dict
    fetched_at: float
    any_audience: bool = False

    @property
    def enabled(self) -> bool:
        return (self.mode in ("auto", "jwt") and bool(self.team_domain)
                and bool(self.audience or self.any_audience))

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}" if self.team_domain else ""

    @property
    def requires_jwt(self) -> bool:
        return self.mode == "jwt"


def settings_from_env(environ=None, *, fetch= True, opener=None) -> AccessSettings:
    """Read the deployment configuration. `off` keeps today's behaviour exactly."""
    environ = os.environ if environ is None else environ
    mode = (environ.get("JOBWATCH_MCP_ACCESS") or "off").strip().lower()
    team = (environ.get("JOBWATCH_MCP_ACCESS_TEAM") or "").strip()
    audience = (environ.get("JOBWATCH_MCP_ACCESS_AUD") or "").strip()
    mapping = _mapping(environ.get("JOBWATCH_MCP_EMAIL_MAP") or "")
    any_audience = (environ.get("JOBWATCH_MCP_ACCESS_ANY_AUD") or "").strip() in ("1", "true", "yes")
    keys, fetched = {}, 0.0
    settings = AccessSettings(mode=mode, team_domain=team, audience=audience, mapping=mapping,
                              keys=keys, fetched_at=fetched, any_audience=any_audience)
    if settings.enabled and fetch:
        keys = fetch_keys(team, opener=opener)
        settings = AccessSettings(mode=mode, team_domain=team, audience=audience, mapping=mapping,
                                  keys=keys, fetched_at=time.time(), any_audience=any_audience)
    return settings
