"""CLI hooks (picked up by cli._extensions). Run as one person with `jobwatch --user NAME ...`.

  jobwatch notify channels list
  jobwatch notify channels add NAME --kind ssh_append --set host=user@host --set file=~/jobwatch-notify.txt
  jobwatch notify channels add NAME --kind webhook --set url_ref=env:MY_WEBHOOK_URL
  jobwatch notify channels add NAME --kind command --config-json '{"argv": ["notify-send", "Jobwatch"]}'
  jobwatch notify channels disable NAME
  jobwatch notify channels test NAME

Secrets are never typed here: use a `_ref` value (`env:NAME` or `file:/path`).
"""
from __future__ import annotations

import json
import sqlite3


def register(sub) -> None:
    p = sub.add_parser("notify", help="where jobwatch tells you about failures: notification channels")
    ns = p.add_subparsers(dest="notify_cmd", required=True)
    ch = ns.add_parser("channels", help="list, add, disable or test a channel")
    cs = ch.add_subparsers(dest="channels_cmd", required=True)
    cs.add_parser("list", help="show this person's channels")
    add = cs.add_parser("add", help="create a channel, or replace one with the same name")
    add.add_argument("name")
    add.add_argument("--kind", required=True, help="none, ssh_append, command or webhook")
    add.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a config value (repeatable)")
    add.add_argument("--config-json", help="the whole config as JSON (for lists such as argv)")
    add.add_argument("--events", default="failure,action_required", help="comma list of failure, completion, action_required")
    add.add_argument("--digest", action="append", default=[], metavar="GROUP=SECONDS",
                     help="batch a group of events, e.g. incident=21600; 0 = send each at once")
    dis = cs.add_parser("disable", help="turn a channel off")
    dis.add_argument("name")
    tst = cs.add_parser("test", help="send a harmless test event and print the receipt")
    tst.add_argument("name")


def _conn():
    from jobwatch.config import load_config
    from jobwatch.db import connect
    return connect(load_config().db_path)


def _show(cfg) -> str:
    cfg_text = ", ".join(f"{k}={json.dumps(v) if isinstance(v, list) else v}" for k, v in sorted(cfg.config.items()))
    digest = ",".join(f"{k}={v}s" for k, v in sorted(cfg.digest.items())) or "-"
    return (f"{cfg.name}\t{cfg.kind}\t{'enabled' if cfg.enabled else 'disabled'}\tevents={','.join(cfg.events)}"
            f"\tdigest={digest}\tsource={cfg.source}\t{cfg_text}")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) != "notify":
        return None
    from jobwatch import notifier
    conn = _conn()
    try:
        notifier.ensure(conn)
        action = args.channels_cmd
        if action == "list":
            found = notifier.channels_for(conn, include_disabled=True)
            for cfg in found:
                print(_show(cfg))
            if not found:
                print("No channel: messages stay in the Chat page.")
            return 0
        if action == "add":
            config = json.loads(args.config_json) if args.config_json else {}
            for item in args.set:
                key, sep, val = item.partition("=")
                if not sep:
                    print(f"Use KEY=VALUE, not '{key}'.")
                    return 2
                config[key.strip()] = val
            digest = {}
            for item in args.digest:
                key, _, val = item.partition("=")
                digest[key.strip()] = int(val)
            cfg = notifier.add_channel(conn, args.name, args.kind, config,
                                       events=[e.strip() for e in args.events.split(",") if e.strip()],
                                       digest=digest or None)
            print("Saved:", _show(cfg))
            return 0
        if action == "disable":
            if notifier.disable_channel(conn, args.name):
                print(f"Disabled {args.name}.")
                return 0
            print(f"No channel called {args.name}.")
            return 1
        cfg, receipt, healthy = notifier.test_channel(conn, args.name)
        print(json.dumps({"channel": cfg.name, "kind": cfg.kind, "healthy": healthy, "status": receipt.status,
                          "detail": receipt.detail}))
        return 0 if receipt.ok else 1
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"Not done: {exc}" if isinstance(exc, ValueError) else "Not done: bad input or database error.")
        return 2
    finally:
        conn.close()
