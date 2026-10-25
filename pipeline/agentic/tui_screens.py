"""The board screens of the terminal app: Today, Jobs, Detail, Review, Applications, Inbox, Table, Sources,
Insights and Models. Each screen draws text lines from backend data (tui_data.Backend); nothing here writes
except the few keys named in each footer. Submit is only ever approved from ReviewScreen."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static

from . import tui_theme as theme
from .tui_theme import (AMBER, AMETHYST, BG, GREEN, IDLE, MUTED, NEEDS_YOU, PANEL, RED, TEXT, badge, fit, join,
                        plain, score_text, styled)
from .tui_widgets import (bar, box, btn, caps, heading, header_row, keyhint, lines_of, row, selected, wrap)

NAV = [('today', 'Today'), ('jobs', 'Jobs'), ('applications', 'Applications'), ('inbox', 'Inbox'), ('table', 'Table'),
       ('sources', 'Sources'), ('insights', 'Insights'), ('models', 'Models')]
APP_STATE = {'interested': ('○', 'saved', MUTED), 'saved': ('○', 'saved', MUTED), 'drafting': ('◐', 'drafting', AMETHYST),
             'drafted': ('●', 'drafted', AMETHYST), 'applied': ('✓', 'applied', GREEN), 'assessment': ('▶', 'assessment', AMETHYST),
             'interview': ('▶', 'interview', AMETHYST), 'offer': ('▶', 'offer', GREEN), 'rejected': ('✕', 'rejected', RED),
             'withdrawn': ('⊘', 'withdrawn', MUTED), 'skipped': ('⊘', 'hidden', MUTED), 'hidden': ('⊘', 'hidden', MUTED),
             'new': ('◌', 'new', MUTED), 'seen': ('·', 'seen', MUTED), 'closed': ('✕', 'closed', MUTED)}


def app_state(word: str | None) -> Text:
    glyph, label, colour = APP_STATE.get(word or '', ('·', word or '', MUTED))
    return styled(f'{glyph} {label}', colour)


def row_state(r: dict) -> Text:
    status = r.get('app_status') if r.get('app_status') in ('drafting', 'drafted', 'interview', 'offer', 'assessment') else r.get('status')
    return app_state(status)


def score_cell(value) -> Text:
    if value is None:
        return styled('-', MUTED)
    return styled(f'{float(value):.1f}', f'bold {GREEN}' if float(value) >= 4 else MUTED)


def pid_of(r: dict):
    return r.get('posting_id', r.get('id'))


def open_view(app, name: str, arg=None) -> None:
    """Show a board: nav boards replace the current one, detail/review/picker stack on top."""
    if name in ('detail', 'review'):
        if arg is None:
            app._say('[yellow]No job is selected. Use /job N or pick one from the queue.[/yellow]')
            return
        app.push_screen(DetailScreen(app, int(arg)) if name == 'detail' else ReviewScreen(app, int(arg)))
        return
    classes = {'today': TodayScreen, 'jobs': JobsScreen, 'applications': ApplicationsScreen, 'inbox': InboxScreen,
               'table': TableScreen, 'sources': SourcesScreen, 'insights': InsightsScreen, 'models': ModelsScreen}
    if name not in classes:
        app._say(f'[dim]{plain(name)} is not available yet[/dim]')
        return
    while len(app.screen_stack) > app.base_depth():
        app.pop_screen()
    app.push_screen(classes[name](app))


class ViewScreen(Screen):
    """Nav row, a scrolling body, one hint line and the footer; subclasses supply lines and keys."""
    kind = ''
    DEFAULT_CSS = f"""
    ViewScreen {{ layout: vertical; background: {BG}; }}
    #navrow {{ height: 1; padding: 0 1; }}
    #scroller {{ height: 1fr; }}
    #viewbody {{ height: auto; padding: 1 2 0 2; }}
    #viewhint {{ height: 1; padding: 0 2; color: {MUTED}; }}
    #viewfoot {{ height: 1; background: {PANEL}; padding: 0 1; }}
    """

    def __init__(self, app_ref) -> None:
        super().__init__()
        self.tui = app_ref
        self.backend = app_ref.backend
        self.data = None
        self.error = ''
        self.sel = 0
        self.loading = True
        self.nav_counts: dict = {}
        self.toast = ''
        self.plain_text = ''

    def compose(self) -> ComposeResult:
        yield Static('', id='navrow')
        with VerticalScroll(id='scroller'):
            yield Static('', id='viewbody')
        yield Static('', id='viewhint')
        yield Static('', id='viewfoot')

    def on_mount(self) -> None:
        self.redraw()
        self.reload()

    def on_resize(self, event) -> None:
        self.redraw()

    # ---- data
    def fetch(self):
        return None

    @work(thread=True, exclusive=True)
    def reload(self) -> None:
        try:
            data, error = self.fetch(), ''
        except Exception as exc:  # noqa: BLE001 - a missing database must not break the screen
            data, error = None, f'{type(exc).__name__}: {exc}'
        try:
            counts = self.backend.nav_counts()
        except Exception:  # noqa: BLE001
            counts = {}
        self.app.call_from_thread(self._loaded, data, error, counts)

    def _loaded(self, data, error: str, counts: dict) -> None:
        self.data, self.error, self.loading, self.nav_counts = data, error, False, counts
        self.after_load()
        self.redraw()
        self.set_timer(0.15, self.redraw)        # a second pass once the first layout has settled

    def after_load(self) -> None:
        self.sel = min(self.sel, max(self.count() - 1, 0))

    # ---- drawing
    def count(self) -> int:
        return 0

    def nav(self, width: int) -> Text:
        out = styled(' [■] jobwatch', 'bold')
        out.append('  ')
        for key, label in NAV:
            n = {'applications': self.nav_counts.get('applications'), 'inbox': self.nav_counts.get('inbox')}.get(key)
            part = Text()
            on = key == self.kind or (key == 'jobs' and self.kind == 'detail')
            part.append(label, style=f'bold underline {AMETHYST}' if on else TEXT)
            if n:
                part.append(f' {n}', style=AMETHYST)
            out.append_text(part)
            out.append('   ')
        return out

    def body(self, width: int) -> tuple[list[Text], int]:
        return [], 0

    def footer_keys(self) -> list[tuple[str, str]]:
        return []

    def hint_text(self) -> str:
        return ''

    def redraw(self) -> None:
        if self.size.width == 0:           # not laid out yet; on_resize draws it
            return
        width = max(self.size.width - 2, 40)
        self.query_one('#navrow', Static).update(self.nav(width))
        if self.loading:
            lines, at = [styled('Loading…', MUTED)], 0
        elif self.error:
            lines, at = [styled(f'✕ failed  could not load this board', RED), styled(plain(self.error)[:200], MUTED),
                         Text(''), keyhint([('r', 'try again'), ('esc', 'back')])], 0
        else:
            lines, at = self.body(width - 2)
        if self.toast:
            lines = lines + [Text(''), styled(plain(self.toast), AMBER)]
        text = Text('\n').join(lines)
        self.plain_text = text.plain
        body = self.query_one('#viewbody', Static)
        body.update(text)
        body.refresh(layout=True)
        self.query_one('#viewhint', Static).update(self.hint_text())
        left = keyhint(self.footer_keys())
        right = keyhint([('1-8', 'switch view'), ('ctrl+p', 'commands')])
        self.query_one('#viewfoot', Static).update(theme.two_col(join(' ', left), join(right, ' '), width))
        scroller = self.query_one('#scroller')
        top = scroller.scroll_y
        if at < top:
            scroller.scroll_to(y=max(at - 2, 0), animate=False)
        elif at + 3 > top + scroller.size.height - 1:
            scroller.scroll_to(y=max(at - scroller.size.height + 4, 0), animate=False)

    # ---- keys (subclasses override `handle`, never `on_key`: Textual would run both)
    def on_key(self, event) -> None:
        self.handle(event)

    def handle(self, event) -> None:
        key = event.key
        if isinstance(self.focused, Input):
            return
        if key in '12345678' and len(key) == 1:
            event.stop()
            self.tui.show_view(NAV[int(key) - 1][0])
        elif key == 'escape':
            event.stop()
            self.go_back()
        elif key in ('up', 'k'):
            event.stop()
            self.sel = max(self.sel - 1, 0)
            self.redraw()
        elif key in ('down', 'j'):
            event.stop()
            self.sel = min(self.sel + 1, max(self.count() - 1, 0))
            self.redraw()
        elif key == 'enter':
            event.stop()
            self.activate()
        elif key == 'r' and self.error:
            event.stop()
            self.loading, self.error = True, ''
            self.redraw()
            self.reload()
        else:
            self.key(key, event)

    def go_back(self) -> None:
        self.app.pop_screen()

    def activate(self) -> None:
        pass

    def key(self, key: str, event) -> None:
        pass


def big_buttons(specs: list[tuple[str, bool, int]], width: int) -> list[Text]:
    """Three-row buttons, right aligned: a filled amethyst primary and grey secondaries."""
    rows = [Text(), Text(), Text()]
    for label, primary, size in specs:
        style = f'bold {BG} on {AMETHYST}' if primary else 'bold on #27272a'
        for n, text in enumerate(['', label.center(size), '']):
            rows[n].append(text.center(size), style=style)
            rows[n].append('  ')
    for row_ in rows:
        row_.pad_left(max(width - 2 - row_.cell_len, 0))
    return rows


def needs_you(rows: list[dict], inbox: int = 0) -> list[dict]:
    """What waits on the owner, from the queue rows and the number of mail replies to confirm."""
    items = []
    for r in rows:
        title, who = plain(r.get('title') or 'job'), plain(r.get('employer') or '')
        state = r.get('state')
        if state == 'draft ready':
            items.append({'glyph': '◆', 'head': f'Check and submit: {title}', 'note': f'{who} · CV and letter are ready. You press Submit.', 'pid': r['posting_id'], 'who': who, 'title': title})
        elif state == 'awaiting browser press':
            items.append({'glyph': '◆', 'head': f'Press Submit in the browser: {title}', 'note': who, 'pid': r['posting_id'], 'who': who, 'title': title})
        elif state in ('failed', 'expired'):
            items.append({'glyph': '✕' if state == 'failed' else '◇', 'head': f'{state.capitalize()}: {title}', 'note': who, 'pid': r['posting_id'], 'who': who, 'title': title})
        elif state == 'outcome unknown':
            items.append({'glyph': '?', 'head': f'Check the employer site: {title}', 'note': f'{who} · outcome unknown; nothing resends without you.', 'pid': r['posting_id'], 'who': who, 'title': title})
    if inbox:
        items.append({'glyph': '●', 'head': f'{inbox} email repl{"y" if inbox == 1 else "ies"} to confirm', 'note': 'Jobwatch read your mail and needs a yes or no.', 'view': 'inbox'})
    return items


# ------------------------------------------------------------------------------------------------ Today
class TodayScreen(ViewScreen):
    kind = 'today'

    def fetch(self):
        rows = self.backend.overview()
        return {'today': self.backend.today(), 'rows': rows}

    def needs(self) -> list[dict]:
        return needs_you((self.data or {}).get('rows', []), self.nav_counts.get('inbox') or 0)

    def best(self) -> list[dict]:
        return ((self.data or {}).get('today') or {}).get('rows', [])[:6]

    def count(self) -> int:
        return len(self.needs()) + len(self.best())

    def body(self, width):
        today = (self.data or {}).get('today') or {}
        total = today.get('total', len(self.best()))
        prog = today.get('progress') or {}
        read, seen = prog.get('read', 0), prog.get('total', 0)
        lines = [join(styled('Today', 'bold'), styled('  ' + datetime.now().strftime('%A %-d %B'), MUTED)), Text('')]
        inner = width - 6
        pct = (read / seen) if seen else 0
        lines += box([styled(f'{total} job{"" if total == 1 else "s"} {"is" if total == 1 else "are"} worth applying to.', 'bold'),
                      styled(f'AI has read {read} of {seen} matched ads', MUTED),
                      join(bar(pct, inner - 6), styled(f' {round(pct * 100)}%', MUTED))], width)
        lines += [Text(''), caps('Needs you')]
        needs = self.needs()
        at = 0
        if not needs:
            lines.append(styled('Nothing is waiting on you.', MUTED))
        for n, item in enumerate(needs):
            colour = AMETHYST if item['glyph'] in '◆●' else AMBER if item['glyph'] == '?' else RED if item['glyph'] == '✕' else MUTED
            line = join(styled(item['glyph'] + ' ', colour), styled(item['head'], 'bold'), styled('  ' + item['note'], MUTED))
            if n == self.sel:
                at = len(lines)
            lines.append(selected(line, width, n == self.sel))
        lines += [Text(''), caps('Best matches')]
        cols = [('Score', 5), ('Title', 32), ('Company', 17), ('Where · age', 22), ('Pay', 21), ('State', 12)]
        lines.append(join(' ', header_row(cols)))
        best = self.best()
        for n, r in enumerate(best):
            idx = len(needs) + n
            loc = plain(r.get('where') or r.get('location') or '')
            age = plain(r.get('listed_ago') or '')
            line = row([(score_cell(r.get('score5')), 5), (plain(r.get('title')), 32), (plain(r.get('company')), 17),
                        (f'{loc} · {age}' if age else loc, 22), (plain(r.get('salary') or ''), 21), (row_state(r), 12)])
            if idx == self.sel:
                at = len(lines)
            lines.append(selected(line, width, idx == self.sel))
        if not best:
            lines.append(styled('No matches yet. The first run will fill this in.', MUTED))
        lines += [Text(''), join(styled('enter', AMETHYST), ' open   ', styled(f'Browse all {total} jobs: press ', MUTED), styled('2', AMETHYST))]
        return lines, at

    def footer_keys(self):
        return [('↑ ↓', 'move'), ('enter', 'open'), ('/', 'search')]

    def activate(self):
        needs = self.needs()
        if self.sel < len(needs):
            item = needs[self.sel]
            return self.tui.show_view('inbox') if item.get('view') else self.tui.show_view('detail', item['pid'])
        best = self.best()
        if self.sel - len(needs) < len(best):
            self.tui.show_view('detail', pid_of(best[self.sel - len(needs)]))


# ------------------------------------------------------------------------------------------------ Jobs
class JobsScreen(ViewScreen):
    kind = 'jobs'

    def fetch(self):
        return {'rows': self.backend.overview()}

    def count(self):
        return len((self.data or {}).get('rows', []))

    def body(self, width):
        rows = (self.data or {}).get('rows', [])
        lines = heading('Jobs', f'{len(rows)} in the queue. Newest activity first.') + [Text('')]
        if not rows:
            return lines + empty_feed(width), 0
        cols = [('Score', 5), ('State', 26), ('Employer', 24), ('Title', 36)]
        lines.append(join(' ', header_row(cols)))
        at = 0
        for n, r in enumerate(rows):
            line = row([(score_cell(r.get('score')), 5), (badge(r.get('state', '')), 26), (plain(r.get('employer') or ''), 24),
                        (plain(r.get('title') or ''), 36)])
            if n == self.sel:
                at = len(lines)
            lines.append(selected(line, width, n == self.sel))
        return lines, at

    def footer_keys(self):
        return [('↑ ↓', 'move'), ('enter', 'open job')]

    def activate(self):
        rows = (self.data or {}).get('rows', [])
        if self.sel < len(rows):
            self.tui.show_view('detail', rows[self.sel]['posting_id'])


def empty_feed(width: int) -> list[Text]:
    """First run: say what is going on and what to type."""
    return [styled('Nothing in the queue yet.', 'bold'), styled('The watcher has not found a job to score.', MUTED), Text(''),
            join(styled('/run', AMETHYST), '      start a watcher run'),
            join(styled('/profile', AMETHYST), '  check the career profile it scores against'), Text(''),
            styled('Or ask: "What is the watcher doing?"', MUTED)]


# ------------------------------------------------------------------------------------------------ Detail
class DetailScreen(ViewScreen):
    kind = 'detail'

    def __init__(self, app_ref, posting_id: int) -> None:
        super().__init__(app_ref)
        self.posting_id = posting_id

    def fetch(self):
        ctx = self.backend.job(self.posting_id)
        card = next((r for r in self.backend.overview() if r.get('posting_id') == self.posting_id), None)
        return {'ctx': ctx, 'card': card}

    def count(self):
        return 0

    def body(self, width):
        ctx = (self.data or {}).get('ctx') or {}
        card = (self.data or {}).get('card') or {}
        job, ai, draft = ctx.get('job') or {}, (ctx.get('job') or {}).get('ai') or {}, ctx.get('draft') or {}
        app = ctx.get('app') or {}
        lines = [styled('← Jobs (esc)', MUTED), styled(plain(job.get('title') or f'Job {self.posting_id}'), 'bold')]
        sub = ' · '.join(x for x in (plain(job.get('company') or ''), plain(job.get('where') or job.get('location') or ''),
                                      f'Posted {plain(job.get("posted_ago"))} ago' if job.get('posted_ago') else '') if x)
        state = badge(card['state']) if card.get('state') else app_state((app or {}).get('status') or job.get('status'))
        lines.append(theme.two_col(styled(sub, MUTED), join(state, '   '), min(width, 100)))
        if card.get('state') == 'outcome unknown':
            lines += [Text('')] + outcome_unknown_lines(card, job, width)
        lines.append(Text(''))
        rec = plain(job.get('rec_word') or ai.get('recommendation') or 'Not read yet')
        score = job.get('score_label') or ('-  (not scored yet)' if job.get('score5') is None else score_text(job.get('score5')))
        lines += box([join(styled(rec.capitalize(), 'bold'), styled(f'  score {plain(score)}', MUTED)),
                      styled(plain(ai.get('reason') or job.get('hide_sentence') or 'Nothing read about this ad yet.')[:width - 8], MUTED)],
                     width, accent=AMBER)
        lines += [Text(''), join(btn('Open the ad (o)'), ' ', btn('I applied (i)'), ' ', styled('Not for me (n)', MUTED))]
        lines.append(Text(''))
        ready = draft.get('state') == 'ready'
        files = ctx.get('draft_links') or {}
        if ready or draft.get('state') == 'running':
            head = 'CV and letter are ready.' if ready else 'Drafting your CV and letter…'
            row_ = join(btn('CV (PDF) c'), ' ', btn('Letter (PDF) l'), ' ', btn('Fill the form f', primary=True)) if ready else Text('')
            lines += box([styled(head, 'bold'), Text(''), row_], width)
        else:
            lines += box([styled('No CV or letter yet.', 'bold'), styled('Ask Jobwatch to prepare the application from the main board.', MUTED)], width)
        lines.append(Text(''))
        facts = [('Pay', job.get('salary') or '-'), ('Type', job.get('wt_label') or job.get('wt') or '-'),
                 ('Where', job.get('where') or job.get('location') or '-'), ('Found on', ', '.join(job.get('src_labels') or []) or '-'),
                 ('Posted', job.get('posted_abs') or '-')]
        cell = max((width - 4) // 5, 14)
        top, mid = Text(), Text()
        for name, value in facts:
            top.append(('┌' + '─' * (cell - 2) + '┐'), style=theme.RULE)
            top.append(' ')
        lines.append(top)
        names, vals = Text(), Text()
        for name, value in facts:
            names.append(join(styled('│ ', theme.RULE), styled(fit(name, cell - 4).ljust(cell - 4), MUTED), styled(' │', theme.RULE), ' '))
            vals.append(join(styled('│ ', theme.RULE), styled(fit(value, cell - 4).ljust(cell - 4), 'bold'), styled(' │', theme.RULE), ' '))
        lines += [names, vals]
        bottom = Text()
        for _ in facts:
            bottom.append('└' + '─' * (cell - 2) + '┘', style=theme.RULE)
            bottom.append(' ')
        lines += [bottom, Text(''), caps('About the job')]
        for block in (job.get('blocks') or [])[:6]:
            text = block.get('text') if isinstance(block, dict) else block
            lines += wrap(str(text or ''), width)
        return lines, 0

    def hint_text(self):
        return 'Fill the form opens the review tab. Nothing is sent until you approve there.'

    def footer_keys(self):
        return [('o', 'open ad'), ('f', 'fill the form'), ('i', 'I applied'), ('esc', 'back')]

    def key(self, key, event):
        ctx = (self.data or {}).get('ctx') or {}
        job = ctx.get('job') or {}
        if key == 'o':
            self.tui.open_link(job.get('url') or '')
        elif key in ('i', 'n'):
            action = 'applied' if key == 'i' else 'hide'
            try:
                self.toast = self.backend.job_action(self.posting_id, action)
            except Exception as exc:  # noqa: BLE001
                self.toast = f'could not do that: {exc}'
            self.redraw()
        elif key in ('c', 'l'):
            self.tui.open_link((ctx.get('draft_links') or {}).get('cv' if key == 'c' else 'letter') or '')
        elif key == 'f':
            self.tui.fill_form(self.posting_id)
        elif key in ('m', 'x') and ((self.data or {}).get('card') or {}).get('state') == 'outcome unknown':
            self.toast = 'Marking the outcome is not wired into the terminal yet. Check the employer site or your email, then use the web board.'
            self.redraw()


def outcome_unknown_lines(card: dict, job: dict, width: int) -> list[Text]:
    """Outcome unknown: never retried; the owner checks the employer site or email first."""
    return [join(styled('? outcome unknown', f'bold {AMBER}'), f'  {plain(card.get("employer") or job.get("company") or "")} · {plain(card.get("title") or job.get("title") or "")}'),
            *wrap(card.get('detail') or 'Outcome unknown; retries are paused. Check the employer site or your email before anything is sent again.', min(width, 60)),
            Text(''), keyhint([('enter', 'open job detail'), ('m', 'mark as submitted'), ('x', 'mark as not sent')]),
            Text(''), styled('Nothing will resend without you.', MUTED)]


# ------------------------------------------------------------------------------------------------ Review
class ReviewScreen(ViewScreen):
    """The only place a Submit is approved. Opens beside Main; esc leaves with nothing sent."""
    kind = 'review'
    DEFAULT_CSS = ViewScreen.DEFAULT_CSS

    def __init__(self, app_ref, posting_id: int | None) -> None:
        super().__init__(app_ref)
        self.posting_id = posting_id

    def fetch(self):
        return self.backend.review_form(self.posting_id) if self.posting_id is not None else {'rows': []}

    def count(self):
        return len((self.data or {}).get('rows', []))

    def waiting(self) -> bool:
        return any(i.get('type') == 'approval' and i.get('operation') == 'submit_application' for i in self.tui.pending)

    def nav(self, width):
        out = Text()
        out.append(' Main  ', style=MUTED)
        out.append(f'Review · {plain((self.data or {}).get("employer") or "")}'.rstrip(' ·'), style=f'bold underline {AMETHYST}')
        return theme.two_col(out, styled('ctrl+tab switch ', MUTED), width)

    def body(self, width):
        data = self.data or {}
        w = min(width, 100)
        pad = ' ' * ((width - w) // 2)
        employer = plain(data.get('employer') or 'the employer')
        inner = w - 6
        lines = [styled('Review before Submit'.center(inner), f'bold {AMETHYST}'), Text(''),
                 Text('The form is filled in. Check every answer and file below.'), Text('')]
        lines += box([styled(f'▲ This will send your application to {employer}. It cannot be undone.', AMBER)], inner, pad=1, edge=AMBER)
        lines.append(Text(''))
        c1, c2 = 24, 46
        lines.append(styled('Field'.ljust(c1) + 'Answer'.ljust(c2) + 'Source'.ljust(inner - c1 - c2 - 2), f'bold on #27272a'))
        at = 0
        for n, (field, answer, source) in enumerate(data.get('rows', [])):
            line = join(plain(field).ljust(c1), fit(answer, c2 - 2).ljust(c2),
                        styled(plain(source), AMETHYST if source.startswith('attached') else MUTED))
            if n == self.sel:
                line = join(styled(plain(field).ljust(c1) + fit(answer, c2 - 2).ljust(c2) + plain(source), f'bold {BG} on {AMETHYST}'))
                at = len(lines)
            lines.append(line)
        lines.append(Text(''))
        if self.waiting():
            lines += big_buttons([('Submit (a)', True, 22), ('Edit (e)', False, 14), ('Reject (r)', False, 14)], inner)
        else:
            lines.append(styled('No Submit is waiting on you. Ask Jobwatch to fill the form; it will stop here for your approval.', MUTED))
            lines += big_buttons([('Reject (r)', False, 14)], inner)
        return [join(pad, ln) for ln in box(lines, w, pad=2, edge='#5b3d8f', fill=PANEL)], at + 4

    def footer_keys(self):
        return [('↑ ↓', 'row'), ('enter', 'edit field'), ('p', 'pick file')]

    def nav_right(self):
        return 'esc back to Main, nothing sent'

    def redraw(self):
        super().redraw()
        foot = self.query_one('#viewfoot', Static)
        width = max(self.size.width - 2, 40)
        foot.update(theme.two_col(join(' ', keyhint(self.footer_keys())), join(keyhint([('esc', 'back to Main, nothing sent')]), ' '), width))

    def activate(self):
        rows = (self.data or {}).get('rows', [])
        if self.sel < len(rows):
            self.edit_field(rows[self.sel][0])

    def edit_field(self, field: str) -> None:
        self.app.pop_screen()
        self.tui.begin_edit(f'Change {plain(field)}: ')

    def key(self, key, event):
        if key == 'a':
            if not self.waiting():
                self.toast = 'Nothing to submit: no Submit is waiting on you.'
                return self.redraw()
            self.app.pop_screen()
            self.tui.decide_submit('approve')
        elif key == 'r':
            if self.waiting():
                self.app.pop_screen()
                self.tui.decide_submit('reject')
        elif key == 'e':
            self.app.pop_screen()
            self.tui.begin_edit('')
        elif key == 'p':
            self.tui.pick_file(purpose='attach')

    def handle(self, event) -> None:
        if event.key in '12345678' and len(event.key) == 1:       # digits switch boards elsewhere; here they do nothing
            event.stop()
            return
        super().handle(event)


# ------------------------------------------------------------------------------------------------ Applications
class ApplicationsScreen(ViewScreen):
    kind = 'applications'

    def fetch(self):
        return self.backend.applications()

    def items(self) -> list[dict]:
        data = self.data or {}
        return [a for _, _, apps in data.get('cols', []) for a in apps]

    def count(self):
        return len(self.items())

    def body(self, width):
        data = self.data or {}
        items = self.items()
        lines = heading('Applications', f'{data.get("total", len(items))} tracked. Jobwatch writes the CV and letter; you check the form and press Submit.') + [Text('')]
        cols = [('Job', 36), ('State', 13), ('Actions', 40)]
        lines.append(join(' ', header_row(cols)))
        at = 0
        for n, a in enumerate(items):
            on = n == self.sel
            job = join(styled(plain(a.get('title')), 'bold'), styled(' ' + plain(a.get('company')), MUTED))
            files = a.get('files') or {}
            state = a.get('status')
            second = None
            if on and state in ('interested', 'drafted', 'drafting', 'applied', 'interview', 'assessment', 'offer'):
                second = Text()
                if files.get('cv'):
                    second = join(second, btn('CV (c)'), ' ')
                if files.get('letter'):
                    second = join(second, btn('Letter (l)'), ' ')
                if state in ('interested', 'drafted', 'drafting'):
                    second = join(second, btn('Fill the form (f)', primary=True), ' ')
                second = join(second, btn('I applied (i)'))
                acts = Text('')
            elif state in ('applied', 'interview', 'assessment', 'offer'):
                acts = join(btn('CV'), ' ', btn('Letter'), ' ', btn('Fill the form'), ' ', btn('Follow-up'), ' ', btn('Interview prep'))
            else:
                acts = btn('I applied (i)') if state in ('interested',) else Text('')
            at = len(lines) if on else at
            lines.append(selected(join(row([(job, 36), (app_state(state), 13)]), acts), width, on))
            if second is not None:
                lines.append(selected(join(' ', second), width, True))
        closed = (data.get('closed') or [])
        if closed:
            lines += [Text(''), caps('Closed')]
            for a in closed:
                lines.append(join(' ', row([(join(styled(plain(a.get('title')), 'bold'), styled(' ' + plain(a.get('company')), MUTED)), 36), (app_state(a.get('status')), 13)])))
        if not items and not closed:
            lines.append(styled('No applications yet. Save a job or ask Jobwatch to prepare one.', MUTED))
        lines += [Text(''), join(styled('Prepare an interview from a job link: ', MUTED), styled('n', AMETHYST))]
        return lines, at

    def hint_text(self):
        return 'Fill the form opens the employer form pre-filled. Nothing is sent until you approve on the review tab.'

    def footer_keys(self):
        return [('↑ ↓', 'move'), ('c l f i', 'row actions'), ('n', 'interview prep')]

    def key(self, key, event):
        items = self.items()
        if not items or self.sel >= len(items):
            return
        a = items[self.sel]
        files = a.get('files') or {}
        if key == 'c':
            self.tui.open_link(files.get('cv') or '')
        elif key == 'l':
            self.tui.open_link(files.get('letter') or '')
        elif key == 'f':
            self.tui.fill_form(a.get('posting_id'))
        elif key == 'i':
            try:
                self.toast = self.backend.job_action(a.get('posting_id'), 'applied')
            except Exception as exc:  # noqa: BLE001
                self.toast = f'could not do that: {exc}'
            self.reload()
        elif key == 'n':
            self.tui.ask_agent(f'Prepare interview notes for posting {a.get("posting_id")}.')

    def activate(self):
        items = self.items()
        if self.sel < len(items):
            self.tui.show_view('detail', items[self.sel].get('posting_id'))


# ------------------------------------------------------------------------------------------------ Inbox
class InboxScreen(ViewScreen):
    kind = 'inbox'

    def fetch(self):
        return self.backend.inbox()

    def count(self):
        return len((self.data or {}).get('open', []))

    def body(self, width):
        items = (self.data or {}).get('open', [])
        n = len(items)
        lines = heading('Inbox', f'{n} mail repl{"y" if n == 1 else "ies"} waiting for your yes or no. Jobwatch reads your mail (read-only) and nothing changes on your applications until you approve it here.' if n
                        else 'Nothing is waiting for you. Jobwatch reads your mail (read-only) and suggestions show up here.')
        lines = [lines[0]] + wrap(lines[1].plain, width, MUTED) + [Text('')]
        at = 0
        for i, p in enumerate(items):
            on = i == self.sel
            at = len(lines) if on else at
            old = APP_STATE.get(p.get('app_status') or '', ('·', p.get('app_status') or '?', MUTED))
            new = APP_STATE.get(p.get('proposed_status') or '', ('·', p.get('proposed_status') or '?', MUTED))
            conf = f' · {round(float(p["confidence"]) * 100)}% sure' if p.get('confidence') is not None else ''
            card = box([join(styled(plain(p.get('title') or 'Application'), 'bold underline'), styled(f' · {plain(p.get("company") or "")}', MUTED)),
                          Text(''),
                          join('This reply looks like:  ', styled(f'{new[0]} {new[1]}', f'bold {AMETHYST}')),
                          Text(''),
                          styled(plain(p.get('subject') or ''), 'bold'),
                          styled(f'From {plain(p.get("from_addr") or "")} · Received {plain(p.get("received_ago") or "")}{conf}', MUTED),
                          Text(''),
                          join(styled('Approve moves this job from ', MUTED), styled(f'{old[0]} {old[1]}', f'bold'), styled(' to ', MUTED), styled(f'{new[0]} {new[1]}', 'bold'), styled('.', MUTED)),
                          Text(''),
                          join(btn('Approve (a)', primary=on), ' ', btn('Reject (r)'))], width, pad=1)
            lines += [join(styled('▌', AMBER if on else theme.RULE), line[1:]) for line in card]
            lines.append(Text(''))
        return lines, at

    def hint_text(self):
        return 'Nothing is sent and no application changes until you press a.'

    def footer_keys(self):
        return [('a', 'approve'), ('r', 'reject'), ('enter', 'open job')]

    def key(self, key, event):
        items = (self.data or {}).get('open', [])
        if key in ('a', 'r', 'y', 'n') and self.sel < len(items):
            decision = 'approve' if key in ('a', 'y') else 'reject'
            try:
                self.toast = self.backend.inbox_decide(items[self.sel]['id'], decision)
            except Exception as exc:  # noqa: BLE001
                self.toast = f'could not do that: {exc}'
            self.reload()

    def activate(self):
        items = (self.data or {}).get('open', [])
        if self.sel < len(items) and items[self.sel].get('posting_id'):
            self.tui.show_view('detail', items[self.sel]['posting_id'])


# ------------------------------------------------------------------------------------------------ Table
SORTS = ['fit', 'new', 'salary', 'company']


class TableScreen(ViewScreen):
    kind = 'table'

    def __init__(self, app_ref) -> None:
        super().__init__(app_ref)
        self.sort = 0
        self.needle = ''
        self.filtering = False

    def fetch(self):
        return self.backend.table(sort=SORTS[self.sort], q=self.needle)

    def count(self):
        return len((self.data or {}).get('rows', []))

    def body(self, width):
        data = self.data or {}
        rows = data.get('rows', [])
        sort_name = {'fit': 'best fit', 'new': 'listed', 'salary': 'salary', 'company': 'company'}[SORTS[self.sort]]
        lines = heading('All jobs', f'Showing 1 to {len(rows)} of {data.get("total", len(rows))}' + (f' · {plain(data.get("ai_text"))}' if data.get('ai_text') else '')) + [Text('')]
        if self.filtering:
            lines.append(join(styled('/ ', AMETHYST), plain(self.needle) + '▏'))
        else:
            lines.append(join(styled('/ ', AMETHYST), styled(plain(self.needle) or 'Job title, company or skill', MUTED if not self.needle else TEXT),
                              '   ', btn(f'Sorted by {sort_name} ▾'), ' ', btn('Columns 9'), ' ', btn('Download CSV (x)')))
        lines.append(Text(''))
        counts = (data.get('counts') or {}).get('ai') or {}
        chips = Text()
        for key, label in (('show', 'Worth a look'), ('hide', 'Hidden by AI'), ('pending', 'Waiting for AI')):
            if isinstance(counts, dict):
                chips.append_text(btn(f'{label} {counts.get(key, 0)}', primary=key == 'show' and bool(counts)))
                chips.append(' ')
        if chips.plain.strip():
            lines += [chips, Text('')]
        cols = [('Score', 5), ('Title', 29), ('Company', 14), ('Archetype', 12), ('Location', 13), ('Salary', 11), ('Listed', 7), ('State · AI view', 16)]
        lines.append(join(' ', header_row(cols)))
        at = 0
        for n, r in enumerate(rows):
            ai = plain(r.get('ai_state') or '')
            ai = {'show': 'good', 'hide': 'hidden', 'review': 'review', 'pending': 'waiting'}.get(ai, ai)
            state = row_state(r)
            state.append(f' · {ai}' if ai else '', style=MUTED)
            line = row([(score_cell(r.get('score5')), 5), (plain(r.get('title')), 29), (plain(r.get('company')), 14),
                        (plain(r.get('archetype') or '-'), 12), (plain(r.get('where') or r.get('location') or ''), 13),
                        (plain(r.get('salary') or ''), 11), (plain(r.get('listed_ago') or '')[:8] + (' ago' if r.get('listed_ago') else ''), 7), (state, 16)])
            if n == self.sel:
                at = len(lines)
            lines.append(selected(line, width, n == self.sel))
        if not rows:
            lines.append(styled('No jobs match.', MUTED))
        return lines, at

    def footer_keys(self):
        return [('↑ ↓', 'row'), ('enter', 'open job'), ('s', 'sort'), ('tab', 'next list'), ('x', 'csv')]

    def handle(self, event):
        if self.filtering:
            event.stop()
            if event.key == 'enter':
                self.filtering = False
                self.reload()
            elif event.key == 'escape':
                self.filtering, self.needle = False, ''
                self.reload()
            elif event.key == 'backspace':
                self.needle = self.needle[:-1]
            elif event.is_printable and event.character:
                self.needle += event.character
            self.redraw()
            return
        super().handle(event)

    def key(self, key, event):
        if key == 's':
            self.sort = (self.sort + 1) % len(SORTS)
            self.reload()
        elif key in ('slash', '/'):
            self.filtering = True
            self.redraw()
        elif key == 'x':
            try:
                self.toast = self.backend.export_csv()
            except Exception as exc:  # noqa: BLE001
                self.toast = f'could not export: {exc}'
            self.redraw()
        elif key == 'tab':
            self.toast = 'Other lists (saved, applied, hidden) are in the web board for now.'
            self.redraw()

    def activate(self):
        rows = (self.data or {}).get('rows', [])
        if self.sel < len(rows):
            self.tui.show_view('detail', pid_of(rows[self.sel]))


# ------------------------------------------------------------------------------------------------ Sources
class SourcesScreen(ViewScreen):
    kind = 'sources'

    def __init__(self, app_ref) -> None:
        super().__init__(app_ref)
        self.sector = ''
        self.sector_i = -1
        self.checking = ''
        self.show_all = False

    def fetch(self):
        return self.backend.sources(sector=self.sector, enabled=self.checking)

    def employers(self) -> list[dict]:
        rows = (self.data or {}).get('employers', [])
        return rows if self.show_all else rows[:8]

    def count(self):
        return len(self.employers())

    def body(self, width):
        data = self.data or {}
        health = data.get('health', [])
        lines = heading('Job sources', 'Where jobs come from, and whether each source is working.') + [Text('')]
        if not health:
            lines.append(styled('◌ No source has run yet. Health shows up after the first run.', AMBER))
        for h in health:
            colour = {'ok': GREEN, 'warn': AMBER, 'bad': RED}.get(h.get('rag'), MUTED)
            word = {'ok': 'ok', 'warn': 'attention', 'bad': 'failing'}.get(h.get('rag'), '')
            glyph = {'ok': '✓', 'warn': '?', 'bad': '✕'}.get(h.get('rag'), '·')
            lines.append(join(styled(f'{glyph} {word:<10}', colour), plain(h.get('label') or h.get('collector')).ljust(22),
                              styled(f'last ok {plain(h.get("last_ok_ago") or "never")}', MUTED)))
        allrows = data.get('employers', [])
        lines += [Text(''), styled('Employers watched', 'bold'),
                  styled("Jobwatch checks these employers' own careers systems directly, not only the job boards. Live = seen in 7 days.", MUTED), Text(''),
                  join(styled('Sector ', MUTED), btn(f'{self.sector or "All sectors"} ▾'), '    ', styled('Checking ', MUTED),
                       btn({'': 'All', '1': 'On', '0': 'Off'}[self.checking] + ' ▾'), '    ', styled(f'{len(allrows)} employers', MUTED)), Text('')]
        cols = [('Employer', 31), ('Sector', 11), ('System', 17), ('Live', 7), ('Ver · AU · VIC', 17), ('Checked', 20)]
        lines.append(join(' ', header_row(cols)))
        at = 0
        for n, e in enumerate(self.employers()):
            ver = ' · '.join(str(e.get(k)) if e.get(k) is not None else '-' for k in ('vc_total', 'vc_au', 'vc_vic'))
            checked = styled(f'✓ checked {plain(e.get("verified_at"))}', GREEN) if e.get('verified_at') else styled('· not checked', MUTED)
            line = row([(plain(e.get('name')), 31), (plain(str(e.get('sector')).capitalize()), 11), (plain(e.get('provider')), 17),
                        (f'{e.get("live", 0)} live', 7), (ver, 17), (checked, 20)])
            if n == self.sel:
                at = len(lines)
            lines.append(selected(line, width, n == self.sel))
        lines += [Text(''), join(styled('enter', AMETHYST), ' show notes for the selected employer   ', styled('A', AMETHYST), f' show all {len(allrows)} employers')]
        sel = self.employers()[self.sel] if self.employers() and self.sel < len(self.employers()) else None
        if sel and sel.get('notes') and getattr(self, 'notes_open', False):
            lines += [Text('')] + wrap(plain(sel['notes']), width, MUTED)
        return lines, at

    def footer_keys(self):
        return [('↑ ↓', 'row'), ('s', 'sector'), ('c', 'checking'), ('A', 'show all')]

    def key(self, key, event):
        sectors = (self.data or {}).get('sectors', [])
        if key == 's':
            names = [''] + [s if isinstance(s, str) else str(s[0]) for s in sectors]
            self.sector_i = (self.sector_i + 1) % len(names)
            self.sector = names[self.sector_i]
            self.reload()
        elif key == 'c':
            self.checking = {'': '1', '1': '0', '0': ''}[self.checking]
            self.reload()
        elif key in ('A', 'shift+a'):
            self.show_all = not self.show_all
            self.redraw()

    def activate(self):
        self.notes_open = not getattr(self, 'notes_open', False)
        self.redraw()


# ------------------------------------------------------------------------------------------------ Insights
class InsightsScreen(ViewScreen):
    kind = 'insights'

    def fetch(self):
        return self.backend.insights()

    def count(self):
        return 0

    def body(self, width):
        d = self.data or {}
        totals = d.get('totals') or {}
        lines = heading('Insights', 'What Jobwatch has found, and what is working.') + [Text('')]
        stats = [(totals.get('postings', 0), 'Postings seen'), (totals.get('matches', 0), 'Matches, all time'),
                 (totals.get('matches_7d', 0), 'Matches, 7 days'), (totals.get('employers_live', 0), 'Employers hiring now')]
        cell = 24
        for part in range(4):
            line = Text()
            for value, label in stats:
                if part == 0:
                    line.append('┌' + '─' * (cell - 2) + '┐ ', style=theme.RULE)
                elif part == 1:
                    line.append_text(join(styled('│ ', theme.RULE), styled(str(value).ljust(cell - 4), 'bold'), styled(' │ ', theme.RULE)))
                elif part == 2:
                    line.append_text(join(styled('│ ', theme.RULE), styled(label.ljust(cell - 4), MUTED), styled(' │ ', theme.RULE)))
                else:
                    line.append('└' + '─' * (cell - 2) + '┘ ', style=theme.RULE)
            lines.append(line)
        lines.append(Text(''))
        half = max((width - 4) // 2, 30)
        left = [styled('New matches per day', 'bold'), styled('Dim bars are older than 7 days.', MUTED)]
        series = d.get('series') or []
        top = max([n for _, n in series] or [1]) or 1
        days = series[-min(30, (half - 6) // 2):]
        chart = day_chart([n for _, n in days], top)
        first = dayname(days[0][0]) if days else ''
        left += [Text('')] + chart + [join(styled(first, MUTED), ' ' * max(len(days) * 2 - 1 - len(first) - 5, 1), styled('Today', MUTED)) if days else Text(''),
                styled(f'{totals.get("matches_30d", 0)} new matches in 30 days.', MUTED), Text('')]
        prog = d.get('progress') or {}
        if prog:
            left += [styled('Is the AI getting through them?', 'bold'), styled(f'{prog.get("read", 0)} of {prog.get("total", 0)} matched ads read.', 'bold'),
                     join(bar((prog.get('read', 0) / prog['total']) if prog.get('total') else 0, half - 8), styled(f' {prog.get("read", 0)}/{prog.get("total", 0)}', MUTED))]
        right = [styled('By job type', 'bold')]
        right += [join(plain(a[3] if len(a) > 3 else a[0]).ljust(18), bar(min(a[2] / max(top_n(d.get('by_arm')), 1), 1), 12), f' {a[2]}') for a in (d.get('by_arm') or [])[:4]]
        right += [Text(''), styled('By source', 'bold')]
        right += [join(plain(a[2] if len(a) > 2 else a[0]).ljust(18), bar(min(a[1] / max(top_n(d.get('by_src'), 1), 1), 1), 12), f' {a[1]}') for a in (d.get('by_src') or [])[:4]]
        right += [Text(''), styled('Busiest employers (30 days, seen · matched)', 'bold'),
                  Text(' · '.join(plain(t[0]) for t in (d.get('top') or [])[:6]))]
        rem = d.get('remote') or {}
        if rem.get('matches'):
            m, n = rem['matches']
            right += [Text(''), styled('Remote jobs', 'bold'), join('Your matches  ', bar(m / n if n else 0, 12), styled(f' {round(100 * m / n, 1) if n else 0}% · {m} of {n}', MUTED))]
        cb = ((d.get('callbacks') or {}).get('_all')) or {}
        right += [Text(''), styled('Callback rate', 'bold')]
        if cb.get('n'):
            lo, hi = cb.get('hdi', (0, 0))
            right += [join(styled(f'{cb["mean"] * 100:.1f}%', 'bold'), styled(' ? small sample' if cb['n'] < 10 else '', AMBER)),
                      styled(f'{cb.get("successes", 0)} callback from {cb["n"]} applications. Likely {lo * 100:.0f}% to {hi * 100:.0f}%.', MUTED)]
        else:
            right += [styled('No resolved applications yet.', MUTED)]
        for i in range(max(len(left), len(right))):
            l = left[i] if i < len(left) else Text('')
            l = l.copy()
            l.pad_right(max(half - l.cell_len, 0))
            lines.append(join(l, '  ', right[i] if i < len(right) else Text('')))
        return lines, 0

    def footer_keys(self):
        return [('tab', 'next panel'), ('↑ ↓', 'scroll')]


def dayname(value) -> str:
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime('%-d %b')
    except ValueError:
        return ''


def day_chart(counts: list[int], top: int, height: int = 3) -> list[Text]:
    """Columns of stacked eighth blocks, `height` text rows tall; recent days are bright, older ones dim."""
    blocks = '▁▂▃▄▅▆▇█'
    rows = [Text() for _ in range(height)]
    for i, n in enumerate(counts):
        level = round(n / top * height * 8) if n else 0
        colour = GREEN if i >= len(counts) - 7 else '#2f6f5b'
        for r in range(height):
            below = (height - 1 - r) * 8
            if level - below >= 8:
                cell = '█'
            elif level - below > 0:
                cell = blocks[level - below - 1]
            else:
                cell = '─' if r == height - 1 and not n else ' '
            rows[r].append(cell + ' ', style=colour)
    return rows


def top_n(rows, idx: int = 2) -> int:
    return max([r[idx] if len(r) > idx else r[1] for r in (rows or [])] or [1])


# ------------------------------------------------------------------------------------------------ Models
class ModelsScreen(ViewScreen):
    kind = 'models'

    def __init__(self, app_ref) -> None:
        super().__init__(app_ref)
        self.edits: dict[str, str] = {}
        self.test_result: dict[str, str] = {}
        self.editing = False

    def fetch(self):
        return self.backend.models()

    def rows(self) -> list[dict]:
        return (self.data or {}).get('rows', [])

    def count(self):
        return len(self.rows())

    def compose(self) -> ComposeResult:
        yield from super().compose()
        yield Input(placeholder='type the model id', id='modelinput')

    DEFAULT_CSS = ViewScreen.DEFAULT_CSS + f"""
    #modelinput {{ display: none; height: 1; border: none; background: {PANEL}; dock: bottom; margin-bottom: 1; }}
    #modelinput.-on {{ display: block; }}
    """

    def body(self, width):
        d = self.data or {}
        lines = heading('Models', 'Pick which AI model does each job. Your pick is used for you only.')
        if not d.get('gateway_ok', True):
            lines.append(styled('▲ Could not load the model list from the gateway. Type the model id by hand.', AMBER))
        lines += [Text(''), styled('Which model for which job', 'bold')]
        cols = [('Job', 28), ('Model', 28), ('Source', 28), ('Test', 12)]
        lines.append(join(' ', header_row(cols)))
        lines[-1].pad_right(max(width - lines[-1].cell_len, 0))
        lines[-1].stylize_before(f'on {PANEL}')
        at = 0
        for n, r in enumerate(self.rows()):
            value = self.edits.get(r['role'], r.get('value'))
            if r['role'] in self.edits:
                source = styled('Your pick (unsaved)', AMETHYST)
            elif r.get('custom'):
                source = styled('Your pick', AMETHYST)
            else:
                source = styled('Default (server setting)', MUTED)
            result = self.test_result.get(r['role'], 'not tested')
            test = styled('Test (t)', 'bold') if n == self.sel and result == 'not tested' else styled(result, GREEN if result == 'ok' else RED if result != 'not tested' else MUTED)
            line = row([(plain(r.get('label')), 28), (plain(value), 28), (source, 28), (test, 12)])
            if n == self.sel:
                at = len(lines)
            lines.append(selected(line, width, n == self.sel))
        lines += [Text(''), join(btn('Save models (s)', primary=bool(self.edits)), styled('  Test uses the saved model, so save first.', MUTED)), Text('')]
        gw = d.get('gateway') or {}
        lines += [styled('Your keys', 'bold'), styled("Using the server's gateway. Your own gateway key is set in the web app; it is never shown here.", MUTED), Text(''),
                  join(styled('Gateway base URL  ', MUTED), plain(gw.get('base_url') or gw.get('url') or '(server default)')),
                  join(styled('API key           ', MUTED), styled('set' if gw.get('has_key') or gw.get('key') else 'not set (server key in use)', MUTED))]
        return lines, at

    def footer_keys(self):
        return [('↑ ↓', 'job'), ('enter', 'type model id'), ('t', 'test'), ('s', 'save')]

    def handle(self, event):
        if self.editing:
            return                         # the Input has the keys
        super().handle(event)

    def key(self, key, event):
        rows = self.rows()
        if key == 's':
            if self.edits:
                self.toast = self.backend.save_models(dict(self.edits))
                self.edits = {}
                self.reload()
            self.redraw()
        elif key == 't' and self.sel < len(rows):
            role = rows[self.sel]['role']
            self.toast = f'testing {rows[self.sel].get("label")}…'
            self.redraw()
            self.run_test(role)

    @work(thread=True)
    def run_test(self, role: str) -> None:
        try:
            result = self.backend.test_model(role)
        except Exception as exc:  # noqa: BLE001
            result = str(exc)[:40]
        self.app.call_from_thread(self._tested, role, result)

    def _tested(self, role: str, result: str) -> None:
        self.test_result[role] = result
        self.toast = ''
        self.redraw()

    def activate(self):
        if self.sel < len(self.rows()):
            box_ = self.query_one('#modelinput', Input)
            box_.value = self.edits.get(self.rows()[self.sel]['role'], self.rows()[self.sel].get('value') or '')
            box_.add_class('-on')
            self.editing = True
            box_.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self.sel < len(self.rows()) and event.value.strip():
            self.edits[self.rows()[self.sel]['role']] = event.value.strip()
        box_ = self.query_one('#modelinput', Input)
        box_.remove_class('-on')
        self.editing = False
        self.set_focus(None)
        self.redraw()
