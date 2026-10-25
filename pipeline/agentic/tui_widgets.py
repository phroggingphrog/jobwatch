"""Small text-grid building blocks shared by the board screens (all return rich Text lines)."""
from __future__ import annotations

from rich.text import Text

from .tui_theme import AMBER, AMETHYST, BG, GREEN, MUTED, PANEL, RULE, fit, join, plain, styled

BUTTON = '#27272a'


def btn(label: str, primary: bool = False, muted: bool = False) -> Text:
    if primary:
        return styled(f' {label} ', f'bold {BG} on {AMETHYST}')
    return styled(f' {label} ', f'{MUTED if muted else "bold"} on {BUTTON}')


def keyhint(pairs: list[tuple[str, str]], gap: int = 3) -> Text:
    out = Text()
    for n, (key, word) in enumerate(pairs):
        out.append(key, style='bold').append(f' {word}', style=MUTED)
        if n < len(pairs) - 1:
            out.append(' ' * gap)
    return out


def heading(text: str, note: str = '') -> list[Text]:
    lines = [styled(text, 'bold')]
    if note:
        lines.append(styled(note, MUTED))
    return lines


def caps(text: str) -> Text:
    return styled(text.upper(), f'bold {MUTED}')


def bar(fraction: float, width: int, colour: str = GREEN) -> Text:
    fraction = min(max(fraction, 0.0), 1.0)
    full = round(fraction * width)
    out = Text()
    out.append('█' * full, style=colour)
    out.append('█' * (width - full), style='#52525b')
    return out


def box(lines: list[Text], width: int, accent: str | None = None, pad: int = 2, edge: str = RULE, fill: str | None = None) -> list[Text]:
    """A thin square box; with `accent` a thick bar of that colour runs down the left edge instead."""
    inner = width - 2 - pad * 2
    out = []
    if accent:
        out.append(Text(''))
    else:
        out.append(styled('┌' + '─' * (width - 2) + '┐', edge))
    for line in lines:
        cell = Text()
        cell.append_text(line)
        cell.truncate(inner, overflow='ellipsis')
        cell.pad_right(inner - cell.cell_len)
        if accent:
            out.append(join(styled('▌', accent), ' ' * pad, cell, ' ' * (pad)))
        else:
            out.append(join(styled('│', edge), ' ' * pad, cell, ' ' * pad, styled('│', edge)))
    if not accent:
        out.append(styled('└' + '─' * (width - 2) + '┘', edge))
    if fill:
        for line in out:
            line.stylize_before(f'on {fill}')
    return out[1:] if accent else out


def selected(line: Text, width: int, on: bool) -> Text:
    """Selected row: panel fill and a bar at the left edge."""
    if not on:
        return join(' ', line)
    out = join(styled('▌', AMETHYST), line)
    out.pad_right(max(width - out.cell_len, 0))
    out.stylize_before(f'on {PANEL}')
    return out


def row(cells: list[tuple[str | Text, int]], style: str | None = None) -> Text:
    """Fixed-width columns, one gap cell between."""
    out = Text()
    for value, width in cells:
        cell = Text(fit(value, width)) if isinstance(value, str) else value.copy()
        if isinstance(value, Text):
            cell.truncate(width, overflow='ellipsis')
        cell.pad_right(width - cell.cell_len)
        out.append_text(cell)
        out.append(' ')
    if style:
        out.stylize(style)
    return out


def header_row(cells: list[tuple[str, int]]) -> Text:
    return row([(styled(name.upper(), MUTED), width) for name, width in cells])


def lines_of(*items) -> list[Text]:
    out: list[Text] = []
    for item in items:
        out.extend(item if isinstance(item, list) else [item])
    return out


def amber(text: str) -> Text:
    return styled(text, AMBER)


def wrap(text: str, width: int, style: str | None = None) -> list[Text]:
    import textwrap
    return [styled(part, style) if style else Text(part) for part in (textwrap.wrap(plain(text), max(width, 10)) or [''])]
