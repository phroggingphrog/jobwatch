"""Pure render functions for the Main board: feed rows, sidebar, narrow header, approval strip, user block."""
from __future__ import annotations

import textwrap

from rich.text import Text

from .tui_theme import (join, styled, AMBER, AMETHYST, GREEN, IDLE, MUTED, NEEDS_YOU, PANEL, STATES, badge, fit, plain,
                        score_text, two_col)

COMMANDS = {'/today': 'Today', '/jobs': 'all jobs', '/applications': 'Applications', '/inbox': 'Inbox', '/table': 'Table',
            '/sources': 'Sources', '/insights': 'Insights', '/models': 'Models', '/job N': 'set the job in focus',
            '/run': 'start a watcher run', '/profile': 'check the career profile', '/new': 'new thread',
            '/resume': 'resume an unfinished turn', '/quit': 'leave'}


def counts_lines(counts: dict) -> list[Text]:
    first = Text()
    first.append('● ', style=AMETHYST).append(f'{counts.get("needs_you", 0)} need you  ')
    first.append('✓ ', style=GREEN).append(f'{counts.get("submitted", 0)} sent')
    second = Text()
    second.append('? ', style=AMBER).append(f'{counts.get("outcome_unknown", 0)} outcome unknown')
    lines = [first, second]
    if counts.get('needs_info'):
        lines.append(Text(f'◆ {counts["needs_info"]} need info', style=AMETHYST))
    return lines


def feed_rows(rows: list[dict], selected: int | None, width: int = 27) -> list[Text]:
    """Two lines per job: employer left and score right, then the status badge (glyph and word)."""
    out: list[Text] = []
    for n, row in enumerate(rows):
        on = n == selected
        name = two_col(fit(row.get('employer') or f'job {row.get("posting_id")}', width - 5), '' if row.get('score') is None else score_text(row.get('score')), width)
        name.stylize(MUTED, width - 3, width)
        if on:
            name = join(styled('▎', AMETHYST), name)
            name.stylize(f'on {PANEL}')
        line2 = join(' ' if on else '', badge(row.get('state', '')))
        if on:
            line2.stylize(f'on {PANEL}')
        out += [name, line2]
    return out


def sidebar(title: str, counts: dict, rows: list[dict], selected: int | None, services: list[tuple[str, str]],
            width: int = 27) -> list[Text]:
    lines = [Text(plain(title), style='bold'), Text('')]
    lines += counts_lines(counts)
    lines += [Text(''), Text('Queue', style='bold')]
    lines += feed_rows(rows, selected, width) if rows else [Text('Nothing in the queue yet.', style=MUTED)]
    if services:
        lines += [Text(''), Text('Services', style='bold')]
        for name, status in services:
            colour = GREEN if status == 'Healthy' else AMBER
            left = join(styled('● ', colour), fit(name, width - 12))
            lines.append(two_col(left, Text(status, style=MUTED), width))
    return lines


def narrow_header(counts: dict, width: int) -> Text:
    right = Text()
    right.append(f'● {counts.get("needs_you", 0)}', style=AMETHYST).append(' ')
    right.append(f'? {counts.get("outcome_unknown", 0)}', style=AMBER).append(' ')
    right.append(f'✓ {counts.get("submitted", 0)}', style=GREEN)
    out = two_col(styled(' Jobwatch', 'bold'), join(right, ' '), width)
    out.stylize(f'on {PANEL}')
    return out


def narrow_feed(rows: list[dict], width: int, selected: int | None = None, limit: int = 3) -> list[Text]:
    """The jobs that need the owner first; one line each: badge, employer, score."""
    needs = [r for r in rows if r.get('state') in NEEDS_YOU or r.get('state') == 'outcome unknown']
    shown = (needs + [r for r in rows if r not in needs])[:limit]
    lines = []
    for n, row in enumerate(shown):
        left = join(badge(row.get('state', '')), '  ' + fit(row.get('employer') or '', max(width - 36, 12)))
        line = two_col(join(' ', left), score_text(row.get('score')) + ' ', width)
        if n == selected:
            line.stylize(f'on {PANEL}')
        lines.append(line)
    more = len(rows) - len(shown)
    lines.append(Text(f' + {more} more · tab to browse the queue' if more > 0 else ' tab to browse the queue', style=MUTED))
    return lines


