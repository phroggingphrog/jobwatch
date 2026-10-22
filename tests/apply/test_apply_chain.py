"""Chain-level tests: end-to-end with a mocked LLM, reviewer isolation, verify_pdf checks,
ledger reindex round-trip, fit-stop gate."""
from __future__ import annotations
from jobwatch.settings import DEFAULT_MODEL

import json
import shutil
from pathlib import Path
from datetime import UTC, datetime, timedelta

import pytest

from jobwatch import ledger
from jobwatch.apply import render
from jobwatch.apply.chain import DraftRefused, draft_status, start_draft
from jobwatch.apply.verify_pdf import garbage_reasons, verify_pdf

from .conftest import FakeLLM, fake_draft

pytestmark = pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler-utils not installed")


def test_chain_end_to_end(conn, profile):
    fake = FakeLLM(profile)
    app_id = start_draft(conn, 1, "web:evt1", llm=fake, profile=profile)
    st = draft_status(conn, app_id)
    assert st["application_status"] == "drafted" and st["status"] == "ready", st["error"]
    assert set(st["files"]) == {"cv_pdf", "letter_pdf", "summary_md"}
    assert "Honest gaps" in st["summary"] and "Alex Example" not in st["summary"]
    s = st["metrics"]
    assert s["verify_ok"] and s["pages"] == {"cv": 1, "letter": 1}
    assert s["claims_counts"]["removed_by_reason"] == {"number_not_in_evidence": 1}
    # Bogus kind dropped; no unconfirmed stock-phrase preference adds edits.
    assert s["reviewer_edits"]["grounding"] == 1 and s["reviewer_edits"]["style"] == 1
    assert s["models"] == [DEFAULT_MODEL]  # owner 2026-10-19: no Claude subscription; Sol writes and checks
    vdir = st["dir"]
    for name in ("cv.md", "cv.pdf", "letter.md", "letter.pdf", "claims.json", "verify.json", "review.json",
                 "requirements.json", "summary.md"):
        assert Path(vdir, name).exists(), name
    cv_md = open(f"{vdir}/cv.md").read()
    assert "40%" not in cv_md and "120 supplier invoices per week" in cv_md
    assert cv_md.startswith("# Alex Example")          # header copied verbatim by code
    # the owner's proceed is recorded
    ev = conn.execute("SELECT kind, actor, source FROM application_events WHERE application_id=? ORDER BY id",
                      (app_id,)).fetchall()
    assert ("command", "owner", "web:evt1") in [tuple(r) for r in ev]
    # summary returned to the command layer carries no profile text
    blob = json.dumps(s)
    for personal in ("Alex Example", "alex@example.test", "Fakeco", "Bean Scene", "supplier invoices per week"):
        assert personal not in blob


def test_reviewer_gets_only_drafts_and_named_refs(conn, profile):
    fake = FakeLLM(profile)
    start_draft(conn, 1, "cli", llm=fake, profile=profile)
    rev = [b for b in fake.requests if b["messages"][0]["content"].startswith("You are a fresh-context reviewer")]
    assert len(rev) == 1
    msgs = rev[0]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]          # fresh context, single turn
    user = msgs[1]["content"]
    headers = [line for line in user.splitlines() if line.isupper() or line.startswith(("DRAFT", "REFERENCE"))]
    assert headers == ["DRAFT CV:", "DRAFT COVER LETTER:", 'REFERENCE "posting":',
                       'REFERENCE "evidence" (items the draft cites):']
    assert "[c1]" in user and "Acme Logistics" in user
    # nothing else: no contact header, no uncited evidence, no requirements, no drafter brief
    for leak in ("alex@example.test", "Alex Example", "trial balances", "Microsoft Excel", "REQUIREMENTS",
                 "honest_gaps", "You tailor", '"weight"'):
        assert leak not in user and leak not in msgs[0]["content"]
    # the invented claim was removed by code before the reviewer saw anything
    assert "40%" not in user


