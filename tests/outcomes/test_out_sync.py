from jobwatch.settings import DEFAULT_MODEL
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from outkit import FakeLLM, FakeMcp, add_match, envelope, ledger_lines, make_env, sse
from jobwatch import db as dbm
from jobwatch.commands.state import set_status
from jobwatch.outcomes.classify import classify_llm, classify_rules, never_hired
from jobwatch.outcomes.mcp import McpClient, ToolNotAllowed
from jobwatch.outcomes.sync import company_terms, run_outcomes
from jobwatch.web.actions import decide_proposal

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)          # 12:00 Melbourne
APPLIED = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
GM = ("gmail", "[Gmail]/All Mail")
IC = ("icloud", "Inbox")


def synthetic_mail():
    gmail = [
        envelope(1, "m1@telstra", "Interview invitation – Customer Service Officer", "talent@telstra.com",
                 "Telstra Talent", "2026-10-04 09:00:00+00:00"),
        envelope(2, "m2@wd", "Thank you for your application", "no-reply@myworkday.com", "Telstra Careers",
                 "2026-10-01 12:00:00+00:00"),
        envelope(3, "m3@seek", "New jobs for you", "jobmail@seek.com.au", "SEEK", "2026-10-03 09:00:00+00:00"),
        envelope(4, "m4@pageup", "Your application update", "noreply@pageup.com", "Telstra",
                 "2026-10-05 09:00:00+00:00"),
        envelope(5, "m5@old", "Interview invitation", "talent@telstra.com", "Telstra",
                 "2026-09-01 09:00:00+00:00"),
        envelope(6, "m6@telstra", "Next steps", "careers@telstra.com", "Telstra", "2026-10-05 10:00:00+00:00"),
    ]
    icloud = [dict(gmail[0], id="901")]             # the same message in a second mailbox
    bodies = {"4": "Dear applicant, unfortunately you were not successful on this occasion.",
              "6": "Please let us know when you can talk. " + "x" * 5000}
    return FakeMcp({GM: gmail, IC: icloud}, bodies)


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = make_env(tmp_path, monkeypatch, {"outcomes": {"mailboxes": [
        {"account": "gmail", "mailbox": "[Gmail]/All Mail"}, {"account": "icloud", "mailbox": "Inbox"}]}})
    conn = dbm.connect(config.db_path)
    mid = add_match(conn, 1, url="https://careers.telstra.com/job/1")
    set_status(conn, mid, "applied", actor="owner", source="cli", now=APPLIED)
    return config, conn, mid, tmp_path


def run(config, conn, mcp, llm=None, now=NOW, dry_run=False):
    return run_outcomes(config, dry_run=dry_run, mcp=mcp, llm=llm, now=now, conn=conn, printer=lambda *_: None)


def test_scan_proposes_and_dedupes(env):
    config, conn, mid, tmp_path = env
    mcp, llm = synthetic_mail(), FakeLLM({"label": "hired", "confidence": 0.8})
    stats = run(config, conn, mcp, llm=llm)
    assert stats["error"] is None
    assert stats["messages_scanned"] == 6            # m1 seen twice (gmail + icloud) counted once
    assert stats["proposals"] == 3 and stats["no_change"] == 1 and stats["unmatched"] == 2
    assert stats["llm_calls"] == 1
    rows = {r["source_message_id"]: r for r in conn.execute("SELECT * FROM outcome_proposals")}
    assert {k: r["proposed_status"] for k, r in rows.items()} == \
        {"m1@telstra": "interview", "m4@pageup": "rejected", "m6@telstra": "offer"}
    assert all(r["from_addr"] in ("telstra.com", "pageup.com") for r in rows.values())   # domain only
    assert all(len(json.loads(r["evidence_json"])["snippet"]) <= 200 for r in rows.values())
    assert "offer_review" in json.loads(rows["m6@telstra"]["evidence_json"])["flags"]
    # the model got the subject + at most 1,500 chars of body
    user_msg = llm.prompts[0][1][1]["content"]
    assert user_msg.startswith("Subject: Next steps") and len(user_msg) <= len("Subject: Next steps\n\n") + 1500
    assert llm.prompts[0][0] == DEFAULT_MODEL  # owner 2026-10-19: no Claude subscription
    # nothing changed on the application yet
    assert conn.execute("SELECT status FROM applications").fetchone()[0] == "applied"
    # ledger has the proposals as row records
    assert sum(1 for r in ledger_lines(tmp_path, "outcomes") if r.get("table") == "outcome_proposals") >= 3
    # a second run: same mail -> no new proposals
    stats2 = run(config, conn, mcp, llm=llm)
    assert stats2["proposals"] == 0 and stats2["llm_calls"] == 0


