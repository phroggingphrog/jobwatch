"""Claude-Code-style terminal UI for the Jobwatch career agent.

One turn at a time per person; `dispatch` already refuses a second turn with
``person_busy``. Each turn runs in a worker thread with its own person scope and
its own SQLite connection, and progress arrives through ``Execution(emit=...)``
(``model_started``, ``model_finished``, ``tool_started``, ``tool_finished``,
``execution_error``) which a timer drains into the transcript. There is no token
streaming: the answer is rendered once the turn returns.

The turn identity is written to ``career-chat/tui-session.json`` *before* the turn
starts, so a killed terminal can tell an unfinished turn from a fresh one — the
checkpoints carry the invocation id, and a resume must present the same one.

Approvals are never modal: pending decisions sit in a strip above the prompt. With the
prompt empty, ``a`` approves and ``r`` rejects; ``e`` rejects with a written reason (the
gate allows only approve, reject and respond, so there is no in-place edit). Typed answers
still work. Every answer is sent as ``decisions=[...]`` with ``human_decision=True``.
``/job N`` (or an approval naming a posting) sets the job whose task state is shown.
"""
from __future__ import annotations

import argparse
import json
import queue
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.markup import escape as _escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic.chat import dispatch, job_connection
from pipeline.agentic.execution import Execution
from pipeline.agentic.runtime import RuntimeErrorSafe

# Idea from deepagents-code (LangChain, MIT): strip hidden/bidi control characters from
# model, tool and posting text before it is shown. Reimplemented, no code copied.

def _clean(text: str) -> str:
    return ''.join(ch for ch in text if ch in '\n\t' or unicodedata.category(ch) not in ('Cc', 'Cf'))


def _e(text: object) -> str:
    return _escape(_clean(str(text)))


_SESSION = 'tui-session.json'
_DECLINE = 'The human declined to answer. Do not infer missing facts.'


def _session_path(person: str) -> Path:
    root = users.user_dir(person) / 'career-chat'
    root.mkdir(parents=True, exist_ok=True)
    return root / _SESSION


def _read_session(person: str) -> dict[str, Any]:
    try:
        return json.loads(_session_path(person).read_text())
    except (OSError, ValueError):
        return {}


def _write_session(person: str, value: dict[str, Any]) -> None:
    path = _session_path(person)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


# One palette for the whole screen (PhrogVPS dark: zinc greys, one amethyst accent). The accent
# marks "something is happening or waiting on you"; idle chrome stays grey. Status is always a
# glyph plus a word, never colour alone.
ACCENT = '#c084fc'
MUTED = '#a1a1aa'
IDLE = '#71717a'
BG = '#09090b'
PANEL = '#18181b'
INK = '#fafafa'

_WORD = 'jobwatch'
_GREYS = ['#52525b', '#63636b', '#74747c', '#898990', '#a1a1aa', '#c4c4ca', '#e4e4e7', '#fafafa']
_GLYPHS = {
    'j': ['..#', '..#', '..#', '#.#', '.#.'],
    'o': ['.#.', '#.#', '#.#', '#.#', '.#.'],
    'b': ['#..', '#..', '###', '#.#', '###'],
    'w': ['#.#', '#.#', '#.#', '###', '#.#'],
    'a': ['.#.', '#.#', '###', '#.#', '#.#'],
    't': ['.#.', '###', '.#.', '.#.', '.##'],
    'c': ['.##', '#..', '#..', '#..', '.##'],
    'h': ['#..', '#..', '###', '#.#', '#.#'],
}
WORDMARK_WIDTH = len(_WORD) * 8 - 2


def _wordmark(width: int) -> str:
    """Block-letter wordmark with a grey-to-white ramp; plain bold text on narrow terminals."""
    if width < WORDMARK_WIDTH + 8:
        return f'[bold {INK}]jobwatch[/bold {INK}]'
    lines = []
    for row in range(5):
        cells = []
        for i, ch in enumerate(_WORD):
            bits = _GLYPHS[ch][row]
            cells.append(f'[{_GREYS[i]}]' + ''.join('██' if b == '#' else '  ' for b in bits) + '[/]')
        lines.append('  '.join(cells))
    return '\n'.join(lines)


class PromptInput(Input):
    """Lets the app take a / r / e before they are typed, while a decision is pending."""

    def on_key(self, event) -> None:
        self.app.decision_key(event)


