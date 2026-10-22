"""`jobwatch baseline`: freeze, list, show and label the current person's frozen evaluation baselines.

`label` writes the owner's own judgment and runs only at a terminal. `show` prints ids, counts and states, never
candidate or posting text."""
import json
import sqlite3
import sys

_YES_NO_UNSURE = {"yes": True, "no": False, "unsure": None}
LABEL_HELP = ("record the owner's judgment of one case. A label needs a judgment field "
              "(--suitable, --relevance or --exclusion-violation) or a --tag; a note alone is refused. "
              "Runs only at a terminal.")


def register(sub):
    parser = sub.add_parser("baseline", help="frozen evaluation baselines for the current person (--user <name>)")
    actions = parser.add_subparsers(dest="baseline_action", required=True)
    freeze = actions.add_parser("freeze", help="freeze the stored inputs and outputs of the newest evaluated runs "
                                               "(reads the database read-only, calls no model)")
    freeze.add_argument("--limit", type=int, default=500, help="most postings to freeze (default 500)")
    freeze.add_argument("--posting-id", type=int, action="append", metavar="ID",
                        help="freeze only this posting; repeat for more")
    actions.add_parser("list", help="list this person's baselines")
    show = actions.add_parser("show", help="show a baseline's record, label counts and states (no candidate text)")
    show.add_argument("baseline_id")
    show.add_argument("--cases", action="store_true", help="also list one line per case")
    label = actions.add_parser("label", help=LABEL_HELP, description=LABEL_HELP)
    label.add_argument("baseline_id")
    label.add_argument("case_id")
    label.add_argument("--suitable", choices=list(_YES_NO_UNSURE), help="is the case suitable for the candidate")
    label.add_argument("--relevance", type=int, help="relevance 0 to 3")
    label.add_argument("--exclusion-violation", choices=list(_YES_NO_UNSURE),
                       help="does the case violate an explicit exclusion")
    label.add_argument("--allow-holdout", action="store_true", help="explicit audited holdout access")
    label.add_argument("--note", default="", help="free note; never counts as a judgment by itself")
    label.add_argument("--tag", action="append", default=[], metavar="TAG", help="owner tag; repeat for more")


def handle(args):
    if getattr(args, "cmd", None) != "baseline":
        return None
    from pipeline.agentic.contracts import AgenticError
    try:
        return _ACTIONS[args.baseline_action](args)
    except AgenticError as exc:
        print(exc.code, file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error):
        print("baseline_operation_unavailable", file=sys.stderr)
        return 1


def _freeze(args):
    from .config import load_config
    from pipeline.agentic import baseline
    config = load_config(args.config_dir)
    conn = sqlite3.connect(f"file:{config.db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        record = baseline.freeze_baseline(conn, config, posting_ids=args.posting_id, limit=args.limit)
    finally:
        conn.close()
    skipped = sum(record.summary.get("skipped", {}).values())
    print(f"froze {record.baseline_id}: {len(record.case_ids)} cases, {skipped} skipped")
    if baseline.current_gate_version() != baseline.PRE_REVISION_GATE_VERSION:
        print("warning: the gate source differs from the pre-revision release; "
              "this baseline captures the revised gate", file=sys.stderr)
    return 0


def _gate_state(record):
    from pipeline.agentic import baseline
    return "pre_revision" if record.gate_version == baseline.PRE_REVISION_GATE_VERSION else "revised"


def _list(args):
    from pipeline.agentic import baseline
    records = baseline.list_baselines()
    if not records:
        print("no baselines")
        return 0
    for r in records:
        print(f"{r.baseline_id}  {r.created_at}  cases={len(r.case_ids)}  profile_version={r.profile_version}  "
              f"gate={_gate_state(r)}")
    return 0


def _show(args):
    from pipeline.agentic import baseline
    record, cases = baseline.load_baseline(args.baseline_id)
    latest = baseline.latest_labels(baseline.read_labels(args.baseline_id))
    labelled = sum(1 for case in cases if case.case_id in latest)
    shown = record.model_dump(mode="json")
    shown.pop("case_sha256", None)
    shown["labels"] = {"labelled": labelled, "unlabelled": len(cases) - labelled}
    shown["gate_state"] = _gate_state(record)
    shown["gate_changed_since_freeze"] = record.gate_version != baseline.current_gate_version()
    shown["missing_tags"] = [tag for tag in baseline.TAGS if not any(tag in c.tags for c in cases)]
    print(json.dumps(shown, indent=2, sort_keys=True))
    if args.cases:
        for case in cases:
            tags = ",".join(baseline.effective_tags(case, latest)) or "-"
            route = f"{case.decision.get('route', 'error')}/{case.decision.get('reason', '-')}"
            print(f"{case.case_id} {case.posting_id} {route} {tags}")
    return 0


def _is_terminal():
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def _label(args):
    if not _is_terminal():      # an agent running shell commands has no terminal and cannot label
        print("human_required", file=sys.stderr)
        return 1
    from pipeline.agentic import baseline
    from pipeline.agentic import eval_data
    split_path = baseline._baseline_dir(args.baseline_id) / 'evaluation' / 'split.json'
    if split_path.exists():
        split = eval_data.load_split(args.baseline_id)
        if args.case_id in split['holdout']:
            eval_data.audit_holdout(args.baseline_id, 'label', allow_holdout=getattr(args, 'allow_holdout', False))
    baseline.label_case(args.baseline_id, args.case_id, actor="owner",     # at a terminal this is the owner's own act
                        suitable=_YES_NO_UNSURE[args.suitable] if args.suitable else None,
                        relevance=args.relevance,
                        exclusion_violation=_YES_NO_UNSURE[args.exclusion_violation] if args.exclusion_violation else None,
                        note=args.note, tags=tuple(args.tag))
    print(f"labelled {args.case_id}")
    return 0


_ACTIONS = {"freeze": _freeze, "list": _list, "show": _show, "label": _label}
