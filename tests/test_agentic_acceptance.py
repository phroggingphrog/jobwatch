"""Synthetic cross-layer acceptance checks; no network or real candidate data."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from scripts.agentic_acceptance import audit_database
from pipeline.agentic.contracts import RunKey

RUN_KEY = RunKey(posting_id=7, ad_hash=hashlib.sha256(b"Full synthetic Melbourne Python ad").hexdigest(),
                 evidence_hash="b" * 64, rubric_version="career-ops-v1", config_hash="c" * 64,
                 candidate_hash="d" * 64).value
APPROVED = {7: {"synthetic": False, "run_key": RUN_KEY, "evaluation_hash": "e" * 64,
                "evidence_hash": "b" * 64, "review_hash": "2" * 64}}

CV = b"%PDF-1.4 synthetic cv"
LETTER = b"%PDF-1.4 synthetic letter"


def synthetic_db(tmp_path, *, stage="ready", app_status="ready", manifest_overrides=None):
    root = tmp_path / "drafts"
    package_dir = root / "7" / "v1"
    package_dir.mkdir(parents=True)
    cv_path, letter_path = package_dir / "cv.pdf", package_dir / "letter.pdf"
    cv_path.write_bytes(CV)
    letter_path.write_bytes(LETTER)
    (package_dir / "claims.json").write_text(json.dumps({"draft": {"cv": {}, "letter": {}}}))
    (package_dir / "requirements.json").write_text("[]")
    manifest = {
        "run_key": {"posting_id": 7, "ad_hash": hashlib.sha256(b"Full synthetic Melbourne Python ad").hexdigest(),
                    "evidence_hash": "b" * 64, "rubric_version": "career-ops-v1",
                    "config_hash": "c" * 64, "candidate_hash": "d" * 64},
        "evaluation_hash": "e" * 64, "evidence_hash": "b" * 64,
        "answers_hash": "f" * 64, "draft_hash": "1" * 64, "review_hash": "2" * 64,
        "pdfs": {"cv": hashlib.sha256(CV).hexdigest(), "letter": hashlib.sha256(LETTER).hexdigest()},
        "verification": {"cv_pdf": True, "letter_pdf": True, "claims": True, "review": True},
        "owner_to_answer": 1,
    }
    manifest.update(manifest_overrides or {})
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
      CREATE TABLE postings(id INTEGER PRIMARY KEY, text TEXT NOT NULL);
      CREATE TABLE pipeline_state(posting_id INTEGER PRIMARY KEY, stage TEXT NOT NULL, reason TEXT);
      CREATE TABLE applications(id INTEGER PRIMARY KEY, posting_id INTEGER, status TEXT);
      CREATE TABLE drafts(application_id INTEGER, version INTEGER, actor TEXT, cv_pdf TEXT,
                         letter_pdf TEXT, verify_ok INTEGER, manifest_json TEXT);
    """)
    conn.execute("INSERT INTO postings VALUES(7, ?)", ("Full synthetic Melbourne Python ad",))
    conn.execute("INSERT INTO pipeline_state VALUES(7, ?, 'agentic_ready')", (stage,))
    conn.execute("INSERT INTO applications VALUES(7, 7, ?)", (app_status,))
    conn.execute("INSERT INTO drafts VALUES(7, 1, 'pipeline-agentic', ?, ?, 1, ?)",
                 (str(cv_path), str(letter_path), json.dumps(manifest)))
    conn.commit()
    return conn, root


def fake_verify(cv, letter, draft, requirements, profile):
    assert cv.read_bytes().startswith(b"%PDF-") and letter.read_bytes().startswith(b"%PDF-")
    assert draft == {"cv": {}, "letter": {}} and requirements == []
    return {"ok": True, "failures": []}


def audit(conn, root, **kwargs):
    return audit_database(conn, data_root=root, verifier=fake_verify, profile=object(),
                          approved_postings=APPROVED, **kwargs)


def test_acceptance_counts_only_current_agentic_ready_verified_real_package(tmp_path):
    conn, root = synthetic_db(tmp_path)
    result = audit(conn, root)
    assert result["qualifying"] == 1
    assert result["rows"][0]["posting_id"] == 7
    assert result["rows"][0]["pdf_verified"] is True


def test_acceptance_excludes_synthetic_and_non_ready_packages(tmp_path):
    conn, root = synthetic_db(tmp_path, stage="drafted")
    result = audit(conn, root)
    assert result["qualifying"] == 0
    assert result["rows"][0]["reason"] == "not_ready"
    result = audit_database(conn, data_root=root, verifier=fake_verify, profile=object(),
                            approved_postings={7: {"synthetic": True}})
    assert result["qualifying"] == 0 and result["rows"][0]["reason"] == "not_approved_real"


def test_acceptance_rejects_tampered_pdf_bytes_even_if_manifest_claims_verified(tmp_path):
    conn, root = synthetic_db(tmp_path)
    (root / "7" / "v1" / "cv.pdf").write_bytes(b"tampered")
    result = audit(conn, root)
    assert result["qualifying"] == 0
    assert result["rows"][0]["reason"] == "pdf_hash_mismatch"


def test_acceptance_ignores_legacy_draft_rows(tmp_path):
    conn, root = synthetic_db(tmp_path)
    conn.execute("UPDATE drafts SET actor='legacy-pipeline'")
    result = audit(conn, root)
    assert result["qualifying"] == 0
    assert result["rows"][0]["reason"] == "not_agentic"


def test_acceptance_requires_all_pdf_claim_and_review_verification_flags(tmp_path):
    bad = {"verification": {"cv_pdf": True, "letter_pdf": True, "claims": True, "review": False}}
    conn, root = synthetic_db(tmp_path, manifest_overrides=bad)
    assert audit(conn, root)["qualifying"] == 0
    assert audit(conn, root)["rows"][0]["reason"] == "manifest_invalid"


def test_acceptance_is_read_only(tmp_path):
    conn, root = synthetic_db(tmp_path)
    before = conn.total_changes
    audit(conn, root)
    assert conn.total_changes == before
