"""Minimal MCP client (streamable HTTP, JSON-RPC) for the local Phrog-Assistant server.

Read-only by construction: only the tools in READ_ONLY_TOOLS can be called; anything else
(send, move, flag, delete, triage writes...) raises ToolNotAllowed before a request is made.
Mail content is never logged.
"""
from __future__ import annotations

import itertools
import json
from urllib.parse import urlsplit

import requests

DEFAULT_URL = "http://127.0.0.1:8913/mcp"
# Himalaya-backed tools: search envelopes, read a body (never marks seen), list folders.
READ_ONLY_TOOLS = frozenset({"inbox_search", "inbox_read_message", "inbox_list_mailboxes"})


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        parts.port                                # raises ValueError on a bad port
    except ValueError:
        return False
    return (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
            and parts.username is None and parts.password is None)


class ToolNotAllowed(PermissionError):
    pass


class McpError(RuntimeError):
    pass


def _parse_body(resp) -> dict:
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        data = [line[5:].strip() for line in resp.text.splitlines() if line.startswith("data:")]
        if not data:
            raise McpError("empty event stream")
        return json.loads(data[-1])
    return resp.json()


class McpClient:
    def __init__(self, url: str = DEFAULT_URL, session=None, timeout: float = 90):
        if not _is_loopback_url(url):
            raise ValueError("the mail MCP must be local (loopback)")
        self.url = url
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session_id: str | None = None
        self._ids = itertools.count(1)
        self._ready = False

    def _post(self, payload: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        r = self.session.post(self.url, data=json.dumps(payload), headers=headers, timeout=self.timeout)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        if r.status_code == 202 or "id" not in payload:
            return None
        if r.status_code != 200:
            raise McpError(f"MCP HTTP {r.status_code}")
        return _parse_body(r)

    def _rpc(self, method: str, params: dict) -> dict:
        out = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params})
        if out is None:
            raise McpError(f"{method}: no response")
        if out.get("error"):
            raise McpError(f"{method}: {str(out['error'].get('message', ''))[:200]}")
        return out.get("result") or {}

    def initialize(self) -> dict:
        info = self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "jobwatch-outcomes", "version": "0.1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True
        return info

    def list_tools(self) -> list[str]:
        if not self._ready:
            self.initialize()
        return [t["name"] for t in self._rpc("tools/list", {}).get("tools", [])]

    def call(self, name: str, arguments: dict):
        """Call a read-only tool; returns its JSON payload (parsed from the text content)."""
        if name not in READ_ONLY_TOOLS:
            raise ToolNotAllowed(f"tool {name!r} is not on the read-only allowlist")
        if not self._ready:
            self.initialize()
        res = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if res.get("isError"):
            raise McpError(f"{name}: tool error")
        if "structuredContent" in res and isinstance(res["structuredContent"], dict) \
                and "result" not in res["structuredContent"]:
            return res["structuredContent"]
        for c in res.get("content") or []:
            if c.get("type") == "text":
                try:
                    return json.loads(c["text"])
                except ValueError:
                    return {"text": c["text"]}
        return {}

    # -- convenience -----------------------------------------------------------------
    def search(self, account: str, mailbox: str, query: str, page_size: int = 50) -> list[dict]:
        out = self.call("inbox_search", {"account": account, "mailbox": mailbox, "query": query,
                                         "page_size": min(int(page_size), 50)})
        if isinstance(out, dict) and out.get("error"):
            raise McpError(f"inbox_search failed on {account}")   # error text may hold details; not logged
        return list((out or {}).get("envelopes") or [])

    def read_body(self, account: str, mailbox: str, msg_id: str, max_chars: int = 1500) -> str:
        out = self.call("inbox_read_message", {"account": account, "mailbox": mailbox, "id": str(msg_id),
                                               "max_chars": int(max_chars)})
        return str((out or {}).get("untrusted_email") or "")[:max_chars]
