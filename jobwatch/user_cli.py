"""CLI hooks (picked up by cli._extensions):

  jobwatch user list                       names of the people who have a folder or an account
  jobwatch user set-password NAME          set or reset a password (asked twice, never shown)
  jobwatch user invite [--show]            make a new sign-up invite code and save it in the settings file
"""
from __future__ import annotations

import getpass
import os
import re
import secrets
import shutil
import time
from pathlib import Path

KEEP_BACKUPS = 3


def register(sub) -> None:
    p = sub.add_parser("user", help="people and sign-in: list, set-password, invite")
    us = p.add_subparsers(dest="user_cmd", required=True)
    us.add_parser("list", help="print the names of the people")
    sp = us.add_parser("set-password", help="set or reset one person's password (creates the person if new)")
    sp.add_argument("name")
    iv = us.add_parser("invite", help="make a new invite code and write it to the settings file")
    iv.add_argument("--show", action="store_true", help="also print the code, once")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) != "user":
        return None
    return {"list": _list, "set-password": _set_password, "invite": _invite}[args.user_cmd](args)


def _names() -> list[str]:
    from . import users
    from .web import auth_routes
    return sorted(set(users.list_users()) | set(auth_routes._load()))


def _list(args) -> int:
    for n in _names():
        print(n)
    return 0


def _set_password(args) -> int:
    from . import users
    from .web import auth_routes
    name = args.name.strip().lower()
    if not users.valid_name(name):
        print("That is not a valid name: use 2 to 31 letters, numbers, - or _, starting with a letter.")
        return 2
    pw = getpass.getpass("New password: ")
    if len(pw) < 8:
        print("Use a password of at least 8 characters.")
        return 2
    if getpass.getpass("Again: ") != pw:
        print("The two passwords do not match. Nothing changed.")
        return 2
    users.create_user_dirs(name)
    auth_routes.set_password(name, pw)
    print(f"Password set for {name}.")
    return 0


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    dest_dir = Path.home() / "backups" / "jobwatch"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    for old in sorted(dest_dir.glob(f"{path.name}.*"))[:-KEEP_BACKUPS]:
        old.unlink()
    return dest


def _invite(args) -> int:
    raw = os.environ.get("JOBWATCH_SETTINGS")
    if not raw:
        print("JOBWATCH_SETTINGS is not set; it must name the env file the web service reads.")
        return 2
    path = Path(os.path.expanduser(raw))
    code = secrets.token_urlsafe(9)
    _backup(path)
    lines = path.read_text().splitlines() if path.exists() else []
    new = f"JOBWATCH_INVITE_CODE={code}"
    pat = re.compile(r"^\s*(export\s+)?JOBWATCH_INVITE_CODE\s*=")
    out, replaced = [], False
    for ln in lines:
        if pat.match(ln):
            if not replaced:
                out.append(new)
                replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    os.chmod(path, 0o600)
    print(f"Invite code saved in {path}")
    print("restart jobwatch-native-web to apply")
    if args.show:
        print(f"Invite code: {code}")
    return 0
