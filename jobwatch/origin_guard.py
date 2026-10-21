"""Origin guard for HTTP surfaces (PLAN-apply D10; the web board uses check_web_host/check_web_post).

If jobwatch ever listens on HTTP it must:
  1. bind a loopback address only           -> check_bind(host)
  2. reject requests whose Host is not loopback, or whose Origin/Referer is cross-origin or
     non-loopback                           -> check_request(headers, port)
"""
from __future__ import annotations

import os
import ipaddress
from urllib.parse import urlsplit

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class OriginRejected(PermissionError):
    pass


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    if h in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def check_bind(host: str) -> str:
    """Only loopback binds are allowed (0.0.0.0, ::, LAN or public addresses are refused)."""
    if not is_loopback_host(host):
        raise OriginRejected(f"refusing to bind non-loopback address {host!r}")
    return host


def _split_host_port(value: str) -> tuple[str, int | None]:
    v = value.strip()
    if v.startswith("["):  # [::1]:8080
        host, _, rest = v[1:].partition("]")
        port = rest.lstrip(":")
        return host, int(port) if port.isdigit() else None
    if v.count(":") == 1:
        host, port = v.split(":")
        return host, int(port) if port.isdigit() else None
    return v, None


def check_request(headers: dict, port: int) -> None:
    """Validate Host and Origin (or Referer). Raises OriginRejected on any doubt.

    * Host must be present, loopback, and on our port (DNS-rebinding defence).
    * Origin (or Referer when Origin is absent) is optional (curl/CLI), but if present it must be
      http(s)://<loopback>:<our port>; the literal "null" origin is rejected.
    """
    h = {k.lower(): v for k, v in (headers or {}).items()}
    host_hdr = h.get("host")
    if not host_hdr:
        raise OriginRejected("missing Host header")
    host, hport = _split_host_port(host_hdr)
    if not is_loopback_host(host):
        raise OriginRejected(f"non-loopback Host {host!r}")
    if hport is not None and hport != port:
        raise OriginRejected("Host port mismatch")
    origin = h.get("origin")
    source = origin if origin is not None else h.get("referer")
    if source is None:
        return
    if source.strip().lower() == "null":
        raise OriginRejected("opaque (null) Origin")
    parts = urlsplit(source)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OriginRejected("malformed Origin")
    if not is_loopback_host(parts.hostname):
        raise OriginRejected(f"cross-origin request from {parts.hostname!r}")
    oport = parts.port or (443 if parts.scheme == "https" else 80)
    if oport != port:
        raise OriginRejected("cross-origin request (port differs)")


# -- web board (BUI-91) -------------------------------------------------------------------
# The board binds loopback only and may be published under JOBWATCH_PUBLIC_HOST through the
# Cloudflare tunnel (behind Access), so the public name is allowed alongside loopback names.
from .settings import get as _setting
WEB_HOSTS = tuple(h for h in (_setting("JOBWATCH_PUBLIC_HOST"), "localhost", "127.0.0.1") if h)


def _host_only(value: str) -> str:
    return _split_host_port(value or "")[0].strip().lower().rstrip(".")


def check_web_host(headers: dict, allowed=WEB_HOSTS) -> None:
    """Every request: the Host header must name the board (DNS-rebinding defence)."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    host = _host_only(h.get("host", ""))
    if host not in allowed and not (host and is_loopback_host(host) and "127.0.0.1" in allowed):
        raise OriginRejected(f"unexpected Host {host!r}")


def check_web_post(headers: dict, allowed=WEB_HOSTS) -> None:
    """State-changing requests: Origin (or Referer when Origin is absent) is REQUIRED and its host
    must be one of `allowed`. A missing, opaque ("null") or foreign origin raises OriginRejected."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    origin = h.get("origin")
    source = origin if origin not in (None, "") else h.get("referer")
    if not source:
        raise OriginRejected("missing Origin/Referer on a state-changing request")
    if source.strip().lower() == "null":
        raise OriginRejected("opaque (null) Origin")
    parts = urlsplit(source.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OriginRejected("malformed Origin")
    if parts.hostname.lower().rstrip(".") not in allowed:
        raise OriginRejected(f"cross-origin request from {parts.hostname!r}")
