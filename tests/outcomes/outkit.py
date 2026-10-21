"""Offline helpers for outcome tests: a fake read-only mail MCP with synthetic mail (never real)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "commands"))
from cmdkit import add_match, make_env, ledger_lines  # noqa: E402,F401


def envelope(uid, mid, subject, email, name="", date="2026-10-04 09:00:00+00:00"):
    return {"id": str(uid), "message-id": f"<{mid}>", "subject": subject,
            "from": [{"name": name, "email": email}], "to": [{"name": None, "email": "me@example.org"}],
            "date": date, "flags": [], "in-reply-to": []}


class FakeMcp:
    """search() filters the synthetic mailbox crudely like IMAP FROM/SUBJECT substring matching."""

    def __init__(self, boxes: dict[tuple[str, str], list[dict]], bodies: dict[str, str] | None = None):
        self.boxes, self.bodies = boxes, bodies or {}
        self.searches: list[tuple[str, str, str]] = []
        self.reads: list[tuple[str, str, str, int]] = []

    def list_tools(self):
        return ["inbox_search", "inbox_read_message", "inbox_list_mailboxes", "mail_compose"]

    def search(self, account, mailbox, query, page_size=50):
        self.searches.append((account, mailbox, query))
        terms = [t.strip('"').lower() for t in re.findall(r'(?:from|subject) ("[^"]+"|\S+)', query)]
        terms = [t.rstrip(")") for t in terms]
        out = []
        for env in self.boxes.get((account, mailbox), []):
            hay = (env["subject"] + " " + env["from"][0]["email"] + " " + env["from"][0]["name"]).lower()
            if any(t in hay for t in terms):
                out.append(env)
        return out

    def read_body(self, account, mailbox, msg_id, max_chars=1500):
        self.reads.append((account, mailbox, msg_id, max_chars))
        return self.bodies.get(str(msg_id), "")[:max_chars]


class FakeLLM:
    def __init__(self, data):
        self.data, self.prompts = data, []

    def chat(self, model, messages, **kw):
        self.prompts.append((model, messages))

        class R:
            pass
        r = R()
        r.data = self.data
        return r


def sse(payload: dict):
    from cmdkit import FakeResp
    return FakeResp(200, None, {"content-type": "text/event-stream"},
                    "event: message\ndata: " + json.dumps(payload) + "\n\n")