def test_chain_failure_is_recorded(conn, profile):
    bad = fake_draft(profile)
    for b in bad["cv"]["experience"]:
        b["bullets"] = [{"id": "x", "text": "Invented 99 things.", "evidence_ids": [], "tier": "stated"}]
    bad["cv"].update(summary=[], skills=[], certifications=[], education=[])
    bad["letter"] = {"paragraphs": []}
    app_id = start_draft(conn, 1, "cli", llm=FakeLLM(profile, drafter=bad), profile=profile)
    st = draft_status(conn, app_id)
    assert st["status"] == "failed" and st["application_status"] == "interested"
    assert "no verified claims left" in st["error"]


def test_gate_refuses(conn, profile):
    with pytest.raises(DraftRefused):
        start_draft(conn, 999, "cli", llm=FakeLLM(profile), profile=profile)
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat(timespec="seconds")
    conn.execute("UPDATE postings SET last_seen_at=?", (old,))
    conn.commit()
    with pytest.raises(DraftRefused, match="not current"):
        start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute("UPDATE postings SET last_seen_at=?", (now,))
    ledger.upsert(conn, "applications", "applications",
                  {"posting_id": 1, "match_id": 1, "status": "skipped", "created_at": now, "updated_at": now})
    with pytest.raises(DraftRefused, match="skipped"):
        start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)


def test_ledger_reindex_round_trip(conn, profile):
    start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)
    start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)      # v2
    ledger.append("commands", {"note": "free log record, ignored by reindex"})
    before = ledger.snapshot(conn)
    assert len(before["drafts"]) == 2 and before["requirements"] and before["application_events"]
    for t in reversed(ledger.APPLY_TABLES):                                 # drop
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    ledger.reindex(conn)
    assert ledger.snapshot(conn) == before
    ledger.reindex(conn)                                                    # idempotent
    assert ledger.snapshot(conn) == before
    for line in open(ledger.path_for("drafts")):
        rec = json.loads(line)
        assert rec["v"] == ledger.SCHEMA_VERSION and rec["kind"] == "drafts"


def test_reindex_refuses_rows_missing_from_ledger(conn, profile):
    start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)
    conn.execute("INSERT INTO commands(event_id, room_id, sender, received_at, status) VALUES('$x','!r','@a','t','done')")
    conn.commit()
    before = ledger.snapshot(conn)
    with pytest.raises(ledger.ReindexRefused):
        ledger.reindex(conn)
    assert ledger.snapshot(conn) == before


# -- verify_pdf ----------------------------------------------------------------------
def _write_pdfs(tmp_path, cv_md, letter_md):
    cv_pdf, _ = render.render_pdf(cv_md, max_pages=2)
    lt_pdf, _ = render.render_pdf(letter_md, max_pages=1, letter=True)
    (tmp_path / "cv.pdf").write_bytes(cv_pdf)
    (tmp_path / "letter.pdf").write_bytes(lt_pdf)
    return tmp_path / "cv.pdf", tmp_path / "letter.pdf"


def test_verify_pdf_pass_and_ligatures_off(tmp_path, profile):
    d = fake_draft(profile, with_invented=False)
    posting = {"title": "Accounts Payable Officer", "company": "Acme Logistics"}
    cv, lt = _write_pdfs(tmp_path, render.cv_markdown(d, profile), render.letter_markdown(d, profile, posting))
    reqs = [{"id": 1, "tier": "jd_quoted", "text": "Process supplier invoices", "quote": "process supplier invoices in Xero"},
            {"id": 2, "tier": "jd_quoted", "text": "Payroll", "quote": "run fortnightly payroll in KeyPay"}]
    res = verify_pdf(cv, lt, d, reqs, profile)
    assert res["ok"], res["failures"]
    assert res["coverage_gaps"] == [2]                                      # advisory, not inserted
    assert "KeyPay" not in open(tmp_path / "cv.pdf", "rb").read().decode("latin-1")


