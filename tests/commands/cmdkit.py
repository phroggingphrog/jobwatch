"""Offline helpers for the commands/outcomes tests: scratch DB + ledger.
(Not named conftest.py: a second conftest module would shadow tests/conftest.py imports.)"""
from __future__ import annotations

import json
from pathlib import Path

from jobwatch import db as dbm
from jobwatch.config import DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, Config, _merge


class FakeResp:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code, self.payload, self.headers, self.text = status, payload, headers or {}, text

    def json(self):
        return self.payload


def make_env(tmp_path: Path, monkeypatch, settings: dict | None = None) -> Config:
    """Scratch DB + ledger dir (never the real ~/brain), Config."""
    data = tmp_path / "data"
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(data))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(tmp_path / "profile"))
    base = _merge(DEFAULT_SETTINGS, {"db_path": str(data / "jobwatch.db")})
    base = _merge(base, settings or {})
    return Config(config_dir=DEFAULT_CONFIG_DIR, settings=base, rules={}, searches={}, feeds={},
                  employers=[])


def add_match(conn, n: int, company="Telstra", title="Customer Service Officer", arm="call_centre",
              url=None) -> int:
    """Insert a posting + match; returns the match id."""
    url = url or f"https://example.org/job/{n}"
    cur = conn.execute(
        """INSERT INTO postings(source, source_id, url, url_hash, dedupe_key, title, company, location,
               first_seen_at, last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        ("seek", str(n), url, f"h{n}", f"k{n}", title, company, "Melbourne VIC", dbm.ts(), dbm.ts()))
    m = conn.execute("INSERT INTO matches(posting_id, arm, matched_at) VALUES(?,?,?)",
                     (cur.lastrowid, arm, dbm.ts()))
    conn.commit()
    return m.lastrowid


def ledger_lines(tmp_path: Path, kind: str) -> list[dict]:
    p = tmp_path / "data" / "ledger" / f"{kind}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
