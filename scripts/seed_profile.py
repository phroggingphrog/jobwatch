#!/usr/bin/env python3
"""Seed the user layer once (PLAN-apply D3): COPY the archived candidate profile into
~/brain/data/jobwatch/profile/ (dir 700, files 600) and build profile/evidence.yaml.

This is the only code allowed to write profile/. It never prints profile contents: output is
file names, counts and the evidence verbatim check.

  .venv/bin/python scripts/seed_profile.py [--src DIR] [--dest DIR] [--force]

Re-running is safe: identical files are skipped; a differing file is refused unless --force
(the old copy is then kept as <name>.bak-<timestamp> in the same directory).
evidence.yaml is always rebuilt (deterministic, no LLM).
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobwatch.apply.evidence import build_evidence, check_evidence  # noqa: E402
from jobwatch.apply.paths import profile_dir  # noqa: E402

SRC = Path("~/archive/job-system-20261004/workspace/job-tracker/agent/candidate-profile").expanduser()
FILES = ["master_resume.md", "profile.yaml", "career_ops_profile.md",
         "transferable_skills_taxonomy.yaml", "interests_and_criteria.yaml"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--dest", type=Path, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    dest = Path(args.dest or profile_dir()).expanduser()
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    for name in FILES:
        src = args.src / name
        if not src.is_file():
            print(f"missing in source (skipped): {name}")
            continue
        target = dest / name
        if target.exists():
            if filecmp.cmp(src, target, shallow=False):
                print(f"unchanged: {name}")
                os.chmod(target, 0o600)
                continue
            if not args.force:
                print(f"REFUSED: {name} differs from the source; re-run with --force", file=sys.stderr)
                return 1
            shutil.copy2(target, dest / f"{name}.bak-{stamp}")
            os.chmod(dest / f"{name}.bak-{stamp}", 0o600)
        shutil.copyfile(src, target)          # copy, never move
        os.chmod(target, 0o600)
        print(f"copied: {name}")
    cv = dest / "cv.md"
    if not cv.exists() and (dest / "master_resume.md").exists():
        cv.symlink_to("master_resume.md")     # PLAN D2 name -> the real file
    items = build_evidence(dest)
    problems = check_evidence(dest, items)
    if problems:
        print(f"evidence verbatim check FAILED for {len(problems)} item(s): {problems[:10]}", file=sys.stderr)
        return 1
    doc = {"version": 1, "generated_at": datetime.now().isoformat(timespec="seconds"),
           "generator": "scripts/seed_profile.py (deterministic, no LLM)", "items": items}
    ev = dest / "evidence.yaml"
    tmp = dest / ".evidence.yaml.tmp"
    tmp.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ev)
    by_kind: dict[str, int] = {}
    by_src: dict[str, int] = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
        by_src[it["source_file"]] = by_src.get(it["source_file"], 0) + 1
    print(f"evidence.yaml: {len(items)} items; by kind {by_kind}; by source {by_src}; verbatim check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
