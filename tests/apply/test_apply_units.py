"""Unit tests: allowlist, requirements tiers, claim verifier, profile guard, origin guard,
evidence extraction, seed script. Offline; synthetic profile; mocked LLM."""
from __future__ import annotations

import sqlite3
import stat
import sys
from pathlib import Path

import pytest

from jobwatch import llm as llm_mod
from jobwatch.apply import paths
from jobwatch.apply.evidence import build_evidence, check_evidence, extract_cv
from jobwatch.apply.requirements import INFERRED_MAX_WEIGHT, get_or_extract, verify_requirements
from jobwatch.apply.verify import verify_draft
from jobwatch.origin_guard import OriginRejected, check_bind, check_request

from .conftest import FAKE_CV, POSTING_DESC, FakeLLM, eid, fake_draft, write_profile


def test_gateway_must_be_loopback():
    with pytest.raises(ValueError):
        llm_mod.LLM(base_url="http://openrouter.ai/api/v1")


def test_key_fallback_and_no_key_in_call_log():
    seen = []

    def transport(url, headers, body, timeout):
        seen.append(headers["Authorization"])
        if headers["Authorization"].endswith("KEYAAA111"):
            return 403, {"error": {"code": "permission_denied", "message": "combo not allowed"}}
        return 200, {"model": "x", "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
                     "choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]}

    client = llm_mod.LLM(transport=transport, keys=["sk-KEYAAA111", "sk-KEYBBB222"])
    res = client.chat("claude/opus", [{"role": "user", "content": "hi"}])
    assert res.data == {"ok": True} and len(seen) == 2
    assert res.cost_usd == pytest.approx((1000 * 15 + 100 * 75) / 1e6)
    assert "KEYAAA111" not in repr(client.calls) and "KEYBBB222" not in repr(client.calls)


# -- requirements tiers ---------------------------------------------------------
def test_quote_verification_and_downgrade():
    text = "Title: AP Officer\nLocation: Melbourne VIC\n\n" + POSTING_DESC
    rows = verify_requirements([
        {"text": "invoices", "tier": "jd_quoted", "quote": "PROCESS   supplier\ninvoices in Xero", "weight": 0.9},
        {"text": "MYOB", "tier": "jd_quoted", "quote": "MYOB experience is essential", "weight": 0.8, "blocker": True},
        {"text": "loc", "tier": "structural", "quote": "Melbourne VIC", "weight": 0.5},
        {"text": "loc2", "tier": "structural", "quote": "Sydney NSW", "weight": 0.5},
    ], text, "Title: AP Officer\nLocation: Melbourne VIC")
    assert rows[0]["tier"] == "jd_quoted" and rows[0]["quote_verified"] == 1
    assert rows[1]["tier"] == "inferred" and rows[1]["quote"] is None
    assert rows[1]["blocker"] == 0 and rows[1]["weight"] <= INFERRED_MAX_WEIGHT
    assert rows[2]["tier"] == "structural" and rows[3]["tier"] == "inferred"


def test_inferred_never_blocker_code_and_db(conn):
    rows = verify_requirements([{"text": "detail", "tier": "inferred", "weight": 0.95, "blocker": True}], "x", "")
    assert rows[0]["blocker"] == 0 and rows[0]["weight"] == INFERRED_MAX_WEIGHT
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO requirements(posting_id, text, tier, blocker) VALUES(1, 'x', 'inferred', 1)")


def test_requirements_extracted_once_and_ledgered(conn, profile):
    fake = FakeLLM(profile)
    reqs = get_or_extract(conn, 1, fake)
    assert [r["tier"] for r in reqs] == ["jd_quoted", "jd_quoted", "inferred", "jd_quoted", "structural", "inferred"]
    assert all(not (r["tier"] == "inferred" and r["blocker"]) for r in reqs)
    n = len(fake.requests)
    assert get_or_extract(conn, 1, fake) == reqs and len(fake.requests) == n
    assert (paths.ledger_dir() / "drafts.jsonl").exists()


# -- claim verifier --------------------------------------------------------------
def _verify(profile, draft):
    return verify_draft(draft, profile.by_id, POSTING_DESC + " Acme Logistics Accounts Payable Officer", {1, 2, 3})


def test_verifier_removes_invented_metric(profile):
    clean, rep = _verify(profile, fake_draft(profile))
    removed = {r["id"]: r["reason"] for r in rep["removed"]}
    assert removed == {"c3": "number_not_in_evidence"}
    kept_ids = [c["id"] for b in clean["cv"]["experience"] for c in b["bullets"]]
    assert "c3" not in kept_ids and "c1" in kept_ids
    assert rep["tiers"] == {"stated": 8, "derived": 1, "framing": 2}


@pytest.mark.parametrize("mutate,reason", [
    (lambda c, p: c.update(tier="inferred"), "inferred_claim"),
    (lambda c, p: c.update(evidence_ids=["cv.L999"]), "no_evidence"),
    (lambda c, p: c.update(key_span="processed 500 invoices"), "key_span_not_in_evidence"),
    (lambda c, p: c.update(text="Handled supplier payments in Xero.", key_span="120 supplier invoices per week"),
     "key_span_not_in_claim"),
    (lambda c, p: c.update(text="Processed 120 supplier invoices per week in Xero at Globex Corp.",
                           key_span="120 supplier invoices per week"), "unsupported_name"),
    (lambda c, p: c.update(text="Processed 120 supplier invoices per week in Xero (found via Seek)."),
     "third_party_branding"),
    (lambda c, p: c.update(text="Processed 120 supplier invoices per week in Xero each June."),
     "date_not_in_evidence"),
])
def test_verifier_reasons(profile, mutate, reason):
    d = fake_draft(profile, with_invented=False)
    mutate(d["cv"]["experience"][0]["bullets"][0], profile)
    _, rep = _verify(profile, d)
    assert {r["id"]: r["reason"] for r in rep["removed"]} == {"c1": reason}


def test_verifier_derived_and_framing(profile):
    d = fake_draft(profile, with_invented=False)
    d["letter"]["paragraphs"][1][1]["derivation"]["result"] = "9"
    d["letter"]["paragraphs"][1][1]["text"] = "I have worked in my current accounts role for 9 years."
    d["letter"]["paragraphs"][0][0]["text"] = "I am applying for the role at Initech after 5 years in finance."
    d["cv"]["summary"].append({"id": "c20", "text": "Motivated team player.", "tier": "framing"})
    _, rep = _verify(profile, d)
    got = {r["id"]: r["reason"] for r in rep["removed"]}
    assert got == {"c11": "derivation_mismatch", "c9": "framing_has_numbers_or_dates",
                   "c20": "framing_outside_letter"}


def test_verifier_headings_come_from_evidence_only(profile):
    d = fake_draft(profile, with_invented=False)
    d["cv"]["experience"][1]["role_ids"] = ["made.up.id"]
    d["cv"]["education"][0]["entry_ids"] = [eid(profile, "Barista", "role")]  # wrong kind
    clean, rep = _verify(profile, d)
    assert len(clean["cv"]["experience"]) == 1 and clean["cv"]["education"] == []
    assert sum(r["reason"] == "bad_heading_ref" for r in rep["removed"]) == 2


def test_verifier_drops_gaps_for_unknown_requirements(profile):
    d = fake_draft(profile)
    d["honest_gaps"].append({"requirement_id": 99, "note": "x"})
    clean, _ = _verify(profile, d)
    assert [g["requirement_id"] for g in clean["honest_gaps"]] == [3]


# -- data contract: profile write guard ---------------------------------------------
def test_profile_write_guard(apply_env):
    pdir = paths.profile_dir()
    for target in (pdir / "cv.md", pdir / "new.txt", pdir / "sub" / "x.json",
                   paths.drafts_dir() / ".." / "profile" / "evidence.yaml"):
        with pytest.raises(paths.ProfileWriteError):
            paths.safe_write_text(target, "x")
    with pytest.raises(paths.ProfileWriteError):
        paths.ensure_dir(pdir / "cache")
    # a symlink from the system layer into profile/ is also refused
    link = apply_env / "drafts_link"
    link.symlink_to(pdir)
    with pytest.raises(paths.ProfileWriteError):
        paths.safe_write_text(link / "x.md", "x")
    out = paths.safe_write_text(paths.drafts_dir() / "1" / "v1" / "ok.md", "ok")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700


# -- evidence extraction (synthetic profile) --------------------------------------
def test_evidence_is_verbatim_and_excludes_contact(apply_env):
    pdir = paths.profile_dir()
    items = build_evidence(pdir)
    assert check_evidence(pdir, items) == []
    texts = " ".join(i["text"] for i in items)
    assert "alex@example.test" not in texts and "0400 000 000" not in texts and "Alex Example" not in texts
    kinds = {i["kind"] for i in items}
    assert kinds == {"role", "education", "skill", "achievement", "cert"}
    lines = FAKE_CV.splitlines()
    for i in extract_cv(FAKE_CV):
        assert i["text"] in lines[i["line"] - 1]
    assert any(i["id"].startswith("tx.ev-acc-01") for i in items)


def test_seed_script_copies_not_moves(tmp_path, monkeypatch):
    src = write_profile(tmp_path / "src")
    (src / "evidence.yaml").unlink()
    dest = tmp_path / "dest"
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import seed_profile
    assert seed_profile.main(["--src", str(src), "--dest", str(dest)]) == 0
    assert (src / "master_resume.md").exists()                 # copied, not moved
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    for f in ("master_resume.md", "profile.yaml", "evidence.yaml"):
        assert stat.S_IMODE((dest / f).stat().st_mode) == 0o600
    assert (dest / "cv.md").is_symlink()
    assert seed_profile.main(["--src", str(src), "--dest", str(dest)]) == 0   # idempotent
    (src / "profile.yaml").write_text((src / "profile.yaml").read_text() + "\n# changed\n")
    assert seed_profile.main(["--src", str(src), "--dest", str(dest)]) == 1   # refuses without --force
    (dest / 'cv.md').unlink()
    (dest / 'cv.md').write_text('Previous synthetic resume')
    monkeypatch.setattr(seed_profile.Path, 'home', classmethod(lambda cls: tmp_path / 'private-home'))
    assert seed_profile.main(['--src', str(src), '--dest', str(dest), '--force']) == 0
    assert (dest / 'cv.md').is_symlink() and (dest / 'cv.md').read_bytes() == (src / 'master_resume.md').read_bytes()
    backups = list((tmp_path / 'private-home' / 'backups' / 'jobwatch').glob('cv.md.*'))
    assert len(backups) == 1 and backups[0].read_text() == 'Previous synthetic resume'


# -- origin guard -------------------------------------------------------------------
@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_bind_loopback_ok(host):
    assert check_bind(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.0.80", "10.0.0.1", "example.com", ""])
def test_bind_non_loopback_refused(host):
    with pytest.raises(OriginRejected):
        check_bind(host)


def test_request_headers():
    check_request({"Host": "127.0.0.1:8099"}, 8099)
    check_request({"Host": "localhost:8099", "Origin": "http://localhost:8099"}, 8099)
    check_request({"host": "[::1]:8099", "referer": "http://[::1]:8099/x"}, 8099)
    bad = [
        {},
        {"Host": "jobs.example.com"},
        {"Host": "evil.example:8099"},                                  # DNS rebinding
        {"Host": "127.0.0.1:9000"},
        {"Host": "127.0.0.1:8099", "Origin": "https://evil.example"},
        {"Host": "127.0.0.1:8099", "Origin": "null"},
        {"Host": "127.0.0.1:8099", "Origin": "http://127.0.0.1:3000"},  # other local app
        {"Host": "127.0.0.1:8099", "Referer": "http://192.168.0.80:8099/"},
        {"Host": "127.0.0.1:8099", "Origin": "file://"},
    ]
    for headers in bad:
        with pytest.raises(OriginRejected):
            check_request(headers, 8099)


def test_stock_edits_flags_template_phrases_and_i_openings():
    from jobwatch.apply.review import stock_edits
    draft = {"cv": {"summary": [{"id": "s1", "text": "Results-driven professional with a proven track record."}]},
             "letter": {"paragraphs": [
                 [{"id": "c1", "text": "I am applying for the Clerk role."},
                  {"id": "c2", "text": "I reviewed tax returns before lodgement."}],
                 [{"id": "c3", "text": "I handled enquiries by phone and live chat."},
                  {"id": "c4", "text": "Your team needs accurate records, which is what I kept at Northside Tax."}]]}}
    edits = stock_edits(draft)
    assert {e["target"] for e in edits} == {"c1", "s1", "letter"}
    assert all(e["kind"] == "style" for e in edits)
    assert stock_edits({"letter": {"paragraphs": [[{"id": "c1", "text": "Your team needs records kept."}]]}}) == []


def test_full_posting_text_prefers_fetched_ad(tmp_path):
    import sqlite3
    from jobwatch.apply.requirements import full_posting_text
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE postings(id INTEGER PRIMARY KEY, title TEXT, company TEXT, description TEXT);"
                       "CREATE TABLE ad_text(posting_id INTEGER PRIMARY KEY, text TEXT, source TEXT, fetched_at TEXT);"
                       "INSERT INTO postings VALUES(1, 'Clerk', 'Acme', 'teaser');"
                       "INSERT INTO postings VALUES(2, 'Clerk', 'Acme', 'a long collector description');"
                       "INSERT INTO ad_text VALUES(1, 'the full ad with every duty', 'seek_detail', 'x');"
                       "INSERT INTO ad_text VALUES(2, 'short', 'seek_detail', 'x');")
    p1, p2 = (conn.execute("SELECT * FROM postings WHERE id=?", (i,)).fetchone() for i in (1, 2))
    assert full_posting_text(conn, p1).endswith("the full ad with every duty")
    assert full_posting_text(conn, p2).endswith("a long collector description")


def test_meta_text_removed_and_stock_framing_dropped(profile):
    from jobwatch.apply.review import drop_stock_framing, stock_edits
    from jobwatch.apply.verify import ClaimVerifier
    v = ClaimVerifier(profile.by_id, "Clerk at Acme")
    assert v.check({"text": "I would help with enquiries, without claiming prior student work.",
                    "tier": "framing"}, "letter.p0") == "meta_text"
    draft = {"letter": {"paragraphs": [
        [{"id": "c1", "tier": "framing", "text": "I am applying for the Clerk role."}],
        [{"id": "c2", "tier": "stated", "text": "I reviewed returns.", "key_span": "reviewed returns"},
         {"id": "c3", "tier": "stated", "text": "Again, I reviewed returns.", "key_span": "reviewed returns"}]]}}
    assert [e["target"] for e in stock_edits(draft) if e["target"] != "letter"] == ["c1", "c3"]
    assert drop_stock_framing(draft) == 1
    assert [[c["id"] for c in p] for p in draft["letter"]["paragraphs"]] == [["c2", "c3"]]


def test_repeated_fact_in_new_words_flagged_and_dropped():
    from jobwatch.apply.review import drop_repeats, stock_edits
    draft = {"letter": {"paragraphs": [
        [{"id": "c1", "tier": "framing", "text": "Your team keeps student records."},
         {"id": "c2", "tier": "stated", "text": "I helped clients through ATO audits.", "evidence_ids": ["e1"],
          "key_span": "ATO audits"}],
        [{"id": "c3", "tier": "stated", "text": "Audits by the ATO were part of my work.", "evidence_ids": ["e1"],
          "key_span": "the ATO"},
         {"id": "c4", "tier": "stated", "text": "I answered live chat.", "evidence_ids": ["e1", "e2"],
          "key_span": "live chat"}]]}}
    edits = stock_edits(draft)
    assert ("c3", "repeated fact (code check)") in {(e["target"], e["reason"]) for e in edits}
    assert ("letter", "no closing paragraph (code check)") in {(e["target"], e["reason"]) for e in edits}
    assert drop_repeats(draft) == 1
    assert [[c["id"] for c in p] for p in draft["letter"]["paragraphs"]] == [["c1", "c2"], ["c4"]]
    draft["letter"]["paragraphs"].append([{"id": "c5", "tier": "framing", "text": "Happy to talk about the role."}])
    assert not any(e["reason"].startswith("no closing") for e in stock_edits(draft))