def test_approve_reject_on_the_board(env, monkeypatch):
    config, conn, mid, tmp_path = env
    # Decide on the same day the proposals were made: with the real clock they pass the 7-day expiry (failed from 2026-10-13).
    monkeypatch.setattr("jobwatch.outcomes.decide.now_utc", lambda: NOW)
    run(config, conn, synthetic_mail(), llm=FakeLLM({"label": "offer", "confidence": 0.7}))
    pid = {r["proposed_status"]: r["id"] for r in conn.execute("SELECT * FROM outcome_proposals")}
    assert "applied → interview" in decide_proposal(conn, pid["interview"], "approve")
    assert "rejected (no change)" in decide_proposal(conn, pid["rejected"], "reject")
    assert "Already approved" in decide_proposal(conn, pid["interview"], "approve")
    c2 = dbm.connect(config.db_path)
    assert c2.execute("SELECT status FROM applications").fetchone()[0] == "interview"
    st = {r["proposed_status"]: r["status"] for r in c2.execute("SELECT * FROM outcome_proposals")}
    assert st == {"interview": "approved", "rejected": "rejected", "offer": "proposed"}
    out = decide_proposal(conn, pid["offer"], "approve")
    assert "interview → offer" in out and "review it yourself" in out
    assert c2.execute("SELECT status FROM applications").fetchone()[0] == "offer"
    decided = c2.execute("SELECT * FROM application_events WHERE kind='outcome_decided'").fetchall()
    assert len(decided) == 3 and all(e["source"] == "web" for e in decided)


def test_never_hired_db_check_and_code(env):
    config, conn, mid, _ = env
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO outcome_proposals(source_message_id, proposed_status) VALUES('x', 'hired')")
    flags = []
    assert never_hired("hired", flags) == "offer" and flags == ["offer_review"]
    v = classify_llm("Welcome aboard", "you are hired", llm=FakeLLM({"label": "HIRED", "confidence": 1}))
    assert v.label == "offer" and "offer_review" in v.flags
    assert classify_rules("Congratulations, you're hired!").label != "hired"


def test_expiry_after_7_days(env):
    config, conn, mid, _ = env
    run(config, conn, synthetic_mail(), llm=FakeLLM({"label": "none"}))
    later = NOW + timedelta(days=8)
    stats = run(config, conn, FakeMcp({}), now=later)
    assert stats["expired"] == 2
    assert {r[0] for r in conn.execute("SELECT status FROM outcome_proposals")} == {"expired"}


def test_dry_run_writes_nothing_and_calls_no_llm(env):
    config, conn, mid, tmp_path = env
    llm = FakeLLM({"label": "offer"})
    before = len(ledger_lines(tmp_path, "outcomes"))
    stats = run(config, conn, synthetic_mail(), llm=llm, dry_run=True)
    assert stats["proposals"] == 2 and stats["would_llm"] == 1 and llm.prompts == []
    assert conn.execute("SELECT COUNT(*) FROM outcome_proposals").fetchone()[0] == 0
    assert len(ledger_lines(tmp_path, "outcomes")) == before
    assert dbm.get_state(conn, "outcomes:seen") is None