class JobwatchTUI(App):
    """A transcript, a prompt line and an honest status line."""

    CSS = f"""
    $phrog-bg: {BG};
    $phrog-panel: {PANEL};
    $phrog-ink: {INK};
    $phrog-muted: {MUTED};
    $phrog-idle: {IDLE};
    $phrog-accent: {ACCENT};
    """ + """
    Screen { background: $phrog-bg; color: $phrog-ink; }
    #body { height: 1fr; }
    #main { width: 1fr; }
    #sidebar { width: 34; padding: 1 2; background: $phrog-panel; color: $phrog-ink; }
    #sidebar.-hidden { display: none; }
    #welcome { display: none; height: auto; width: 100%; text-align: center; padding: 0 0 1 0; }
    #transcript { height: 1fr; padding: 0 1; background: $phrog-bg; scrollbar-size-vertical: 1; }
    #status { height: 1; padding: 0 1; color: $phrog-muted; }
    #taskstate { height: 1; padding: 0 1; color: $phrog-accent; }
    #pending { height: auto; padding: 0 1; border-left: thick $phrog-accent; background: $phrog-panel;
               display: none; }
    #pending.-on { display: block; }
    #prompt { height: 3; padding: 1 1; border: none; border-left: thick $phrog-idle;
              background: $phrog-panel; color: $phrog-ink; }
    #prompt:focus { border: none; border-left: thick $phrog-idle; background-tint: transparent; }
    #prompt.-working, #prompt.-working:focus { border-left: thick $phrog-accent; }
    Screen.-welcome #sidebar { display: none; }
    Screen.-welcome #main { align: center middle; }
    Screen.-welcome #welcome { display: block; }
    Screen.-welcome #transcript { display: none; }
    Screen.-welcome #taskstate, Screen.-welcome #status, Screen.-welcome #pending,
    Screen.-welcome #prompt { width: 80; max-width: 100%; }
    """

    BINDINGS = [
        Binding('ctrl+c', 'cancel_turn', 'cancel turn', priority=True),
        Binding('ctrl+n', 'new_thread', 'new thread'),
    ]

    def __init__(self, person: str, thread_id: str | None = None) -> None:
        super().__init__()
        self.person = person
        self.thread_id = thread_id or f'tui-{time.strftime("%Y%m%d-%H%M%S")}'
        self.checkpoint: str | None = None
        self.run_id: str | None = None
        self.deferred: list[str] = []
        self.pending: list[dict] = []
        self.busy = False
        self.cancel = threading.Event()
        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self._tool_started: dict[str, float] = {}
        self.posting_id: int | None = None
        self.task_label = ''
        self.turns = 0
        self.tools_this_turn = 0
        self.last_usage: dict = {}
        self.reject_with_reason = False

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        with Horizontal(id='body'):
            with Vertical(id='main'):
                yield Static('', id='welcome')
                yield RichLog(id='transcript', wrap=True, markup=True)
                yield Static('', id='taskstate')
                yield Static('', id='status')
                yield Static('', id='pending')
                yield PromptInput(placeholder='Ask anything…  "prepare job 7"  (/quit to leave)', id='prompt')
            yield Static('', id='sidebar')
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#prompt', Input).focus()
        self.screen.add_class('-welcome')
        self._fit(self.size.width)
        self._banner()
        self.set_interval(0.12, self._drain)
        self._set_status('ready')

    def _banner(self) -> None:
        log = self.query_one('#transcript', RichLog)
        previous = _read_session(self.person)
        if previous.get('unfinished'):
            self.thread_id = previous.get('thread_id', self.thread_id)
            self.checkpoint = previous.get('checkpoint')
            log.write(f'[yellow]A previous turn for {_e(self.person)} did not report completion.[/yellow]')
            log.write(f'  thread {_e(self.thread_id)} · last checkpoint {_e(self.checkpoint or "none")}')
            log.write('  Type /resume to continue it, or just ask something new.\n')
            self._enter_chat()
        else:
            log.write(f'[dim]Jobwatch · {_e(self.person)} · thread {_e(self.thread_id)}[/dim]\n')

    def _refresh_task_state(self) -> None:
        line = self.query_one('#taskstate', Static)
        if self.posting_id is None:
            line.update('')
            self.task_label = ''
            self._refresh_sidebar()
            return
        label = 'unknown'
        try:
            from pipeline.agentic import task_state
            with job_connection(load_config()) as jobs:
                label = task_state.task_card(jobs, self.posting_id)['state']
        except Exception:  # noqa: BLE001 - a missing database must not break the screen
            label = 'unavailable'
        line.update(f'job {self.posting_id}: {_e(str(label))}')
        self.task_label = str(label)
        self._refresh_sidebar()

    def _refresh_pending(self) -> None:
        strip = self.query_one('#pending', Static)
        if not self.pending:
            strip.remove_class('-on')
            strip.update('')
            self._sync_bar()
            self._refresh_sidebar()
            return
        rows = []
        for n, item in enumerate(self.pending, 1):
            if item.get('type') == 'approval':
                job = f' · job {item["posting_id"]}' if item.get('posting_id') is not None else ''
                summary = f'\n   [{MUTED}]{_e(str(item["summary"]))}[/]' if item.get('summary') else ''
                rows.append(f'[{ACCENT}]●[/] {n}. approve [bold]{_e(item.get("operation", "operation"))}[/bold]'
                            f'?{_e(job)}{summary}\n   '
                            '[b]a[/b] approve · [b]r[/b] reject · [b]e[/b] reject with reason')
            else:
                rows.append(f'{n}. {_e(str(item.get("question") or item.get("prompt") or "Jobwatch asks"))}  '
                            '(type your answer)')
        strip.update('\n'.join(rows))
        strip.add_class('-on')
        self._sync_bar()
        self._refresh_sidebar()

    def _enter_chat(self) -> None:
        """Leave the startup screen for the transcript; safe to call repeatedly."""
        if self.screen.has_class('-welcome'):
            self.screen.remove_class('-welcome')
            self._fit(self.size.width)

    def _fit(self, width: int) -> None:
        self.query_one('#sidebar', Static).set_class(width < 100, '-hidden')
        self.query_one('#welcome', Static).update(
            _wordmark(width) + f'\n\n[{MUTED}]{_e(self.person)} · {_e(self.thread_id)}[/]')

    def on_resize(self, event) -> None:
        self._fit(event.size.width)

    def _sync_bar(self) -> None:
        """Prompt bar: grey when idle, accent while a turn runs or a decision waits (the status
        line says which in words)."""
        self.query_one('#prompt', Input).set_class(self.busy or bool(self.pending), '-working')

    def _refresh_sidebar(self) -> None:
        rows = ['[b]Jobwatch[/b]', f'[{MUTED}]{_e(self.person)}[/]', f'[{MUTED}]{_e(self.thread_id)}[/]', '',
                '[b]Job[/b]']
        if self.posting_id is None:
            rows.append(f'[{MUTED}]none selected · /job N[/]')
        else:
            rows.append(f'#{self.posting_id}  {_e(self.task_label or "…")}')
        rows += ['', f'[b]Needs you[/b] ({len(self.pending)})']
        if self.pending:
            for item in self.pending:
                if item.get('type') == 'approval':
                    pid = f' · job {item["posting_id"]}' if item.get('posting_id') is not None else ''
                    rows.append(f'[{ACCENT}]●[/] approve {_e(str(item.get("operation", "operation")))}{_e(pid)}')
                else:
                    rows.append(f'[{ACCENT}]●[/] question')
        else:
            rows.append(f'[{MUTED}]○ nothing waiting[/]')
        rows += ['', '[b]Session[/b]',
                 f'[{MUTED}]{"● working" if self.busy else "○ idle"} · turn {self.turns}[/]',
                 f'[{MUTED}]tools last turn {self.tools_this_turn}[/]']
        shown = [(k, v) for k, v in self.last_usage.items() if isinstance(v, (int, float, str))][:4]
        for key, value in shown:
            rows.append(f'[{MUTED}]{_e(str(key))} {_e(str(value))}[/]')
        self.query_one('#sidebar', Static).update('\n'.join(rows))

    def _set_status(self, text: str) -> None:
        extra = f' · {len(self.deferred)} deferred' if self.deferred else ''
        self.query_one('#status', Static).update(f'{text}{extra} · {_e(self.thread_id)}')
        self._sync_bar()
        self._refresh_sidebar()

    # ----------------------------------------------------------------- input
    def decision_key(self, event) -> None:
        prompt = self.query_one('#prompt', Input)
        if (event.key in ('a', 'r', 'e') and self.pending and not prompt.value
                and self.pending[0].get('type') == 'approval'):
            event.prevent_default()
            event.stop()
            if event.key == 'e':
                self.reject_with_reason = True
                self._say('[dim]type the reason and press Enter (sent as a rejection)[/dim]')
            else:
                self._answer_pending(event.key)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one('#prompt', Input).value = ''
        if not text:
            return
        if text in ('/quit', '/exit'):
            self.exit()
            return
        if text.startswith('/job'):
            arg = text[4:].strip()
            self.posting_id = int(arg) if arg.isdigit() else None
            self._refresh_task_state()
            return
        if text == '/new':
            self.action_new_thread()
            return
        if text == '/resume':
            if not self.checkpoint:
                self._say('[yellow]Nothing to resume on this thread.[/yellow]')
                return
            self._start_turn(None, recover=True)
            return
        if self.pending:
            self._answer_pending(text)
            return
        if self.busy:
            self.deferred.append(text)
            self._say(f'[dim]parked as the next message: {_e(text)}[/dim]')
            self._set_status('waiting for the current turn')
            return
        self._start_turn(text)

    def _say(self, markup: str) -> None:
        self._enter_chat()
        self.query_one('#transcript', RichLog).write(markup)

    def action_new_thread(self) -> None:
        if self.busy:
            self._say('[yellow]Finish or cancel the current turn first.[/yellow]')
            return
        self.thread_id = f'tui-{time.strftime("%Y%m%d-%H%M%S")}'
        self.checkpoint = None
        self.pending = []
        self.posting_id = None
        self._refresh_pending()
        self._refresh_task_state()
        _write_session(self.person, {'thread_id': self.thread_id, 'unfinished': False})
        self._say(f'\n[dim]new thread {_e(self.thread_id)}[/dim]')
        self._set_status('ready')

    def action_cancel_turn(self) -> None:
        if not self.busy:
            self._say('[dim]nothing running[/dim]')
            return
        self.cancel.set()
        self._say('[yellow]cancel requested — the turn stops at its next checkpoint[/yellow]')
        self._set_status('cancelling')

    # ------------------------------------------------------------------ turn
    def _answer_pending(self, text: str) -> None:
        decisions = []
        reason, self.reject_with_reason = self.reject_with_reason, False
        for item in self.pending:
            kind = item.get('type')
            if kind == 'approval' and reason:
                decisions.append({'type': 'reject', 'message': text})
            elif kind == 'approval':
                lowered = text.lower()
                if lowered not in ('a', 'approve', 'y', 'yes', 'r', 'reject', 'n', 'no'):
                    self._say('[yellow]For an approval type a (approve) or r (reject).[/yellow]')
                    return
                decisions.append({'type': 'approve' if lowered.startswith(('a', 'y')) else 'reject'})
            else:
                decisions.append({'type': 'respond', 'message': text})
        self.pending = []
        self._refresh_pending()
        self._start_turn(None, decisions=decisions)

    def _start_turn(self, message: str | None, *, decisions: list[dict] | None = None,
                    recover: bool = False) -> None:
        if self.busy:
            if message:
                self.deferred.append(message)
            return
        self.busy = True
        self.cancel.clear()
        self.run_id = uuid.uuid4().hex
        self.turns += 1
        self.tools_this_turn = 0
        if message:
            self._say(f'[{ACCENT}]▎[/] {_e(message)}')
        elif decisions:
            self._say('[dim]› answering the pending decision[/dim]')
        else:
            self._say('[dim]› resuming the unfinished turn[/dim]')
        _write_session(self.person, {'thread_id': self.thread_id, 'run_id': self.run_id,
                                     'checkpoint': self.checkpoint, 'unfinished': True})
        self._set_status('working')
        self._turn(message, decisions, recover)

    @work(thread=True, exclusive=True)
    def _turn(self, message: str | None, decisions: list[dict] | None, recover: bool) -> None:
        started = time.monotonic()
        try:
            with users.use(self.person):
                execution = Execution(
                    self.run_id or uuid.uuid4().hex,
                    emit=lambda kind, data: self.events.put(('event', kind, data)),
                    cancelled=lambda: self.cancel.is_set(),
                )
                result = dispatch(person=self.person, thread_id=self.thread_id, message=message,
                                  decisions=decisions, human_decision=bool(decisions),
                                  config=load_config(), execution=execution,
                                  expected_checkpoint=self.checkpoint, recover=recover)
            self.events.put(('done', result, time.monotonic() - started))
        except RuntimeErrorSafe as exc:
            self.events.put(('failed', str(exc), time.monotonic() - started))
        except Exception as exc:  # noqa: BLE001 - a crash must not kill the TUI
            self.events.put(('failed', f'{type(exc).__name__}: {exc}', time.monotonic() - started))

    # ------------------------------------------------------------- rendering
    def _drain(self) -> None:
        while True:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                return
            kind = item[0]
            if kind == 'event':
                self._render_event(item[1], item[2])
            elif kind == 'done':
                self._render_done(item[1], item[2])
            else:
                self._render_failed(item[1], item[2])

    def _render_event(self, kind: str, data: dict) -> None:
        if kind == 'model_started':
            role = data.get('role') or 'model'
            self._set_status(f'{role} thinking…')
        elif kind == 'model_finished':
            self._set_status('working')
        elif kind == 'tool_started':
            name = str(data.get('tool') or data.get('name') or 'tool')
            self._tool_started[name] = time.monotonic()
            self._set_status(f'running {name}')
        elif kind == 'tool_finished':
            name = str(data.get('tool') or data.get('name') or 'tool')
            took = time.monotonic() - self._tool_started.pop(name, time.monotonic())
            self.tools_this_turn += 1
            self._say(f'[dim]  → {_e(name)} · {took:.1f}s[/dim]')
            self._set_status('working')
        elif kind == 'execution_error':
            self._say(f'[red]! {_e(str(data.get("error") or "execution error"))}[/red]')

    def _render_done(self, result: dict, elapsed: float) -> None:
        self.busy = False
        status = result.get('status')
        self.checkpoint = result.get('checkpoint_id') or self.checkpoint
        answer = result.get('answer')
        if answer:
            self.query_one('#transcript', RichLog).write(Markdown(_clean(str(answer))))
        pending = result.get('interactions') or []
        self.pending = [i for i in pending if i.get('type') in ('approval', 'question')]
        if self.pending:
            self._render_pending(self.pending)
        for item in self.pending:
            if isinstance(item.get('posting_id'), int):
                self.posting_id = item['posting_id']
        self._refresh_pending()
        self._refresh_task_state()
        usage = result.get('usage') or {}
        self.last_usage = usage if isinstance(usage, dict) else {}
        finish = 'interrupted' if self.pending else status
        self._say(f'[dim]— {_e(str(finish))} in {elapsed:.1f}s{_e(f" · {usage}") if usage else ""}[/dim]\n')
        _write_session(self.person, {'thread_id': self.thread_id, 'run_id': self.run_id,
                                     'checkpoint': self.checkpoint,
                                     'unfinished': bool(self.pending)})
        self._set_status('waiting for your decision' if self.pending else 'ready')
        if self.deferred and not self.pending:
            nxt = self.deferred.pop(0)
            self._say(f'[dim]sending the parked message: {_e(nxt)}[/dim]')
            self._start_turn(nxt)

    def _render_pending(self, pending: list[dict]) -> None:
        self._say('[bold yellow]Waiting for you:[/bold yellow]')
        for item in pending:
            kind = item.get('type')
            if kind == 'approval':
                self._say(f'  approve [bold]{_e(item.get("operation", "operation"))}[/bold]?  '
                          f'a = approve · r = reject')
                detail = {k: item[k] for k in ('posting_id', 'summary') if item.get(k) is not None}
                if detail:
                    self._say(f'  [dim]{_e(json.dumps(detail)[:400])}[/dim]')
            else:
                self._say(f'  {_e(str(item.get("question") or item.get("prompt") or "Jobwatch asks:"))}')
        self._say('[dim]press a / r / e with the prompt empty, or type your answer and press Enter[/dim]')

    def _render_failed(self, error: str, elapsed: float) -> None:
        self.busy = False
        self._refresh_task_state()
        if error == 'person_busy':
            self._say('[yellow]Another turn for this person is already running.[/yellow]')
            self._say('[dim]Wait for it to finish, then send again — nothing was lost.[/dim]')
            self._set_status('waiting for this person lock')
        elif error == 'cancelled':
            self._say(f'[yellow]cancelled after {elapsed:.1f}s — completed steps are kept[/yellow]')
            self._set_status('cancelled')
        else:
            self._say(f'[red]{_e(str(error))}[/red]')
            self._set_status('failed')
        _write_session(self.person, {'thread_id': self.thread_id, 'run_id': self.run_id,
                                     'checkpoint': self.checkpoint, 'unfinished': False})
        if self.deferred:
            nxt = self.deferred.pop(0)
            self._start_turn(nxt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='jobwatch-tui', description=__doc__)
    parser.add_argument('--person', help='Jobwatch person; defaults to the current one')
    parser.add_argument('--thread', help='thread id to continue')
    args = parser.parse_args(argv)
    person = args.person or users.current()
    JobwatchTUI(person, args.thread).run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
