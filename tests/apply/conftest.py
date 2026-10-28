"""Fixtures for the apply layer. SYNTHETIC profile only (a fake person); the LLM is mocked."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
import yaml

from jobwatch import db as dbm
from jobwatch.apply.evidence import build_evidence, load_profile
from jobwatch.util.llm import LLM

FAKE_CV = """# Alex Example

**Accounts & Admin | Melbourne VIC**

Melbourne, VIC | alex@example.test | 0400 000 000 | linkedin.com/in/alex-example

## Professional Summary

Accounts graduate with hands-on bookkeeping experience. Comfortable with Xero and Excel.

## Core Skills

- Accounts payable and receivable
- Bank reconciliations
- Xero and MYOB

## Professional Experience

### Accounts Assistant, Fakeco Pty Ltd
*Melbourne, VIC | Mar 2022 – Present*

- Processed 120 supplier invoices per week in Xero.
- Reconciled bank accounts monthly for 3 entities.

### Barista, Bean Scene Cafe
*Geelong, VIC | Jan 2019 – Feb 2022*

- Handled cash and EFTPOS payments during busy morning shifts.

## Education

### Bachelor of Business (Accounting), Example University
*Melbourne, VIC | 2018 – 2021*

## Certifications

Certificate IV in Bookkeeping (2022); First Aid (2023).
"""

FAKE_PROFILE_YAML = """version: "1"
candidate:
  name: "Alex Example"
  email: "alex@example.test"
  languages:
    - "English (fluent)"
skills:
  tools_and_platforms:
    - "Xero"
    - "Microsoft Excel"
experience:
  - title: "Accounts Assistant"
    company: "Fakeco Pty Ltd"
    period: "Mar 2022 - Present"
    highlights:
      - "Processed 120 supplier invoices per week in Xero"
"""

FAKE_TAXONOMY = """version: "1"
academic_evidence:
  example_uni:
    - id: "ev-acc-01"
      course_name: "Financial Accounting"
      verbatim_fact: "Prepared trial balances and month-end journals."
      keywords: ["journals"]
