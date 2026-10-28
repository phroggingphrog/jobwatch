#!/usr/bin/env python3
"""Read-only, conservative acceptance audit for agentic READY packages.

The checker never mutates the database or package files. A supplied snapshot
manifest is an operator attestation of which posting IDs are real (not fixtures);
this prevents synthetic and legacy rows inflating live acceptance counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from pipeline.agentic.contracts import PackageManifest
from jobwatch.apply.verify_pdf import verify_pdf

MINIMUM = 20
AGENT_ACTOR = "pipeline-agentic"


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _inside(root: Path, candidate: str | Path) -> Path | None:
    try:
        path = Path(candidate).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
        return path if path.is_file() else None
    except (OSError, ValueError, RuntimeError):
        return None


def _reason(row: dict[str, Any], manifest: dict[str, Any], approved: dict[int, dict], root: Path,
            verifier: Callable, profile: Any) -> str | None:
    posting_id = row["posting_id"]
    attestation = approved.get(posting_id)
    if not attestation or attestation.get("synthetic") is not False:
        return "not_approved_real"
    if row.get("actor") != AGENT_ACTOR:
        return "not_agentic"
    if row.get("stage") != "ready" or row.get("reason") not in ("agentic_ready", "verified_ready") \
            or row.get("app_status") != "ready" or not row.get("verify_ok"):
        return "not_ready"
    try:
        checked = PackageManifest.model_validate(manifest)
        run_key = checked.run_key
        if run_key.posting_id != posting_id or run_key.ad_hash != hashlib.sha256(
                row["posting_text"].encode("utf-8")).hexdigest():
            return "manifest_invalid"
        if not all(checked.verification.values()) or not checked.review_hash or checked.owner_to_answer < 0:
            return "manifest_invalid"
        expected_hashes = {"run_key": run_key.value, "evaluation_hash": checked.evaluation_hash,
                           "evidence_hash": checked.evidence_hash, "review_hash": checked.review_hash}
        if any(attestation.get(name) != value for name, value in expected_hashes.items()):
            return "stale_run"
    except Exception:
        return "manifest_invalid"

    cv = _inside(root, row["cv_pdf"])
    letter = _inside(root, row["letter_pdf"])
    if cv is None or letter is None:
        return "pdf_missing_or_outside_data_root"
    if hashlib.sha256(cv.read_bytes()).hexdigest() != checked.pdfs["cv"] \
            or hashlib.sha256(letter.read_bytes()).hexdigest() != checked.pdfs["letter"]:
        return "pdf_hash_mismatch"
    # The persisted acceptance contract records the verified package, while the
    # injected verifier permits synthetic tests without subprocess/PDF tooling.
    try:
        package_dir = cv.parent
        draft_file = _inside(root, package_dir / "claims.json")
        req_file = _inside(root, package_dir / "requirements.json")
        if draft_file is None or req_file is None:
            return "verification_evidence_missing"
        draft_data = json.loads(draft_file.read_text(encoding="utf-8"))
        draft_value = draft_data.get("draft", draft_data)
        requirements = json.loads(req_file.read_text(encoding="utf-8"))
        if not isinstance(draft_value, dict) or not isinstance(requirements, list):
            return "verification_evidence_invalid"
        pdf_report = verifier(cv, letter, draft_value, requirements, profile)
    except Exception:
        return "pdf_verification_failed"
    return None if isinstance(pdf_report, dict) and pdf_report.get("ok") is True else "pdf_verification_failed"


def audit_database(conn: sqlite3.Connection, *, data_root: Path, verifier: Callable = verify_pdf,
                   profile: Any = None, approved_postings: dict[int, dict] | None = None) -> dict[str, Any]:
    """Return safe audit rows; caller supplies real-job/snapshot attestation.

    Only application/draft rows with exact current pipeline READY state, valid
    manifest hashes, confined PDF files and passing PDF verification qualify.
    No database writes are issued.
    """
    approved = approved_postings or {}
    tables = _tables(conn)
    required = {"postings", "pipeline_state", "applications", "drafts"}
    if not required <= tables:
        return {"qualifying": 0, "qualifying_ids": [], "rows": [],
                "error": "required_tables_missing"}
    rows: list[dict[str, Any]] = []
    query = """SELECT p.id AS posting_id, p.text AS posting_text, s.stage, s.reason,
                     a.status AS app_status, d.actor, d.cv_pdf, d.letter_pdf,
                     d.verify_ok, d.manifest_json
              FROM postings p JOIN pipeline_state s ON s.posting_id=p.id
              JOIN applications a ON a.posting_id=p.id
              JOIN drafts d ON d.application_id=a.id
              WHERE d.version=(SELECT MAX(d2.version) FROM drafts d2 WHERE d2.application_id=a.id)
              ORDER BY p.id"""
    try:
        records = conn.execute(query).fetchall()
        names = [col[0] for col in conn.execute(query).description]
    except sqlite3.Error:
        return {"qualifying": 0, "qualifying_ids": [], "rows": [], "error": "schema_unavailable"}
    for record in records:
        row = dict(zip(names, record))
        try:
            manifest = json.loads(row["manifest_json"] or "{}")
        except (TypeError, ValueError):
            manifest = {}
        reason = _reason(row, manifest, approved, Path(data_root), verifier, profile)
        rows.append({"posting_id": row["posting_id"], "qualifies": reason is None,
                     "pdf_verified": reason is None, "reason": reason or "qualified"})
    ids = [row["posting_id"] for row in rows if row["qualifies"]]
    return {"qualifying": len(ids), "qualifying_ids": ids, "rows": rows,
            "minimum": MINIMUM, "acceptance_met": len(ids) >= MINIMUM}


def load_approvals(path: Path) -> dict[int, dict]:
    """Load a JSON object/list with posting_id and synthetic=false attestation."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("jobs", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("approval manifest must contain a jobs list")
    result = {}
    for item in items:
        if not isinstance(item, dict) or type(item.get("posting_id")) is not int:
            raise ValueError("invalid approval item")
        result[item["posting_id"]] = item
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite database to inspect read-only")
    parser.add_argument("--data-root", required=True, type=Path, help="root confining package PDF paths")
    parser.add_argument("--snapshot-manifest", required=True, type=Path,
                        help="operator attestation JSON; only synthetic=false jobs qualify")
    args = parser.parse_args(argv)
    try:
        approvals = load_approvals(args.snapshot_manifest)
        conn = sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        from jobwatch.apply.evidence import load_profile
        result = audit_database(conn, data_root=args.data_root, profile=load_profile(),
                                approved_postings=approvals)
        conn.close()
    except Exception as exc:
        print(json.dumps({"error": "audit_unavailable", "detail": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("acceptance_met") else 1


if __name__ == "__main__":
    raise SystemExit(main())
