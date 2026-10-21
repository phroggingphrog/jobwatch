from __future__ import annotations

import json
from pathlib import Path

from jobwatch.candidate.contracts import ReferenceBundle, content_hash


def write_cv(parent: Path, text: str) -> Path:
    root = parent / "profile"
    root.mkdir(parents=True, exist_ok=True)
    (root / "master_resume.md").write_text(text, encoding="utf-8")
    return root


def write_profile(parent: Path, text: str) -> Path:
    root = parent / "profile"
    root.mkdir(parents=True, exist_ok=True)
    (root / "master_resume.md").write_text("# Fictional\\n\\n## Skills\\n- Independent CV skill\\n", encoding="utf-8")
    (root / "profile.yaml").write_text(text, encoding="utf-8")
    return root


def fictional_profile(tmp_path: Path) -> Path:
    """Writes a primary CV under <tmp_path>/profile and returns that root."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cv_path = profile_dir / "cv.md"
    cv_path.write_text("# Fictional\n\n## Skills\n- Reconciled ledgers\n", encoding="utf-8")
    return profile_dir


def fictional_reference(tmp_path: Path) -> Path:
    """Writes an explicit reference JSON export under tmp_path and returns its path."""
    ref_path = tmp_path / "reference.json"
    data = {
        "schema_version": 1,
        "version": "fixture-v1",
        "sources": {"fictional": "fixture-v1"},
        "licenses": {"fictional": "test-only"},
        "families": ["accounting", "hospitality"],
        "dwas": [
            {"id": "test.accounts", "title": "Reconcile accounts", "gwa_id": "test.gwa"}
        ],
        "occupations": [
            {
                "code": "221111", "title": "Accountant", "family": "accounting",
                "excluded": False, "dwa_weights": {"test.accounts": 1.0},
                "gwa_ratings": {"test.gwa": 4.0},
            },
            {
                "code": "431111", "title": "Barista", "family": "hospitality",
                "excluded": True, "dwa_weights": {"test.accounts": 1.0},
                "gwa_ratings": {"test.gwa": 4.0},
            },
        ],
        "crosswalks": [{"soc": "13-2011", "anzsco_codes": ["221111"]}],
    }
    ref_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return ref_path


def fictional_reference_bundle(tmp_path: Path) -> ReferenceBundle:
    """Loads the fictional reference into a validated ReferenceBundle model."""
    ref_path = fictional_reference(tmp_path)
    raw_bytes = ref_path.read_bytes()
    data = json.loads(raw_bytes.decode("utf-8"))
    ref_hash = content_hash(raw_bytes)
    return ReferenceBundle(**data, reference_hash=ref_hash, raw_contents=raw_bytes)
