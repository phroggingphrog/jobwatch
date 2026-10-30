"""Cloudflare Access is verified, never trusted, and an unmapped email is refused rather than guessed."""
import base64
import time

import pytest

pytest.importorskip("fastmcp")

jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa                          # noqa: E402

from pipeline.agentic import mcp_access                                            # noqa: E402

TEAM = "team.cloudflareaccess.com"
AUD = "aud-tag-123"
ISSUER = f"https://{TEAM}"


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def signing():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    jwks = {"keys": [{"kid": "k1", "kty": "RSA", "n": _b64u(numbers.n), "e": _b64u(numbers.e)}]}
    return key, jwks


def _token(key, **over):
    claims = {"email": "Owner@Example.com", "sub": "user-1", "aud": AUD, "iss": ISSUER,
              "iat": int(time.time()) - 5, "exp": int(time.time()) + 300}
    claims.update(over)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": over.pop("kid", "k1") if "kid" in over else "k1"})


def test_keys_parse_and_a_valid_assertion_is_accepted(signing):
    key, jwks = signing
    keys = mcp_access.keys_from_jwks(jwks)
    assert set(keys) == {"k1"}
    identity = mcp_access.verify_access_jwt(_token(key), keys=keys, audience=AUD, issuer=ISSUER)
    assert identity.email == "owner@example.com" and identity.subject == "user-1"


@pytest.mark.parametrize("override, code", [
    ({"exp": int(time.time()) - 600}, "access_token_expired"),
    ({"aud": "someone-else"}, "access_audience_invalid"),
    ({"iss": "https://evil.cloudflareaccess.com"}, "access_issuer_invalid"),
    ({"email": None}, "access_email_missing"),
])
def test_bad_assertions_are_refused_with_a_reason(signing, override, code):
    key, jwks = signing
    keys = mcp_access.keys_from_jwks(jwks)
    with pytest.raises(mcp_access.AccessError) as caught:
        mcp_access.verify_access_jwt(_token(key, **override), keys=keys, audience=AUD, issuer=ISSUER)
    assert caught.value.code == code


def test_an_unknown_key_or_a_forged_signature_is_refused(signing):
    key, jwks = signing
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = mcp_access.keys_from_jwks(jwks)
    with pytest.raises(mcp_access.AccessError) as caught:
        mcp_access.verify_access_jwt(_token(other), keys=keys, audience=AUD, issuer=ISSUER)
    assert caught.value.code in ("access_token_invalid", "access_key_unknown")
    with pytest.raises(mcp_access.AccessError) as caught:
        mcp_access.verify_access_jwt(_token(key), keys={}, audience=AUD, issuer=ISSUER)
    assert caught.value.code == "access_key_unknown"


def test_an_unmapped_email_is_refused_not_defaulted():
    assert mcp_access.person_for_email("owner@example.com", {"owner@example.com": "owner"}) == "owner"
    with pytest.raises(mcp_access.AccessError) as caught:
        mcp_access.person_for_email("stranger@example.com", {"owner@example.com": "owner"})
    assert caught.value.code == "access_person_unmapped"
    with pytest.raises(mcp_access.AccessError):
        mcp_access.person_for_email("owner@example.com", {"owner@example.com": "not a valid name!"})


@pytest.mark.parametrize("env, enabled, requires_jwt", [
    ({}, False, False),
    ({"JOBWATCH_MCP_ACCESS": "off"}, False, False),
    ({"JOBWATCH_MCP_ACCESS": "jwt", "JOBWATCH_MCP_ACCESS_AUD": AUD}, True, True),
    ({"JOBWATCH_MCP_ACCESS": "auto", "JOBWATCH_MCP_ACCESS_AUD": AUD}, True, False),
    ({"JOBWATCH_MCP_ACCESS": "auto"}, False, False),          # no audience: incomplete is off, never open
])
def test_misconfiguration_turns_access_off_instead_of_open(env, enabled, requires_jwt):
    env = {"JOBWATCH_MCP_ACCESS_TEAM": TEAM, **env}
    settings = mcp_access.settings_from_env(env, fetch=False)
    assert settings.enabled is enabled and settings.requires_jwt is requires_jwt


