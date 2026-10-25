"""The start screen of the terminal app (mockup Home): pixel logo, the 1-8 menu, what needs you, services, one prompt."""
from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Input, Static

from . import tui_theme as theme
from .tui_screens import NAV, needs_you
from .tui_theme import AMBER, AMETHYST, BG, GREEN, INPUT, MUTED, PANEL, RULE, TEXT, fit, join, plain, styled

BADGE = '#27272a'
SELECTED = '#1e1830'          # amethyst-tinted dark row behind the chosen menu item
JOB, WATCH = '#a855f7', '#e9d5ff'
DESCRIPTIONS = {'today': 'what needs you now', 'jobs': 'best matches, detail, drafts', 'applications': 'CV, letter, fill the form',
                'inbox': 'mail replies to confirm', 'table': 'every job, sort and filter', 'sources': 'employers watched',
                'insights': 'what is working', 'models': 'which AI does which job'}

# 5x7 pixel capitals and an x-height 5-row lowercase, drawn two pixel rows per text row with half blocks
_GLYPHS = {
    'J': ['....##', '....##', '....##', '....##', '....##', '....##', '##..##', '##..##', '.####.'],
    'O': ['.####.', '##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '.####.'],
    'b': ['##....', '##....', '##....', '##....', '#####.', '##..##', '##..##', '##..##', '#####.'],
    'W': ['##....##', '##....##', '##....##', '##....##', '##.##.##', '##.##.##', '##.##.##', '########', '.##..##.'],
    'a': ['......', '......', '......', '.####.', '....##', '.#####', '##..##', '##..##', '.#####'],
    't': ['.##..', '.##..', '#####', '.##..', '.##..', '.##..', '.##..', '.##.#', '..###'],
    'C': ['......', '......', '......', '.####.', '##..##', '##....', '##....', '##..##', '.####.'],
    'h': ['##....', '##....', '##....', '##....', '#####.', '##..##', '##..##', '##..##', '##..##'],
}
LOGO_WIDTH = sum(len(g[0]) for g in _GLYPHS.values()) + len(_GLYPHS) - 1


def logo_lines() -> list[Text]:
    """JOb in purple, Watch in pale lilac; five text rows, each two pixel rows high."""
    rows = [Text() for _ in range(5)]
    for n, (letter, glyph) in enumerate(_GLYPHS.items()):
        colour = JOB if n < 3 else WATCH
        for r in range(5):
            top = glyph[2 * r] if 2 * r < len(glyph) else ''
            bottom = glyph[2 * r + 1] if 2 * r + 1 < len(glyph) else ''
            for c in range(len(glyph[0])):
                a, b = c < len(top) and top[c] == '#', c < len(bottom) and bottom[c] == '#'
                rows[r].append('█' if a and b else '▀' if a else '▄' if b else ' ', style=colour)
        if n < len(_GLYPHS) - 1:
            for row in rows:
                row.append(' ')
    return rows


def version() -> str:
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version('jobwatch')
    except Exception:  # noqa: BLE001 - an uninstalled checkout has no version
        return ''


def menu_lines(width: int, selected: int, counts: dict, compact: bool) -> list[Text]:
    """MENU 1-8: number badge, label (+count), description; the chosen item is a tinted two-row band."""
    out = [styled('MENU', f'bold {MUTED}'), Text('')] if not compact else [styled('MENU', f'bold {MUTED}')]
    for n, (key, label) in enumerate(NAV):
        count = counts.get(key)
        name = Text()
        name.append(label, style='bold')
        if count:
            name.append(f' {count}', style=f'bold {AMETHYST}')
        name.pad_right(max(17 - name.cell_len, 1))
        line = join(styled('▌' if n == selected else ' ', AMETHYST), styled(f' {n + 1} ', f'bold {AMETHYST} on {BADGE}'), '  ', name,
                    styled(DESCRIPTIONS[key], MUTED))
        extra = [] if compact else [Text('')]
        if n == selected:
            line.pad_right(max(width - line.cell_len, 0))
            line.stylize(f'on {SELECTED}', 1)
            if not compact:
                extra = [join(styled('▌', f'{AMETHYST} on {SELECTED}'), styled(' ' * (width - 1), f'on {SELECTED}'))]
        out.append(line)
        out += extra
    return out


def side_lines(rows: list[dict], inbox: int, services: list[tuple[str, str]], width: int, limit: int = 4) -> list[Text]:
    out = [styled('NEEDS YOU', f'bold {MUTED}')]
    items = needs_you(rows, inbox)[:limit]
    if not items:
        out.append(styled('Nothing is waiting on you.', MUTED))
    for item in items:
        colour = AMETHYST if item['glyph'] in '◆●' else AMBER if item['glyph'] == '?' else theme.RED if item['glyph'] == '✕' else MUTED
        head, _, rest = item['head'].partition(': ')
        sub = item['note'] if item.get('view') else (f'{rest} · {item["who"]}' if rest else item['who'])
        out += [join(styled(item['glyph'] + ' ', colour), styled(head, TEXT)), styled('  ' + fit(sub, width - 2), MUTED)]
        out.append(Text(''))
    out += [styled('SERVICES', f'bold {MUTED}')]
    if not services:
        out.append(styled('No service status yet.', MUTED))
    pad = max((len(name) for name, _ in services), default=8) + 2
    for name, status in services:
        colour = GREEN if status.startswith('Healthy') else AMBER if status.startswith('Attention') else theme.RED
        out.append(join(styled('● ', colour), styled(f'{plain(name):<{pad}}', TEXT), styled(plain(status), MUTED)))
    return out


class HomePrompt(Input):
    """Digits open a view while the line is empty; everything else is typed as a question."""

    def on_key(self, event) -> None:
        self.screen.home_key(event)


class HomeScreen(Screen):
    DEFAULT_CSS = f"""
    HomeScreen {{ layout: vertical; background: {BG}; padding: 1 3 0 3; }}
    #hhead {{ height: auto; }}
    #hbody {{ height: 1fr; margin-top: 1; }}
    #hmenu {{ width: 1fr; height: 1fr; }}
    #hside {{ width: 50; height: 1fr; border-left: solid {RULE}; padding: 0 0 0 2; }}
    #hprompt {{ height: 2; background: {INPUT}; border-top: solid {AMETHYST}; padding: 0 2; }}
    #hprompt Static {{ height: 1; background: {INPUT}; }}
    #hchev {{ width: 2; color: {MUTED}; }}
    #hinput {{ width: 1fr; background: {INPUT}; border: none; height: 1; padding: 0; }}
    #hinput:focus {{ border: none; background-tint: transparent; }}
    #hagent {{ width: auto; color: {MUTED}; }}
    #hfoot {{ height: 1; margin-top: 1; background: {BG}; }}
    """

    def __init__(self, app_ref) -> None:
        super().__init__()
        self.tui = app_ref
        self.backend = app_ref.backend
        self.sel = 0
        self.rows: list[dict] = []
        self.counts: dict = {}
        self.nav_counts: dict = {}
        self.services: list[tuple[str, str]] = []
        self.model = ''
        self.plain_text = ''

    def compose(self) -> ComposeResult:
        yield Static('', id='hhead')
        with Horizontal(id='hbody'):
            yield Static('', id='hmenu')
            yield Static('', id='hside')
        with Horizontal(id='hprompt'):
            yield Static('›', id='hchev')
            yield HomePrompt(placeholder='Ask Jobwatch, or press 1-8 to open a view', id='hinput')
            yield Static('', id='hagent')
        yield Static('', id='hfoot')

    def on_mount(self) -> None:
        self.query_one('#hinput', Input).focus()
        self.redraw()
        self.reload()

    def on_resize(self, event) -> None:
        self.redraw()

    @work(thread=True, exclusive=True)
    def reload(self) -> None:
        def safe(call, default):
            try:
                return call()
            except Exception:  # noqa: BLE001 - a missing database must not break the start screen
                return default
        rows = safe(self.backend.overview, [])
        data = {'rows': rows, 'counts': safe(lambda: self.backend.counts(rows), {}), 'nav': safe(self.backend.nav_counts, {}),
                'services': safe(self.backend.services, []), 'model': safe(self.backend.chat_model, '')}
        self.app.call_from_thread(self._loaded, data)

    def _loaded(self, data: dict) -> None:
        self.rows, self.counts, self.nav_counts = data['rows'], data['counts'], data['nav']
        self.services, self.model = data['services'], data['model']
        self.redraw()

    # ---- drawing
    def redraw(self) -> None:
        width = self.size.width
        if width == 0:
            return
        inner = width - 6
        narrow, short = width < 100, self.size.height < 30
        head = Text('\n').join(logo_lines())
        tag = [styled('your job search agent', MUTED),
               styled(' · '.join(p for p in (version(), datetime.now().strftime('%A %-d %B')) if p), MUTED)]
        if narrow:
            need = self.counts.get('needs_you', 0)
            tag.append(join(styled('● ', AMETHYST), styled(f'{need} need you', MUTED)) if need else Text(''))
            head = Text('\n').join(logo_lines() + [Text('')] + tag[:3 if need else 2])
        else:
            lines = [Text(''), Text(''), Text('')] + tag
            logo = logo_lines()
            merged = []
            for n, line in enumerate(logo):
                merged.append(join(line, ' ' * 3, lines[n]) if n < len(lines) else line)
            head = Text('\n').join(merged)
        self.query_one('#hhead', Static).update(head)
        side = self.query_one('#hside', Static)
        side.display = not narrow
        menu_w = max(self.query_one('#hmenu', Static).size.width, 40)
        counts = {'applications': self.nav_counts.get('applications'), 'inbox': self.nav_counts.get('inbox')}
        menu = Text('\n').join(menu_lines(menu_w, self.sel, counts, short))
        self.plain_text = menu.plain
        self.query_one('#hmenu', Static).update(menu)
        if not narrow:
            side_text = Text('\n').join(side_lines(self.rows, self.nav_counts.get('inbox') or 0, self.services, 46, 3))
            self.plain_text += '\n' + side_text.plain
            side.update(side_text)
        agent = Text()
        agent.append('Agent', style=MUTED).append(' · ', style=MUTED).append('Jobwatch', style='bold')
        if self.model:
            agent.append(f' {plain(self.model)}', style=MUTED)
        self.query_one('#hagent', Static).update(agent)
        left = Text()
        for n, (key, word) in enumerate([('↑ ↓', 'choose'), ('enter', 'open')]):
            left.append(key, style=f'bold {MUTED}').append(f' {word}', style=MUTED)
            left.append('   ')
        right = Text()
        right.append('ctrl+p', style=MUTED).append(' commands', style=MUTED).append('   ')
        right.append('ctrl+c', style=MUTED).append(' quit', style=MUTED)
        self.query_one('#hfoot', Static).update(theme.two_col(left, right, inner))

    # ---- keys
    def home_key(self, event) -> None:
        prompt = self.query_one('#hinput', Input)
        key = event.key
        if key in ('up', 'down') or (key in ('j', 'k') and not prompt.value):
            event.prevent_default()
            event.stop()
            step = -1 if key in ('up', 'k') else 1
            self.sel = min(max(self.sel + step, 0), len(NAV) - 1)
            self.redraw()
        elif not prompt.value and len(key) == 1 and key in '12345678':
            event.prevent_default()
            event.stop()
            self.tui.show_view(NAV[int(key) - 1][0])
        elif key == 'enter' and not prompt.value:
            event.prevent_default()
            event.stop()
            self.tui.show_view(NAV[self.sel][0])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ''
        event.stop()
        if text:
            self.tui.submit_text(text)