def test_verify_pdf_page_limit_and_missing_span(tmp_path, profile):
    d = fake_draft(profile, with_invented=False)
    long_cv = render.cv_markdown(d, profile) + "\n".join(f"- filler line {i} " + "word " * 30 for i in range(300))
    letter = "Dear Hiring Manager,\n\nShort letter body that is long enough. " * 8
    cv, lt = _write_pdfs(tmp_path, long_cv, letter)
    res = verify_pdf(cv, lt, d, [], profile)
    assert not res["ok"]
    assert any(f.startswith("cv:") and "pages" in f for f in res["failures"])
    assert res["missing_span_ids"]["letter"]   # letter claims absent (reported; up to 2 tolerated)


def test_garbage_detection():
    assert garbage_reasons("ok text " * 50, 100) == []
    assert any("ligature" in r for r in garbage_reasons("the ﬁnance ofﬂow " * 30, 100))
    assert any("cid" in r for r in garbage_reasons("(cid:12)(cid:44) " * 30, 100))
    assert any("replacement" in r for r in garbage_reasons("abc � " * 40, 100))
    assert any("too short" in r for r in garbage_reasons("hi", 100))
    assert any("non-letters" in r for r in garbage_reasons("1234 5678 #### " * 30, 100))


def test_ledger_upsert_text_primary_key(conn):
    row = ledger.upsert(conn, "commands", "commands",
                        {"event_id": "$evtA", "room_id": "!r", "sender": "@o", "received_at": "t", "status": "done"})
    assert row["event_id"] == "$evtA" and row["status"] == "done"
    row = ledger.upsert(conn, "commands", "commands", {"event_id": "$evtA", "status": "error", "error": "x"})
    assert row["status"] == "error" and row["sender"] == "@o"          # partial update keeps other columns
    ledger.upsert(conn, "commands", "commands",
                  {"event_id": "$evtB", "room_id": "!r", "sender": "@o", "received_at": "t", "status": "done"})
    before = ledger.snapshot(conn)
    conn.execute("DELETE FROM commands")
    conn.commit()
    ledger.reindex(conn)
    assert ledger.snapshot(conn) == before and len(before["commands"]) == 2


@pytest.mark.parametrize("status", ["applied", "assessment", "interview", "offer"])
def test_drafting_never_moves_an_application_backwards(conn, profile, status):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute("UPDATE postings SET last_seen_at=?", (now,))
    app = ledger.upsert(conn, "applications", "applications",
                        {"posting_id": 1, "match_id": 1, "status": status, "created_at": now, "updated_at": now})
    app_id = start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)
    assert app_id == app["id"] and draft_status(conn, app_id)["status"] == "ready"
    assert conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()[0] == status
    assert not conn.execute("SELECT 1 FROM application_events WHERE kind='status' AND application_id=?", (app_id,)).fetchone()


def test_a_status_changed_during_the_chain_is_not_overwritten(conn, profile):
    class Skipper(FakeLLM):                 # the owner skips the job while the chain runs
        def chat(self, *a, **k):
            conn.execute("UPDATE applications SET status='skipped'")
            conn.commit()
            return super().chat(*a, **k)
    app_id = start_draft(conn, 1, "cli", llm=Skipper(profile), profile=profile)
    assert conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()[0] == "skipped"


def test_a_draft_already_running_for_a_submitted_application_is_refused(conn, profile):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute("UPDATE postings SET last_seen_at=?", (now,))
    app = ledger.upsert(conn, "applications", "applications",
                        {"posting_id": 1, "match_id": 1, "status": "applied", "created_at": now, "updated_at": now})
    conn.execute("INSERT INTO drafts(application_id, version, status, created_at) VALUES(?, 1, 'drafting', ?)", (app["id"], now))
    conn.commit()
    with pytest.raises(DraftRefused, match="already drafting"):     # the status stays 'applied', the draft row says busy
        start_draft(conn, 1, "cli", llm=FakeLLM(profile), profile=profile)
