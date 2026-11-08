"""Fail when owner-private config or personal data is tracked in Git.

Run locally with `python scripts/check_personal_data.py`, optionally passing the
owner's identifiers with `--identifiers` or JOBWATCH_OWNER_IDENTIFIERS (comma
separated). CI cannot hold those identifiers, so CI enforces the private-config
and secret parts; the identifier check is for the owner's own pre-push runs.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Real owner config. Only the neutral *.example.* files are tracked; see docs/configuration.md.
PRIVATE_CONFIG = (
    "config/jobwatch.yaml",
    "config/rules.yaml",
    "config/searches.yaml",
    "config/feeds.yaml",
    "config/employers.yaml",
    "config/vic_localities.txt",
)
SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
)
MAX_BYTES = 2_000_000
SELF = "scripts/check_personal_data.py"


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True,
                         capture_output=True).stdout
    return [name for name in out.decode("utf-8", "replace").split("\0") if name]


def _text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_BYTES or b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "ignore")


def findings(root: Path, identifiers: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for name in tracked(root):
        if name in PRIVATE_CONFIG:
            found.append(f"{name}: owner-private configuration must not be tracked")
        if name == SELF:
            continue
        text = _text(root / name)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    found.append(f"{name}:{lineno}: {label} committed")
            folded = line.casefold()
            for identifier in identifiers:
                if identifier.casefold() in folded:
                    found.append(f"{name}:{lineno}: owner identifier committed")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to scan")
    parser.add_argument("--identifiers", default=os.environ.get("JOBWATCH_OWNER_IDENTIFIERS", ""),
                        help="comma/newline separated owner identifiers; never commit them")
    args = parser.parse_args(argv)
    identifiers = tuple(part.strip() for part in re.split(r"[,\n]", args.identifiers)
                        if part.strip())
    found = findings(Path(args.root).resolve(), identifiers)
    if found:
        print("\n".join(found))
        print(f"personal-data guard: {len(found)} finding(s)", file=sys.stderr)
        return 1
    print("personal-data guard: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