def approval_strip(pending: list[dict]) -> Text:
    """Line 1 title, line 2 summary, line 3 keys. A Submit has no `a`: it opens the review."""
    first = pending[0]
    out = Text()
    if first.get('type') == 'approval':
        op = plain(first.get('operation') or 'operation')
        title = Text('◆ Approval waiting', style=f'bold {AMETHYST}')
        title.append(f'  {op}', style=MUTED)
        if first.get('posting_id') is not None:
            title.append(f' · posting {first["posting_id"]}', style=MUTED)
        if len(pending) > 1:
            title.append(f'  (+{len(pending) - 1} more)', style=MUTED)
        out.append_text(title)
        out.append('\n' + plain(first.get('summary') or f'Approve {op}'))
        out.append('\n')
        keys = ([('enter', 'review form'), ('r', 'reject'), ('e', 'edit')] if op == 'submit_application'
                else [('a', 'approve'), ('r', 'reject'), ('e', 'edit')])
        for n, (key, word) in enumerate(keys):
            out.append(key, style=AMETHYST).append(f' {word}' + ('   ' if n < len(keys) - 1 else ''))
    else:
        out.append('◆ Jobwatch asks', style=f'bold {AMETHYST}')
        out.append('\n' + plain(first.get('question') or first.get('prompt') or 'Jobwatch asks'))
        out.append('\ntype your answer and press Enter', style=MUTED)
    return out


def user_block(message: str, width: int) -> list[Text]:
    """Panel fill with an amethyst bar down the left edge, one blank row above and below."""
    body = textwrap.wrap(plain(message), max(width - 6, 10)) or ['']
    rows = []
    for text in ['', *body, '']:
        line = join(styled('▌', f'{AMETHYST} on {PANEL}'), styled('  ' + text.ljust(width - 3), f'on {PANEL}'))
        rows.append(line)
    return rows


def gutter(label: str, text: str, colour: str | None, width: int) -> list[Text]:
    """Narrow layout: a 7-cell label column, then the text."""
    body = textwrap.wrap(plain(text), max(width - 8, 10)) or ['']
    lines = []
    for n, part in enumerate(body):
        head = styled(f'{label:<7}', colour or MUTED) if n == 0 else Text(' ' * 7)
        lines.append(join(head, part))
    return lines


def tool_line(name: str, state: str, indent: int = 2, took: float | None = None) -> Text:
    word = state + (f' {took:.1f}s' if took is not None and state == 'done' else '')
    return Text(' ' * indent + f'▸ {plain(name):<22}{word}', style=MUTED)


def hint(pending: list[dict], busy: bool, text: str = '') -> Text:
    if text.startswith('/'):
        match = [f'{k} {v}' for k, v in COMMANDS.items() if k.startswith(text.split()[0])] if text.strip() else []
        if match:
            return Text(' · '.join(match[:4]), style=MUTED)
    if busy:
        return Text('Working. Typing queues a reply.', style=MUTED)
    if pending:
        return Text('Typing replies to the agent and never approves.', style=MUTED)
    return Text('Ask Jobwatch. / for commands, @ to attach a file.', style=IDLE)


def footer(width: int, left: str = '~', keys: list[tuple[str, str]] | None = None) -> Text:
    keys = keys or [('tab', 'sidebar'), ('ctrl+p', 'commands')]
    right = Text()
    for n, (key, word) in enumerate(keys):
        right.append(key, style='bold').append(f' {word}', style=MUTED)
        if n < len(keys) - 1:
            right.append('   ')
    return two_col(Text(left, style=MUTED), right, width)


def empty_feed() -> list[str]:
    """First run: what is going on and what to type (markup lines for the transcript)."""
    return ['[bold]Nothing in the queue yet.[/bold]', '[dim]The watcher has not found a job to score.[/dim]', '',
            f'[{AMETHYST}]/run[/]      start a watcher run', f'[{AMETHYST}]/profile[/]  check the career profile it scores against', '',
            '[dim]Or ask: "What is the watcher doing?"[/dim]']
