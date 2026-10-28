"""Small Gmail helpers on the person's own token. There is no send function, on purpose."""
from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import getaddresses

import requests

from jobwatch.google import oauth as google_oauth

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _call(method: str, path: str, **kw) -> dict:
    r = requests.request(method, API + path, timeout=30,
                         headers={"Authorization": f"Bearer {google_oauth.access_token()}"}, **kw)
    if r.status_code >= 300:
        raise RuntimeError(f"Gmail API {r.status_code}")
    return r.json() if r.content else {}


def search_messages(query: str, max_results: int = 50) -> list[str]:
    out = _call("GET", "/messages", params={"q": query, "maxResults": max_results})
    return [m["id"] for m in out.get("messages", [])]


def get_message(msg_id: str, full: bool = False) -> dict:
    return _call("GET", f"/messages/{msg_id}", params={"format": "full" if full else "metadata"})


def create_draft(to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
    m = EmailMessage()
    m["To"], m["Subject"] = to, subject
    m.set_content(body)
    msg = {"raw": base64.urlsafe_b64encode(m.as_bytes()).decode()}
    if thread_id:
        msg["threadId"] = thread_id
    return _call("POST", "/drafts", json={"message": msg})


def archive(msg_id: str) -> dict:
    return _call("POST", f"/messages/{msg_id}/modify", json={"removeLabelIds": ["INBOX"]})


def trash(msg_id: str) -> dict:
    return _call("POST", f"/messages/{msg_id}/trash")


# -- adapter so outcomes/sync.py can use it like the MCP client ------------------------------------
def to_gmail_query(q: str) -> str:
    """Turn the sync.py query syntax (from "x" or subject "y" and after 2026-01-01) into Gmail's."""
    q = re.sub(r'\b(from|subject) ("[^"]*"|\S+)', r"\1:\2", q)
    q = re.sub(r"\bafter (\d{4})-(\d\d)-(\d\d)", r"after:\1/\2/\3", q)
    return q.replace(" and ", " ").replace(" or ", " OR ")


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _text(part: dict) -> str:
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"] + "==").decode("utf-8", "replace")
    return "".join(_text(p) for p in part.get("parts", []))


class GmailMcp:
    """Same three calls sync.scan uses on McpClient, backed by the person's Gmail."""

    def list_tools(self):
        return ["gmail"]

    def search(self, account: str, mailbox: str, query: str, page_size: int = 50) -> list[dict]:
        out = []
        for mid in search_messages(to_gmail_query(query), page_size):
            msg = get_message(mid)
            name_addr = (getaddresses([_header(msg, "From")]) or [("", "")])[0]
            out.append({"id": mid, "message-id": _header(msg, "Message-ID") or mid,
                        "subject": _header(msg, "Subject"), "date": _header(msg, "Date"),
                        "from": [{"name": name_addr[0], "email": name_addr[1]}]})
        return out

    def read_body(self, account: str, mailbox: str, msg_id: str, max_chars: int = 1500) -> str:
        return _text(get_message(msg_id, full=True).get("payload", {}))[:max_chars]