def test_no_applications_no_search(tmp_path, monkeypatch):
    config = make_env(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    mcp = synthetic_mail()
    stats = run(config, conn, mcp)
    assert stats["applications"] == 0 and mcp.searches == []


def test_queries_are_scoped_to_company_and_ats_since_applied(env):
    config, conn, mid, _ = env
    mcp = synthetic_mail()
    run(config, conn, mcp, llm=FakeLLM({"label": "none"}))
    qs = [q for _, _, q in mcp.searches]
    assert any('from "Telstra"' in q and "from telstra.com" in q and "after 2026-09-28" in q for q in qs)
    assert any("from workday" in q and "from careers.vic" in q for q in qs)
    assert all(" and after " in q for q in qs)
    assert all(r[3] == 1500 for r in mcp.reads)


def test_company_terms():
    t = company_terms("Department of Health Victoria", "https://www.health.vic.gov.au/careers/1")
    assert t == {"name": "Department of Health Victoria", "key": "", "domain": "health.vic.gov.au"}
    assert company_terms("Telstra", "https://telstra.wd3.myworkdayjobs.com/x")["domain"] == ""


@pytest.mark.parametrize("subject,body,label", [
    ("Interview invitation - Admin Officer", "", "interview"),
    ("We'd like to invite you to a phone interview", "", "interview"),
    ("Complete your online assessment", "", "assessment"),
    ("Your application", "Please complete the HireVue one-way video", "assessment"),
    ("Your application for Payroll Officer", "Unfortunately we will not be progressing your application", "rejected"),
    ("Thank you for applying", "", "applied"),
    ("Thank you for your application", "Unfortunately you were unsuccessful", "rejected"),
    ("Letter of offer - Payroll Officer", "", "offer"),
    ("Weekly newsletter", "Special offer on courses", None),
])
def test_classify_rules(subject, body, label):
    assert classify_rules(subject, body).label == label


def test_conflicting_body_is_ambiguous():
    v = classify_rules("Update on your application", "Interview invitation ... letter of offer attached")
    assert v.label is None and v.ambiguous


class _Session:
    def __init__(self):
        self.posts = []

    def post(self, url, data=None, headers=None, timeout=None):
        p = json.loads(data)
        self.posts.append(p)
        if p["method"] == "notifications/initialized":
            from cmdkit import FakeResp
            return FakeResp(202, None, {})
        if p["method"] == "initialize":
            return sse({"jsonrpc": "2.0", "id": p["id"], "result": {"serverInfo": {"name": "fake"}}})
        if p["method"] == "tools/list":
            return sse({"jsonrpc": "2.0", "id": p["id"], "result": {"tools": [{"name": "inbox_search"},
                                                                             {"name": "mail_compose"}]}})
        if p["method"] == "tools/call":
            env = {"envelopes": [envelope(1, "a@b", "Hi", "x@telstra.com")]}
            return sse({"jsonrpc": "2.0", "id": p["id"],
                        "result": {"content": [{"type": "text", "text": json.dumps(env)}], "isError": False}})
        raise AssertionError(p)


def test_mcp_client_read_only_allowlist():
    s = _Session()
    c = McpClient(session=s)
    assert c.list_tools() == ["inbox_search", "mail_compose"]
    assert c.search("gmail", "INBOX", "from telstra")[0]["message-id"] == "<a@b>"
    n = len(s.posts)
    for bad in ("mail_compose", "mail_reply", "inbox_move_message", "inbox_set_flag", "google_send_gmail_message"):
        with pytest.raises(ToolNotAllowed):
            c.call(bad, {})
    assert len(s.posts) == n                     # refused before any request
    with pytest.raises(ValueError):
        McpClient("http://example.com/mcp")


def test_scan_holds_no_write_transaction_over_network_calls(env):
    config, conn, mid, tmp_path = env
    other = sqlite3.connect(config.db_path, timeout=0.2)
    seen = []

    def probe(what):
        # a proposal was already written when later body reads / model calls happen
        seen.append((what, conn.in_transaction,
                     conn.execute("SELECT COUNT(*) FROM outcome_proposals").fetchone()[0]))
        other.execute("INSERT OR REPLACE INTO state(key, value) VALUES('probe', '1')")   # "database is locked" if held
        other.commit()

    class Probing(FakeMcp):
        def read_body(self, *a, **kw):
            probe("body")
            return super().read_body(*a, **kw)

    class ProbingLLM(FakeLLM):
        def chat(self, *a, **kw):
            probe("llm")
            return super().chat(*a, **kw)

    mcp = synthetic_mail()
    mcp.__class__ = Probing
    stats = run(config, conn, mcp, llm=ProbingLLM({"label": "hired", "confidence": 0.8}))
    assert stats["error"] is None and stats["proposals"] == 3
    assert any(n > 0 for _, _, n in seen)                       # a proposal existed before a later network step
    assert not any(in_tx for _, in_tx, _ in seen)
    other.close()


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8913/mcp", "http://localhost:8913/mcp", "http://localhost/mcp",
    "http://[::1]:8913/mcp", "http://127.0.0.1/", "http://LOCALHOST:1/mcp"])
def test_mcp_loopback_urls_accepted(url):
    assert McpClient(url).url == url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1.evil.example/mcp", "http://127.0.0.1@evil.example/mcp",
    "http://localhost.evil.example/mcp", "http://localhostevil.example/mcp",
    "http://user:pw@127.0.0.1:8913/mcp", "http://user@localhost/mcp", "http://@127.0.0.1/mcp",
    "http://127.0.0.1:99999/mcp", "http://127.0.0.1:abc/mcp", "https://127.0.0.1/mcp",
    "http://[::2]/mcp", "http://[::1]@evil.example/mcp", "http://localhost./mcp", "http://127.0.0.2/mcp",
    "ftp://localhost/mcp", "//127.0.0.1/mcp", "127.0.0.1", "", "http://example.com/mcp"])
def test_mcp_non_loopback_urls_rejected(url):
    with pytest.raises(ValueError):
        McpClient(url)


def test_friend_without_google_never_reads_owner_mailboxes(env, monkeypatch):
    """A non-owner person with no Gmail connection gets no scan (not the owner's local MCP mail)."""
    from jobwatch import users
    import jobwatch.outcomes.sync as sync
    config, conn, mid, tmp_path = env
    built = []
    monkeypatch.setattr(sync, "McpClient", lambda *a, **k: built.append(a) or synthetic_mail())
    with users.use("friend"):
        stats = run_outcomes(config, now=NOW, conn=conn, printer=lambda *_: None)
    assert built == [] and stats["messages_scanned"] == 0 and stats["proposals"] == 0
    assert stats["error"] is None and "Gmail" in stats["skipped"]
    assert conn.execute("SELECT count(*) FROM outcome_proposals").fetchone()[0] == 0
