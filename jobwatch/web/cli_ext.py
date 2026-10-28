"""CLI hooks (picked up by cli._extensions):

  jobwatch web [--host 127.0.0.1] [--port 8960]                       serve the board
  jobwatch design notes [--open] [--md] [--all] [--page PATH]         design notes as Markdown (open ones by default)
  jobwatch design resolve ID [--note TEXT]                            mark a design note resolved
  jobwatch design add-image PATH --title T [--source-url U]           add a reference image (same checks as the upload)
"""
from __future__ import annotations

DEFAULT_PORT = 8960


def register(sub) -> None:
    p = sub.add_parser("web", help="serve the personal job board (loopback only)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)

    sub.add_parser("ask-missing", help="count form answers still missing and tell the owner (once) to answer them in Chat")

    d = sub.add_parser("design", help="design notes and reference images from the web board's Design area")
    ds = d.add_subparsers(dest="design_cmd", required=True)
    n = ds.add_parser("notes", help="print design notes as Markdown (open notes unless --all)")
    n.add_argument("--open", action="store_true", help="only open notes (the default)")
    n.add_argument("--md", action="store_true", help="Markdown output (the default; accepted for clarity)")
    n.add_argument("--all", action="store_true", help="include resolved notes")
    n.add_argument("--page", default="", help="only notes on this page path, e.g. / or /table or /design/ref/3")
    r = ds.add_parser("resolve", help="mark a design note resolved")
    r.add_argument("id", type=int)
    r.add_argument("--note", default="", help="what was done (optional)")
    a = ds.add_parser("add-image", help="add a local PNG/JPEG/WebP as a reference image")
    a.add_argument("path")
    a.add_argument("--title", default="", help="title (defaults to the file name)")
    a.add_argument("--source-url", default="", help="where the image came from (stored as text only)")


def handle(args) -> int | None:
    if getattr(args, "cmd", None) == "design":
        return _design(args)
    if getattr(args, "cmd", None) == "ask-missing":
        from .ask_cards import notify_missing
        print(f"{notify_missing()} questions waiting in Chat")
        return 0
    if getattr(args, "cmd", None) != "web":
        return None
    import uvicorn

    from ..config import load_config
    from ..origin_guard import check_bind
    from .app import create_app
    check_bind(args.host)
    uvicorn.run(create_app(load_config(args.config_dir)), host=args.host, port=args.port,
                log_level="warning", proxy_headers=False, server_header=False)
    return 0


def _design(args) -> int:
    from .. import db as dbm
    from ..config import load_config
    from . import design
    conn = dbm.connect(load_config(getattr(args, "config_dir", None)).db_path)
    try:
        if args.design_cmd == "notes":
            print(design.cli_notes(conn, include_resolved=args.all and not args.open, page=args.page))
        elif args.design_cmd == "resolve":
            print(design.cli_resolve(conn, args.id, args.note))
        elif args.design_cmd == "add-image":
            ref = design.cli_add_image(conn, args.path, args.title, args.source_url)
            print(f"added reference #{ref['id']} \"{ref['title']}\" ({ref['width']}x{ref['height']}); "
                  f"open /design/ref/{ref['id']} on the board")
    except design.DesignError as exc:
        print(f"design: {exc}")
        return 1
    finally:
        conn.close()
    return 0
