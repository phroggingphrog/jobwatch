"""Palette, status glyphs and small render helpers for the Jobwatch terminal app (zinc greys + amethyst)."""
from __future__ import annotations

import unicodedata

from rich.markup import escape as _escape
from rich.text import Text

BG, PANEL, SIDE, INPUT, RULE = '#09090b', '#18181b', '#141416', '#1c1c1f', '#3f3f46'
TEXT, MUTED, IDLE = '#fafafa', '#a1a1aa', '#71717a'
AMETHYST, GREEN, AMBER, RED = '#c084fc', '#34d399', '#fbbf24', '#f87171'

# state -> (glyph, colour); status is always a glyph plus a word
STATES = {
    'not started': ('○', IDLE), 'queued': ('◌', IDLE), 'drafting': ('◐', AMETHYST), 'draft ready': ('●', AMETHYST),
    'awaiting browser press': ('◆', AMETHYST), 'executing': ('▶', AMETHYST), 'submitted': ('✓', GREEN),
    'outcome unknown': ('?', AMBER), 'failed': ('✕', RED), 'expired': ('◇', IDLE), 'cancelled': ('⊘', IDLE),
}
NEEDS_YOU = ('draft ready', 'awaiting browser press', 'failed', 'expired')


def clean(text: str) -> str:
    """Strip hidden/bidi control characters before anything model, tool or posting related is shown."""
    return ''.join(ch for ch in text if ch in '\n\t' or unicodedata.category(ch) not in ('Cc', 'Cf'))


def esc(text: object) -> str:
    return _escape(clean(str(text)))


def plain(value: object) -> str:
    return clean(str(value if value is not None else ''))


def join(*parts: Text | str) -> Text:
    """Concatenate without letting the first piece's base style colour the rest."""
    out = Text()
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        else:
            out.append_text(part)
    return out


def styled(text: str, style: str) -> Text:
    out = Text()
    out.append(text, style=style)
    return out


def badge(state: str) -> Text:
    glyph, colour = STATES.get(state, ('·', MUTED))
    return styled(f'{glyph} {state}', colour)


def fit(text: object, width: int) -> str:
    text = plain(text)
    return text if len(text) <= width else text[:max(width - 1, 0)] + '…'


def score_text(score) -> str:
    return '-' if score is None else f'{float(score):.1f}'


def two_col(left: Text | str, right: Text | str, width: int) -> Text:
    left = Text(left) if isinstance(left, str) else left
    right = Text(right) if isinstance(right, str) else right
    pad = max(width - left.cell_len - right.cell_len, 1)
    out = Text()
    out.append_text(left)
    out.append(' ' * pad)
    out.append_text(right)
    return out


BASE_CSS = f"""
Screen {{ background: {BG}; color: {TEXT}; }}
.muted {{ color: {MUTED}; }}
#navrow {{ height: 1; background: {BG}; padding: 0 1; }}
#viewbody {{ height: 1fr; padding: 1 2 0 2; }}
#viewfoot {{ height: 1; background: {PANEL}; padding: 0 1; }}
"""
