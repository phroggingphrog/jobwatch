"""CLI hooks (picked up by cli._extensions):

  jobwatch prescreen words list [--category C] [--all]
  jobwatch prescreen words add --category C --term T [--match word|phrase|regex] [--applies-to title|location|hours|ad_text]
                               [--value V] [--strength obvious|weak] [--polarity exclude|allow] [--field-tag TAG]
  jobwatch prescreen words disable ID [--enable]
  jobwatch prescreen rules list | add --kind K --params JSON [--effect skip|flag] | disable ID [--enable]
  jobwatch prescreen test TITLE [--location L] [--hours H] [--ad-text-file F] [--remote]   (no model, nothing saved)
  jobwatch prescreen stats                      hit counts per term from recorded decisions
  jobwatch prescreen override POSTING_ID [--posting-only]   take a skip back for this person
"""
from __future__ import annotations

import json
import sys

from . import store


def register(sub) -> None:
    p = sub.add_parser("prescreen", help="early deterministic screening: words, rules, test, stats, override")
    ps = p.add_subparsers(dest="prescreen_cmd", required=True)
    w = ps.add_parser("words").add_subparsers(dest="action", required=True)
    wl = w.add_parser("list")
    wl.add_argument("--category", choices=store.CATEGORIES)
    wl.add_argument("--all", action="store_true", help="include disabled terms")
    wa = w.add_parser("add")
    wa.add_argument("--category", required=True, choices=store.CATEGORIES)
    wa.add_argument("--term", required=True)
    wa.add_argument("--match", default="word", choices=store.MATCH_TYPES)
    wa.add_argument("--applies-to", default="title", choices=store.APPLIES_TO)
    wa.add_argument("--value")
    wa.add_argument("--strength", default="weak", choices=("obvious", "weak"))
    wa.add_argument("--polarity", default="exclude", choices=("exclude", "allow"))
    wa.add_argument("--field-tag")
    wd = w.add_parser("disable")
    wd.add_argument("id", type=int)
    wd.add_argument("--enable", action="store_true")
    r = ps.add_parser("rules").add_subparsers(dest="action", required=True)
    r.add_parser("list")
    ra = r.add_parser("add")
    ra.add_argument("--kind", required=True, choices=store.RULE_KINDS)
    ra.add_argument("--params", required=True, help="JSON object")
    ra.add_argument("--effect", default="skip", choices=("skip", "flag"))
    rd = r.add_parser("disable")
    rd.add_argument("id", type=int)
    rd.add_argument("--enable", action="store_true")
    t = ps.add_parser("test", help="show which terms and rules fire on a title/location, no model")
    t.add_argument("title")
    t.add_argument("--location", default="")
    t.add_argument("--hours", default="")
    t.add_argument("--remote", action="store_true")
    t.add_argument("--ad-text-file")
    ps.add_parser("stats")
    o = ps.add_parser("override")
    o.add_argument("posting_id", type=int)
    o.add_argument("--posting-only", action="store_true", help="admit this posting only; keep the term active")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) != "prescreen":
        return None
    from jobwatch import db as dbm
    from jobwatch.config import load_config
    conn = dbm.connect(load_config(args.config_dir).db_path)
    try:
        return _run(conn, args)
    finally:
        conn.close()


def _run(conn, a) -> int:
    from jobwatch import users
    from jobwatch.candidate.policy import policy_for
    c = a.prescreen_cmd
    if c == "words":
        if a.action == "list":
            q = "SELECT * FROM prescreen_terms WHERE (enabled=1 OR ?) AND (? IS NULL OR category=?) ORDER BY category, id"
            for r in conn.execute(q, (int(a.all), a.category, a.category)):
                print(f"{r['id']:>5} {'on ' if r['enabled'] else 'off'} {r['category']:<22} {r['strength']:<7} {r['polarity']:<7} "
                      f"{r['applies_to']:<8} {r['match_type']:<6} {r['value'] or '-':<18} {r['term']}  [{r['scope']}]")
        elif a.action == "add":
            try:
                tid = store.add_term(conn, category=a.category, term=a.term, match_type=a.match, applies_to=a.applies_to,
                                     polarity=a.polarity, strength=a.strength, value=a.value, field_tag=a.field_tag)
            except ValueError as exc:
                print(f"not added: {exc}")
                return 2
            print(f"added term {tid}")
        else:
            print("ok" if store.set_term_enabled(conn, a.id, a.enable) else "no such term")
        return 0
    if c == "rules":
        if a.action == "list":
            for r in conn.execute("SELECT * FROM prescreen_rules ORDER BY id"):
                print(f"{r['id']:>4} {'on ' if r['enabled'] else 'off'} {r['kind']:<19} {r['effect']:<5} [{r['source']}] {r['params_json']}")
        elif a.action == "add":
            try:
                params = json.loads(a.params)
                if not isinstance(params, dict):
                    raise ValueError("params must be a JSON object")
                print(f"added rule {store.add_rule(conn, kind=a.kind, params=params, effect=a.effect)}")
            except ValueError as exc:
                print(f"not added: {exc}")
                return 2
        else:
            print("ok" if store.set_rule_enabled(conn, a.id, a.enable) else "no such rule")
        return 0
    if c == "test":
        from .engine import Engine, PostingFields
        eng = Engine.load(conn, policy_for(users.current()))
        text = open(a.ad_text_file, encoding="utf-8").read() if a.ad_text_file else ""
        pf = PostingFields(title=a.title, location=a.location, hours=a.hours, ad_text=text, remote=a.remote)
        for h in eng.parse(pf):
            print(f"hit  term {h.term_id:<5} {h.category:<22} {h.strength:<7} {h.applies_to:<8} value={h.value} n={h.n} text={h.text!r}")
        out = eng.evaluate(pf)
        print(f"outcome: {out.outcome}" + (f"  rule {out.rule_id}  term {out.term_id}: {out.reason}" if out.outcome != "admit" else ""))
        return 0
    if c == "stats":
        for r in store.stats(conn):
            print(f"{r['id']:>5} {r['category']:<22} skips={r['skips'] or 0:<4} flags={r['flags'] or 0:<4} overridden={r['overridden']:<2} "
                  f"{'on ' if r['enabled'] else 'off'} {r['strength']:<7} {r['term']}")
        return 0
    if c == "override":
        from .lifecycle import override_skip
        print(json.dumps(override_skip(conn, a.posting_id, term_too=not a.posting_only)))
        return 0
    print("unknown prescreen command", file=sys.stderr)
    return 2