def test_the_verifier_accepts_either_proof_and_nothing_else(signing):
    """The static token stays the local path; the Access assertion is the public path."""
    import asyncio
    from pipeline.agentic import mcp_server

    key, jwks = signing
    settings = mcp_access.AccessSettings(mode="auto", team_domain=TEAM, audience=AUD,
                                         mapping={"owner@example.com": "owner"},
                                         keys=mcp_access.keys_from_jwks(jwks), fetched_at=0.0)
    verifier = mcp_server._JobwatchTokenVerifier("s" * 40, "owner", settings)
    verify = lambda token: asyncio.run(verifier.verify_token(token))

    assert verify("s" * 40).subject == "owner"                      # local static token
    access = verify(_token(key))
    assert access is not None and access.subject == "owner"          # public Access assertion
    assert access.claims["email"] == "owner@example.com"

    unmapped = verify(_token(key, email="stranger@example.com"))
    assert unmapped is None                                          # never guessed
    assert verify("forged") is None
    assert verify("") is None


def test_jwt_only_mode_refuses_the_static_token(signing):
    import asyncio
    from pipeline.agentic import mcp_server

    key, jwks = signing
    settings = mcp_access.AccessSettings(mode="jwt", team_domain=TEAM, audience=AUD,
                                         mapping={"owner@example.com": "owner"},
                                         keys=mcp_access.keys_from_jwks(jwks), fetched_at=0.0)
    verifier = mcp_server._JobwatchTokenVerifier(None, "owner", settings)
    assert asyncio.run(verifier.verify_token("anything")) is None
    assert asyncio.run(verifier.verify_token(_token(key))).subject == "owner"


def test_any_audience_is_opt_in_and_still_checks_signature_and_issuer(signing):
    """The AUD tag is dashboard-only. An operator may waive it explicitly; the rest still holds."""
    team = TEAM
    off = mcp_access.settings_from_env({"JOBWATCH_MCP_ACCESS": "auto", "JOBWATCH_MCP_ACCESS_TEAM": team}, fetch=False)
    assert off.enabled is False                       # default is still closed
    on = mcp_access.settings_from_env({"JOBWATCH_MCP_ACCESS": "auto", "JOBWATCH_MCP_ACCESS_TEAM": team,
                                       "JOBWATCH_MCP_ACCESS_ANY_AUD": "1"}, fetch=False)
    assert on.enabled is True and on.any_audience is True

    key, jwks = signing
    keys = mcp_access.keys_from_jwks(jwks)
    identity = mcp_access.verify_access_jwt(_token(key, aud="some-other-app"),
                                            keys=keys, audience=None, issuer=ISSUER)
    assert identity.email == "owner@example.com"
    # Signature and issuer are still enforced with the audience waived.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(mcp_access.AccessError):
        mcp_access.verify_access_jwt(_token(other), keys=keys, audience=None, issuer=ISSUER)
    with pytest.raises(mcp_access.AccessError) as caught:
        mcp_access.verify_access_jwt(_token(key, iss="https://evil.cloudflareaccess.com"),
                                     keys=keys, audience=None, issuer=ISSUER)
    assert caught.value.code == "access_issuer_invalid"


def test_the_access_header_becomes_the_bearer_the_verifier_checks():
    """Cloudflare proves identity; the origin only moves that proof to where it already verifies it."""
    import asyncio
    from pipeline.agentic.mcp_server import _AccessHeaderMiddleware

    seen = {}

    async def app(scope, receive, send):
        seen["headers"] = dict(scope["headers"])

    scope = {"type": "http", "headers": [(b"host", b"x"), (b"cf-access-jwt-assertion", b"THE-JWT")]}
    asyncio.run(_AccessHeaderMiddleware(app)(scope, None, None))
    assert seen["headers"][b"authorization"] == b"Bearer THE-JWT"

    # A client-supplied Authorization is replaced, never duplicated: the edge proof wins.
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer mine"), (b"cf-access-jwt-assertion", b"EDGE")]}
    asyncio.run(_AccessHeaderMiddleware(app)(scope, None, None))
    assert seen["headers"][b"authorization"] == b"Bearer EDGE"

    # No forwarded assertion: untouched, so an ordinary bearer still works.
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer mine")]}
    asyncio.run(_AccessHeaderMiddleware(app)(scope, None, None))
    assert seen["headers"][b"authorization"] == b"Bearer mine"
