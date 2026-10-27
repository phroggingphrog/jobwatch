"""Transports. A channel is built from a stored config and sends one event.

Secrets never live in a config. A key ending in `_ref` points at one: `env:NAME` (a setting or environment
variable) or `file:/path` (first line of a file). Receipts carry short fixed codes only, so no address, URL, token or
message text reaches a log, the database or the screen from here.
"""
from __future__ import annotations

import json
import logging
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .events import Event

log = logging.getLogger(__name__)
TIMEOUT = 20
_SECRETISH = re.compile(r"token|secret|passw|api_?key|credential|auth|bearer", re.I)


@dataclass(frozen=True)
class Receipt:
    status: str            # 'delivered' | 'failed'
    detail: str = ""       # short fixed code: ok, not_configured, timeout, exit_255, http_500 ...
    at: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "delivered"


def _receipt(ok: bool, detail: str) -> Receipt:
    return Receipt("delivered" if ok else "failed", detail, time.time())


class Channel(Protocol):
    kind: str

    def send(self, event: Event) -> Receipt: ...

    def healthy(self) -> bool: ...


def resolve_ref(ref: str | None) -> str:
    """'env:NAME' or 'file:/path' -> the secret value, or '' when it is not available."""
    if not ref or ":" not in ref:
        return ""
    scheme, _, target = ref.partition(":")
    if scheme == "env":
        from jobwatch import settings
        return settings.get(target).strip()
    if scheme == "file":
        try:
            return Path(target).expanduser().read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError):
            return ""
    return ""


def value(config: dict, name: str) -> str:
    """A plain config value, or the secret its `<name>_ref` points at."""
    plain = config.get(name)
    return str(plain).strip() if plain else resolve_ref(config.get(name + "_ref"))


class NoneChannel:
    kind = "none"

    def __init__(self, name: str, config: dict):
        self.name = name

    def send(self, event: Event) -> Receipt:
        return _receipt(False, "no_transport")

    def healthy(self) -> bool:
        return False


class SshAppendChannel:
    """Append the line to a file on another machine: `ssh host 'cat >> file'`."""
    kind = "ssh_append"

    def __init__(self, name: str, config: dict):
        self.name = name
        self.host, self.file = value(config, "host"), value(config, "file")

    def healthy(self) -> bool:
        return bool(self.host and self.file and not self.host.startswith("-"))

    @staticmethod
    def _quote(path: str) -> str:
        return "~/" + shlex.quote(path[2:]) if path.startswith("~/") else shlex.quote(path)

    def send(self, event: Event) -> Receipt:
        if not self.healthy():
            return _receipt(False, "not_configured")
        try:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "--", self.host,
                                f"cat >> {self._quote(self.file)}"],
                               input=event.line + "\n", text=True, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return _receipt(False, "timeout")
        except (OSError, subprocess.SubprocessError):
            return _receipt(False, "transport_error")
        return _receipt(r.returncode == 0, "ok" if r.returncode == 0 else f"exit_{r.returncode}")


class CommandChannel:
    """Run a local command (argv list, no shell) and give it the message on stdin."""
    kind = "command"

    def __init__(self, name: str, config: dict):
        self.name = name
        argv = config.get("argv")
        self.argv = [str(a) for a in argv] if isinstance(argv, list) and argv else []

    def healthy(self) -> bool:
        return bool(self.argv and shutil.which(self.argv[0]))

    def send(self, event: Event) -> Receipt:
        if not self.healthy():
            return _receipt(False, "not_configured")
        try:
            r = subprocess.run(self.argv, input=event.line + "\n", text=True, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return _receipt(False, "timeout")
        except (OSError, subprocess.SubprocessError):
            return _receipt(False, "transport_error")
        return _receipt(r.returncode == 0, "ok" if r.returncode == 0 else f"exit_{r.returncode}")


class WebhookChannel:
    """POST the event as JSON to a URL kept in a secret reference."""
    kind = "webhook"

    def __init__(self, name: str, config: dict):
        self.name = name
        self.url = value(config, "url")

    def healthy(self) -> bool:
        return self.url.startswith(("https://", "http://"))

    def send(self, event: Event) -> Receipt:
        if not self.healthy():
            return _receipt(False, "not_configured")
        body = json.dumps({"source": "jobwatch", **event.to_dict()}).encode()
        req = urllib.request.Request(self.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "jobwatch"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:       # noqa: S310 - owner-configured URL
                return _receipt(200 <= resp.status < 300, f"http_{resp.status}")
        except urllib.error.HTTPError as exc:
            return _receipt(False, f"http_{exc.code}")
        except (OSError, ValueError):
            return _receipt(False, "network_error")


KINDS: dict[str, Callable[[str, dict], Channel]] = {
    "none": NoneChannel, "ssh_append": SshAppendChannel, "command": CommandChannel, "webhook": WebhookChannel,
}
# keys each kind accepts (plus their `_ref` forms where listed)
ALLOWED = {"none": set(), "ssh_append": {"host", "host_ref", "file", "file_ref"}, "command": {"argv"},
           "webhook": {"url_ref"}}


def register_kind(kind: str, factory: Callable[[str, dict], Channel], allowed_keys: set[str] | None = None) -> None:
    """Plug in another transport (a chat-bot service, a mail relay...). Keys ending in `_ref` stay secret references."""
    KINDS[kind] = factory
    ALLOWED[kind] = set(allowed_keys or ())


def build(kind: str, name: str, config: dict) -> Channel:
    if kind not in KINDS:
        raise ValueError("unknown_channel_kind")
    return KINDS[kind](name, config)


def validate_config(kind: str, config: dict) -> dict:
    """Reject unknown keys and any literal that looks like a credential (it must be a `_ref`)."""
    if kind not in KINDS:
        raise ValueError("unknown_channel_kind")
    if not isinstance(config, dict):
        raise ValueError("config_must_be_an_object")
    for key, val in config.items():
        if key not in ALLOWED[kind]:
            raise ValueError(f"config_key_not_allowed:{key}")
        if key.endswith("_ref"):
            if not isinstance(val, str) or not re.fullmatch(r"(env:[A-Za-z_][A-Za-z0-9_]*|file:/.+|file:~/.+)", val):
                raise ValueError(f"bad_secret_reference:{key}")
        elif _SECRETISH.search(key):
            raise ValueError(f"secret_must_be_a_reference:{key}")
        elif isinstance(val, str) and re.search(r"://[^/\s]*:[^/\s]*@", val):
            raise ValueError(f"secret_must_be_a_reference:{key}")
    if kind == "ssh_append" and not (("host" in config or "host_ref" in config) and ("file" in config or "file_ref" in config)):
        raise ValueError("ssh_append_needs_host_and_file")
    if kind == "command" and not (isinstance(config.get("argv"), list) and config["argv"]):
        raise ValueError("command_needs_argv")
    if kind == "webhook" and "url_ref" not in config:
        raise ValueError("webhook_needs_url_ref")
    return config
