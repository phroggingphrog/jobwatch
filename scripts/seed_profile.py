"""Explicit local profile import. Copies only named inputs; never logs their text."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import yaml

from jobwatch.apply.evidence import build_evidence, check_evidence
from jobwatch.apply.paths import profile_dir

FILES = ('master_resume.md', 'profile.yaml', 'transferable_skills_taxonomy.yaml', 'career_ops_profile.md')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Copy an explicitly selected profile into private Jobwatch storage.')
    parser.add_argument('--src', type=Path, required=True)
    parser.add_argument('--dest', type=Path)
    parser.add_argument('--force', action='store_true', help='Back up differing destination files before replacement')
    args = parser.parse_args(argv)
    try:
        source = args.src.expanduser().resolve()
        target = (args.dest or profile_dir()).expanduser()
        if target.is_symlink() or target.resolve() == source or not source.is_dir():
            raise ValueError
        for name in ('master_resume.md', 'profile.yaml'):
            if not (source / name).is_file():
                raise ValueError
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='jobwatch-profile-import-', dir=target.parent) as directory:
            stage = Path(directory)
            for name in FILES:
                item = source / name
                if item.is_symlink():
                    raise ValueError
                if item.is_file():
                    shutil.copyfile(item, stage / name)
                    (stage / name).chmod(0o600)
            items = build_evidence(stage)
            if check_evidence(stage, items):
                raise ValueError
            (stage / 'evidence.yaml').write_text(yaml.safe_dump({'items': items}, sort_keys=False))
            (stage / 'evidence.yaml').chmod(0o600)
            (stage / 'cv.md').symlink_to('master_resume.md')
            differing = []
            for item in stage.iterdir():
                existing = target / item.name
                if existing.is_symlink():
                    if item.name != 'cv.md' or os.readlink(existing) != 'master_resume.md':
                        raise ValueError
                    continue
                if existing.exists() and (not existing.is_file() or existing.read_bytes() != item.read_bytes()):
                    differing.append(existing)
            if differing and not args.force:
                print('Profile differs; import refused. Use --force only to back up and replace existing inputs.')
                return 1
            if differing:
                backup = Path.home() / 'backups' / 'jobwatch'
                backup.mkdir(parents=True, exist_ok=True)
                identity = hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:12]
                stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
                for existing in differing:
                    saved = backup / f'{existing.name}.{identity}.{stamp}'
                    shutil.copyfile(existing, saved)
                    saved.chmod(0o600)
                    for old in sorted(backup.glob(f'{existing.name}.{identity}.*'), reverse=True)[3:]:
                        old.unlink()
            target.mkdir(parents=True, mode=0o700, exist_ok=True)
            target.chmod(0o700)
            for item in stage.iterdir():
                existing = target / item.name
                if item.is_symlink():
                    os.replace(item, existing)
                else:
                    os.replace(item, existing)
                    existing.chmod(0o600)
        print('Profile copied with private permissions and verified evidence; source retained.')
        return 0
    except (OSError, ValueError, yaml.YAMLError):
        print('Profile import refused; check source files and destination. No source data was moved.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
