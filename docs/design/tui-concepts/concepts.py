"""Static TUI design concepts for Jobwatch (synthetic data, no model calls)."""
import asyncio, sys
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static, DataTable, Collapsible, Label, Rule

T = lambda s, **k: Static(s, markup=True, **k)

class C1(App):
    """Concept 1: Claude-Code style transcript with collapsible tool blocks + plan."""
    TITLE = "Jobwatch — 1 · Conversation first"
    CSS = """
    #log { padding: 0 1; height: 1fr; }
    .you { color: $accent; margin-top: 1; }
    .tool { color: $text-muted; }
    #plan { border: round $primary; padding: 0 1; height: auto; margin: 1 0; }
    #status { height: 1; background: $boost; padding: 0 1; color: $text-muted; }
    Collapsible { border: none; padding: 0; }
    """
    def compose(self) -> ComposeResult:
        with VerticalScroll(id="log"):
            yield T("[dim]Jobwatch · owner · thread jw-1025 · model claude/sonnet[/dim]")
            yield T("› find analyst roles this week and prepare the best one", classes="you")
            with Vertical(id="plan"):
                yield T("[b]Plan[/b]")
                yield T("[green]✓[/green] Read 14 new postings")
                yield T("[green]✓[/green] Assess fit against your profile")
                yield T("[yellow]●[/yellow] Draft CV + letter for Acme Data Analyst")
                yield T("[dim]○ Fill the form, stop before Submit[/dim]")
            with Collapsible(title="⏺ ranked_shortlist ✓ 0.6s  (5 jobs)", collapsed=True):
                yield T("…")
            with Collapsible(title="⏺ assess_job #42 Acme ✓ 2.1s  score 4/5", collapsed=False):
                yield T("  [green]+[/green] SQL, Python, dashboards match 3 of 4 must-haves\n  [yellow]?[/yellow] 'Tableau preferred' — not in profile\n  [green]+[/green] Melbourne hybrid · graduate level")
            yield T("\n[b]jobwatch[/b]  Acme is the strongest match (4/5). Drafting now; I'll show the exact form before anything is sent.")
        yield T("● drafting · Acme #42 · 3 tools · 12.4k tokens · $0.04", id="status")
        yield Input(placeholder="Ask Jobwatch…   /jobs  /stop  /resume")
        yield Footer()

class C2(App):
    """Concept 2: Mission control — job queue left, conversation right."""
    TITLE = "Jobwatch — 2 · Mission control"
    CSS = """
    #left { width: 46; border-right: solid $primary-darken-2; }
    #right { padding: 0 1; }
    #queue { height: 1fr; }
    #inbox { height: auto; border: round $warning; padding: 0 1; margin: 0 1 1 1; }
    #convo { height: 1fr; }
    .h { background: $boost; padding: 0 1; text-style: bold; }
    """
    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left"):
                yield T("Pipeline", classes="h")
                t = DataTable(id="queue", cursor_type="row", zebra_stripes=True)
                yield t
                with Vertical(id="inbox"):
                    yield T("[b][yellow]Needs you (2)[/yellow][/b]")
                    yield T("1 Submit Acme #42?   [b]a[/b]/[b]r[/b]/[b]v[/b]iew")
                    yield T("2 Start date for Globex?  type answer")
            with Vertical(id="right"):
                yield T("Acme · Data Analyst · #42", classes="h")
                with VerticalScroll(id="convo"):
                    yield T("[accent]›[/] prepare it")
                    yield T("[dim]⏺ assess_job ✓ · draft_cv ✓ · draft_letter ✓ · fill_form ✓[/dim]")
                    yield T("\n[b]jobwatch[/b]  Form filled up to Submit. 11 fields, CV v3, letter v2. Review it with [b]v[/b] or say 'submit'.")
                yield Input(placeholder="Talk about Acme #42…")
        yield Footer()
    def on_mount(self):
        t = self.query_one(DataTable)
        t.add_columns("#", "Role", "Fit", "State")
        for r in [("42","Acme · Data Analyst","4/5","[yellow]awaiting approval[/]"),
                  ("51","Globex · BI Grad","4/5","[cyan]needs info[/]"),
                  ("38","Initech · Ops Analyst","3/5","drafting"),
                  ("29","Umbrella · Data Intern","3/5","[green]submitted[/]"),
                  ("17","Hooli · Analyst","2/5","[dim]skipped[/]"),
                  ("12","Vandelay · Reporting","?","[red]outcome unknown[/]")]:
            from rich.text import Text
            t.add_row(*[Text.from_markup(x) for x in r])