"""

YEARS = datetime.now().year - 2022   # derived tenure of the fake current role

POSTING_DESC = ("We are seeking an Accounts Payable Officer to join our finance team. You will process "
                "supplier invoices in Xero and complete bank reconciliations each month. Experience with "
                "MYOB is desirable. Must have full working rights in Australia.")


def write_profile(pdir):
    pdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    (pdir / "master_resume.md").write_text(FAKE_CV)
    (pdir / "profile.yaml").write_text(FAKE_PROFILE_YAML)
    (pdir / "transferable_skills_taxonomy.yaml").write_text(FAKE_TAXONOMY)
    (pdir / "evidence.yaml").write_text(yaml.safe_dump({"items": build_evidence(pdir)}, sort_keys=False))
    return pdir


@pytest.fixture
def apply_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(data))
    monkeypatch.delenv("JOBWATCH_PROFILE_DIR", raising=False)
    write_profile(data / "profile")
    return data


@pytest.fixture
def profile(apply_env):
    return load_profile()


def eid(profile, needle: str, kind: str | None = None) -> str:
    """Evidence id of the first cv.* item containing `needle` (falls back to any source)."""
    items = sorted(profile.evidence, key=lambda e: not e["id"].startswith("cv."))
    for e in items:
        if needle in e["text"] and (kind is None or e["kind"] == kind):
            return e["id"]
    raise KeyError(needle)


@pytest.fixture
def conn(apply_env):
    c = dbm.connect(apply_env / "test.db")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    cur = c.execute(
        "INSERT INTO postings(source, source_id, url, url_hash, dedupe_key, title, company, location, state,"
        " work_type, description, first_seen_at, last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("test", "1", "https://example.test/job/1", "h1", "k1", "Accounts Payable Officer", "Acme Logistics",
         "Melbourne VIC", "VIC", "Full time", POSTING_DESC, now, now))
    pid = cur.lastrowid
    c.execute("INSERT INTO matches(posting_id, arm, arm_tier, matched_at) VALUES(?,?,?,?)",
              (pid, "accounting_clerk", "core", now))
    c.commit()
    return c


def fake_requirements():
    return {"requirements": [
        {"text": "Process supplier invoices in Xero", "tier": "jd_quoted",
         "quote": "process  supplier invoices in XERO", "weight": 0.9, "blocker": False},
        {"text": "Bank reconciliations", "tier": "jd_quoted", "quote": "complete bank reconciliations",
         "weight": 0.7, "blocker": False},
        {"text": "MYOB essential", "tier": "jd_quoted", "quote": "MYOB experience is essential",
         "weight": 0.8, "blocker": True},
        {"text": "Full working rights", "tier": "jd_quoted",
         "quote": "Must have full working rights in Australia", "weight": 1.0, "blocker": True},
        {"text": "Based in Melbourne", "tier": "structural", "quote": "Melbourne VIC", "weight": 0.6},
        {"text": "Attention to detail", "tier": "inferred", "weight": 0.9, "blocker": True},
    ]}


def fake_draft(profile, with_invented=True):
    inv = eid(profile, "supplier invoices", "achievement")
    rec = eid(profile, "Reconciled bank accounts")
    bullets = [
        {"id": "c1", "text": "Processed 120 supplier invoices per week in Xero.", "evidence_ids": [inv],
         "tier": "stated", "key_span": "120 supplier invoices per week"},
        {"id": "c2", "text": "Reconciled bank accounts monthly for 3 entities.", "evidence_ids": [rec],
         "tier": "stated", "key_span": "Reconciled bank accounts monthly"},
    ]
    if with_invented:
        bullets.append({"id": "c3", "text": "Cut supplier invoices processing time by 40%.",
                        "evidence_ids": [inv], "tier": "stated", "key_span": "supplier invoices"})
    return {
        "cv": {
            "summary": [{"id": "c4", "text": "Accounts graduate with hands-on bookkeeping experience.",
                         "evidence_ids": [eid(profile, "Accounts graduate")], "tier": "stated",
                         "key_span": "hands-on bookkeeping experience"}],
            "skills": [{"id": "c5", "text": "Bank reconciliations", "evidence_ids": [eid(profile, "Bank reconciliations")],
                        "tier": "stated", "key_span": "Bank reconciliations"},
                       {"id": "c6", "text": "Xero and MYOB", "evidence_ids": [eid(profile, "Xero and MYOB")],
                        "tier": "stated", "key_span": "Xero and MYOB"}],
            "experience": [
                {"role_ids": [eid(profile, "Accounts Assistant, Fakeco", "role"), eid(profile, "Mar 2022", "role")],
                 "bullets": bullets},
                {"role_ids": [eid(profile, "Barista", "role"), eid(profile, "Jan 2019", "role")],
                 "bullets": [{"id": "c7", "text": "Handled cash and EFTPOS payments during busy shifts.",
                              "evidence_ids": [eid(profile, "EFTPOS")], "tier": "stated",
                              "key_span": "cash and EFTPOS payments"}]}],
            "education": [{"entry_ids": [eid(profile, "Bachelor of Business", "education"),
                                         eid(profile, "2018", "education")], "bullets": []}],
            "certifications": [{"id": "c8", "text": "Certificate IV in Bookkeeping (2022)",
                                "evidence_ids": [eid(profile, "Certificate IV", "cert")], "tier": "stated",
                                "key_span": "Certificate IV in Bookkeeping (2022)"}],
            "additional": [],
        },
        "letter": {"paragraphs": [
            [{"id": "c9", "text": "I am applying for the Accounts Payable Officer role at Acme Logistics.",
              "evidence_ids": [], "tier": "framing"}],
            [{"id": "c10", "text": "In my current role I have processed 120 supplier invoices per week in Xero.",
              "evidence_ids": [inv], "tier": "stated", "key_span": "120 supplier invoices per week in Xero"},
             {"id": "c11", "text": f"I have worked in my current accounts role for {YEARS} years.",
              "evidence_ids": [eid(profile, "Mar 2022", "role")], "tier": "derived",
              "derivation": {"inputs": [eid(profile, "Mar 2022", "role")], "method": "years_between",
                             "result": str(YEARS)}}],
            [{"id": "c12", "text": "I would welcome the chance to discuss the role with your finance team.",
              "evidence_ids": [], "tier": "framing"}],
        ]},
        "honest_gaps": [{"requirement_id": 3, "note": "No MYOB in a paid role."}],
    }


class FakeLLM(LLM):
    """LLM with a mocked transport; records every request body (for isolation tests)."""

    def __init__(self, profile, reviewer_edits=None, drafter=None):
        self.requests: list[dict] = []
        self.profile = profile
        self.reviewer_edits = reviewer_edits if reviewer_edits is not None else [
            {"kind": "grounding", "target": "c2", "suggestion": "keep as stated", "reason": "check entity count"},
            {"kind": "style", "target": "letter", "suggestion": "tighten the opening", "reason": "concision"},
            {"kind": "bogus", "target": "c1", "suggestion": "x", "reason": "y"}]
        self.drafter = drafter
        super().__init__(transport=self._transport, keys=["test-key"])

    def _transport(self, url, headers, body, timeout):
        self.requests.append(body)
        system = body["messages"][0]["content"]
        if system.startswith("You extract hiring requirements"):
            data = fake_requirements()
        elif system.startswith("You tailor"):
            data = self.drafter or fake_draft(self.profile)
        elif system.startswith("You are a fresh-context reviewer"):
            data = {"edits": self.reviewer_edits}
        elif system.startswith("You revise"):
            user = body["messages"][1]["content"]
            draft = json.loads(user.split("DRAFT:\n", 1)[1].split("\n\nEDITS:\n", 1)[0])
            data = {**draft, "applied": [0, 1], "skipped": []}
        else:
            raise AssertionError("unexpected prompt")
        return 200, {"model": body["model"], "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                     "choices": [{"message": {"content": json.dumps(data)}}]}
