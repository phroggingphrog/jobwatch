"""The `@` file picker: fuzzy search from the home folder, then attach chips above the prompt.

Attaching never sends anything. A file goes to the backend only with the next message, through the same
upload path the web upload ticket ends in (tui_data.WebBackend.upload -> intake.save_upload, 10 MB limit)."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

from rich.text import Text
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from . import tui_theme as theme
from .tui_data import MAX_UPLOAD_BYTES, check_attachment
from .tui_theme import AMETHYST, MUTED, PANEL, join, plain, styled
from .tui_widgets import keyhint

SKIP_DIRS = {'node_modules', '__pycache__', '.git', '.cache', '.venv', 'venv', 'site-packages', '.npm', '.cargo', '.local', '.config'}
MAX_SCAN = 4000


def size_text(size: int) -> str:
    return f'{size / 1048576:.1f} MB' if size >= 1048576 else f'{max(size // 1024, 1)} KB' if size else '0 KB'


def kind_for(name: str) -> str:
    low = name.lower()
    if 'letter' in low or 'cover' in low:
        return 'letter'
    if 'cv' in low or 'resume' in low or 'curriculum' in low:
        return 'cv'
    return 'evidence'


def fuzzy_score(query: str, text: str) -> int | None:
    """Subsequence match; higher is better (consecutive letters and a match at a word start score more)."""
    query, low = query.lower(), text.lower()
    pos, score, last = 0, 0, -2
    for ch in query:
        found = low.find(ch, pos)
        if found < 0:
            return None
        score += 3 if found == last + 1 else 1
        if found == 0 or low[found - 1] in '-_./ ':
            score += 2
        last, pos = found, found + 1
    return score - len(text) // 20


def scan(root: Path, limit: int = MAX_SCAN, depth: int = 4) -> list[Path]:
    """Files under root (hidden and cache folders skipped), bounded so a huge home stays quick."""
    out: list[Path] = []
    base = len(root.parts)
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in SKIP_DIRS and len(Path(here).parts) - base < depth)
        for name in sorted(files):
            if not name.startswith('.'):
                out.append(Path(here) / name)
        if len(out) >= limit:
            break
    return out


def listing(folder: Path) -> list[tuple[Path, bool]]:
    """(path, is_dir): folders first, hidden entries left out."""
    try:
        entries = [p for p in folder.iterdir() if not p.name.startswith('.')]
    except OSError:
        return []
    return sorted(((p, p.is_dir()) for p in entries), key=lambda e: (not e[1], e[0].name.lower()))


class FilePicker(ModalScreen):
    DEFAULT_CSS = f"""
    FilePicker {{ align: center middle; background: {theme.BG} 70%; }}
    #pickbox {{ width: 80; height: 24; background: {PANEL}; border: round {theme.RULE}; padding: 0 1; }}
    #pickbody {{ height: 1fr; }}
    """

    def __init__(self, app_ref, purpose: str = 'chat', home: Path | None = None) -> None:
        super().__init__()
        self.tui = app_ref
        self.home = home or Path.home()
        self.folder = self.home
        self.needle = ''
        self.sel = 0
        self.message = ''
        self.scanned: list[Path] | None = None
        self.purpose = purpose

    def compose(self):
        with Vertical(id='pickbox'):
            yield Static('', id='pickbody')

    def on_mount(self) -> None:
        self.redraw()

    # ---- data
    def entries(self) -> list[tuple[Path, bool]]:
        if not self.needle:
            return listing(self.folder)
        if self.scanned is None or self.tree_root != self.folder:
            self.scanned, self.tree_root = scan(self.folder), self.folder
        scored = [(fuzzy_score(self.needle, str(p.relative_to(self.folder))), p) for p in self.scanned]
        return [(p, False) for s, p in sorted(((s, p) for s, p in scored if s is not None), key=lambda e: -e[0])][:200]

    tree_root: Path | None = None

    def current(self) -> tuple[Path, bool] | None:
        rows = self.entries()
        return rows[self.sel] if rows and self.sel < len(rows) else None

    # ---- drawing
    def crumbs(self) -> str:
        try:
            rel = self.folder.relative_to(self.home)
        except ValueError:
            return str(self.folder)
        return ' ▸ '.join(['~', *rel.parts])

    def redraw(self) -> None:
        rows = self.entries()
        self.sel = min(self.sel, max(len(rows) - 1, 0))
        width = 76
        lines = [theme.two_col(styled('Attach File', 'bold'), styled('esc close', MUTED), width),
                 styled(self.crumbs(), MUTED),
                 theme.two_col(join(styled('› ', AMETHYST), plain(self.needle) + '▏'), styled(f'{min(self.sel + 1, len(rows))} of {len(rows)}', MUTED), width),
                 styled('─' * width, theme.RULE)]
        left_w = 42
        shown = rows[max(self.sel - 9, 0):][:12]
        first = max(self.sel - 9, 0)
        left = [join(styled('NAME'.ljust(left_w - 8), MUTED), styled('SIZE'.rjust(8), MUTED))]
        for n, (path, is_dir) in enumerate(shown):
            on = first + n == self.sel
            try:
                size = '-' if is_dir else size_text(path.stat().st_size)
            except OSError:
                size = '?'
            name = (str(path.relative_to(self.folder)) if self.needle else path.name) + ('/' if is_dir else '')
            name = ('▸ ' if is_dir else '● ' if on else '  ') + theme.fit(name, left_w - 12)
            line = join(name.ljust(left_w - 8), size.rjust(8))
            if on:
                line = join(styled('▌', AMETHYST), line)
                line.stylize(f'on {theme.INPUT}')
            else:
                line = join(' ', line)
            left.append(line)
        if not rows:
            left.append(styled('  No files match.', MUTED))
        right = self.preview(rows[self.sel] if rows else None)
        for i in range(max(len(left), len(right), 13)):
            l = left[i].copy() if i < len(left) else Text('')
            l.pad_right(max(left_w + 2 - l.cell_len, 0))
            lines.append(join(l, styled('│ ', theme.RULE), right[i] if i < len(right) else Text('')))
        lines.append(styled('─' * width, theme.RULE))
        if self.message:
            lines.append(styled(theme.fit(self.message, width), AMBER_))
        if True:
            lines.append(theme.two_col(keyhint([('enter', 'attach'), ('→', 'open folder'), ('←', 'up'), ('type', 'filter')]),
                                       styled('↑ ↓ move', MUTED), width))
        self.query_one('#pickbody', Static).update(Text('\n').join(lines))

    def preview(self, entry) -> list[Text]:
        if not entry:
            return []
        path, is_dir = entry
        if is_dir:
            return [styled(plain(path.name) + '/', 'bold'), styled('Folder. Press → to open it.', MUTED)]
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        kind = {'cv': 'CV', 'letter': 'cover letter', 'evidence': 'a supporting document'}[kind_for(path.name)]
        out = [styled(theme.fit(path.name, 28), 'bold'), styled(f'{path.suffix.lstrip(".").upper() or "File"} · {size_text(size)}', MUTED), Text('')]
        problem = check_attachment(path)
        if problem:
            out += [styled(part, AMBER_) for part in textwrap.wrap(f'Cannot attach: {problem}.', 28)]
        else:
            out += [Text('Goes to Jobwatch as'), join(styled(kind, AMETHYST), ''), Text(''),
                    styled('Attaching does not submit anything.', MUTED)]
        return out

    # ---- keys
    def on_key(self, event) -> None:
        key = event.key
        rows = self.entries()
        event.stop()
        self.message = ''
        if key == 'escape':
            self.dismiss(None)
            return
        if key == 'up':
            self.sel = max(self.sel - 1, 0)
        elif key == 'down':
            self.sel = min(self.sel + 1, max(len(rows) - 1, 0))
        elif key == 'right':
            cur = self.current()
            if cur and cur[1]:
                self.folder, self.needle, self.sel = cur[0], '', 0
        elif key == 'left':
            if self.needle:
                self.needle = ''
            elif self.folder != self.home and self.folder.parent != self.folder:
                self.folder, self.sel = self.folder.parent, 0
        elif key == 'enter':
            cur = self.current()
            if cur and cur[1]:
                self.folder, self.needle, self.sel = cur[0], '', 0
            elif cur:
                problem = check_attachment(cur[0])
                if problem:
                    self.message = f'Cannot attach {cur[0].name}: {problem}.'
                else:
                    self.dismiss(cur[0])
                    return
        elif key == 'backspace':
            self.needle, self.sel = self.needle[:-1], 0
        elif event.is_printable and event.character:
            self.needle, self.sel = self.needle + event.character, 0
        self.redraw()


AMBER_ = theme.AMBER


def open_picker(app, purpose: str = 'chat') -> None:
    def done(path: Path | None) -> None:
        app.pending_picker = False
        if path is not None:
            app.add_attachment(path)
    app.push_screen(FilePicker(app, purpose), done)


def chips_text(attachments: list[dict], width: int) -> Text:
    out = Text()
    for item in attachments:
        out.append_text(join(styled('▸ ', AMETHYST), plain(item['path'].name), styled(f'  {size_text(item["size"])}', MUTED), '   '))
    out.append(' x remove', style=MUTED)
    return out