class C3(App):
    """Concept 3: Review & confirm screen before Submit."""
    TITLE = "Jobwatch — 3 · Review before Submit"
    CSS = """
    #card { border: heavy $warning; margin: 1 2; padding: 0 2; height: auto; }
    #fields { height: auto; margin: 1 0; }
    #actions { height: 3; }
    .btn { width: auto; margin-right: 2; padding: 0 2; background: $boost; }
    .ok { background: $success-darken-2; }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield T("[b]Submit application A18?[/b]   Acme Pty Ltd · Data Analyst · careers.acme.example/apply/42")
            yield Rule()
            t = DataTable(id="fields", show_cursor=False)
            yield t
            yield T("Documents  [b]CV v3[/b] (2 pages, verified) · [b]Letter v2[/b] (1 page, verified)")
            yield T("Changed since last review: [yellow]start date 1 Dec[/yellow]   ·   form fingerprint 7c1e…a9   ·   expires in 4:52")
            yield Rule()
            with Horizontal(id="actions"):
                yield T("[b]Enter[/b] Submit A18", classes="btn ok")
                yield T("[b]e[/b] Edit", classes="btn")
                yield T("[b]r[/b] Reject", classes="btn")
                yield T("[b]o[/b] Open form", classes="btn")
        yield T("  [dim]Nothing is sent until you press Enter or reply 'Submit A18' in chat.[/dim]")
        yield Footer()
    def on_mount(self):
        t = self.query_one(DataTable)
        t.add_columns("Field", "Value", "Source")
        for r in [("Name","Alex Example","profile"),("Work rights","Full","profile"),
                  ("Start date","1 Dec 2026","you, today"),("Salary expectation","Not answered (optional)","—"),
                  ("Why Acme? (300 words)","Acme's public data team…","draft v2")]:
            t.add_row(*r)

class C4(App):
    """Concept 4: Minimal / phone-friendly single column with cards."""
    TITLE = "Jobwatch — 4 · Minimal cards"
    CSS = """
    Screen { align-horizontal: center; }
    #col { width: 72; }
    .card { border: round $primary-darken-1; padding: 0 1; margin-bottom: 1; height: auto; }
    .warn { border: round $warning; }
    """
    def compose(self) -> ComposeResult:
        with VerticalScroll(id="col"):
            yield T("[b]Today[/b]  3 new good matches · 1 needs you · 1 outcome unknown")
            yield T("[b]Acme · Data Analyst[/b]   4/5   [yellow]awaiting your OK[/yellow]\nForm filled to Submit. [b]a[/b] approve · [b]v[/b] review", classes="card warn")
            yield T("[b]Globex · BI Graduate[/b]   4/5   [cyan]needs info[/cyan]\nWhat start date can you do?", classes="card")
            yield T("[b]Vandelay · Reporting[/b]   [red]outcome unknown[/red]\nSubmit pressed, no confirmation page. Retries paused — check your email.", classes="card warn")
            yield T("[b]Umbrella · Data Intern[/b]   [green]submitted[/green] 2 days ago", classes="card")
        yield Input(placeholder="Ask or instruct…")
        yield Footer()

async def shoot(app_cls, name, size):
    app = app_cls()
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.6)
        app.save_screenshot(f"{name}.svg", path=sys.argv[1])

async def main():
    for cls, n, s in [(C1,"c1",(110,34)),(C2,"c2",(130,34)),(C3,"c3",(120,26)),(C4,"c4",(100,30))]:
        await shoot(cls, n, s)
asyncio.run(main())
print("svgs ok")
