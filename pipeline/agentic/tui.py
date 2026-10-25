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
import uuid
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.markup import escape as _e
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Input, RichLog, Static

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic.chat import dispatch, job_connection
from pipeline.agentic.execution import Execution
from pipeline.agentic.runtime import RuntimeErrorSafe

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


class PromptInput(Input):
    """Lets the app take a / r / e before they are typed, while a decision is pending."""

    def on_key(self, event) -> None:
        self.app.decision_key(event)


class JobwatchTUI(App):
    """A transcript, a prompt line and an honest status line."""

    CSS = """
    Screen { layout: vertical; }
    #transcript { height: 1fr; padding: 0 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #taskstate { height: 1; padding: 0 1; color: $accent; }
    #pending { height: auto; padding: 0 1; border: round $warning; display: none; }
    #pending.-on { display: block; }
    #prompt { dock: bottom; }
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
        self.reject_with_reason = False

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        with Vertical():
            yield RichLog(id='transcript', wrap=True, markup=True)
            yield Static('', id='taskstate')
            yield Static('', id='status')
            yield Static('', id='pending')
        yield PromptInput(placeholder='Ask Jobwatch…  (/quit to leave)', id='prompt')
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#prompt', Input).focus()
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
        else:
            log.write(f'[dim]Jobwatch · {_e(self.person)} · thread {_e(self.thread_id)}[/dim]\n')

    def _refresh_task_state(self) -> None:
        line = self.query_one('#taskstate', Static)
        if self.posting_id is None:
            line.update('')
            return
        label = 'unknown'
        try:
            from pipeline.agentic import task_state
            with job_connection(load_config()) as jobs:
                label = task_state.task_card(jobs, self.posting_id)['state']
        except Exception:  # noqa: BLE001 - a missing database must not break the screen
            label = 'unavailable'
        line.update(f'job {self.posting_id}: {_e(str(label))}')

    def _refresh_pending(self) -> None:
        strip = self.query_one('#pending', Static)
        if not self.pending:
            strip.remove_class('-on')
            strip.update('')
            return
        rows = []
        for n, item in enumerate(self.pending, 1):
            if item.get('type') == 'approval':
                request = (item.get('action_requests') or [{}])[0]
                rows.append(f'{n}. approve [bold]{_e(str(request.get("name", "operation")))}[/bold]?  '
                            '[b]a[/b] approve · [b]r[/b] reject · [b]e[/b] reject with reason')
            else:
                rows.append(f'{n}. {_e(str(item.get("question") or item.get("prompt") or "Jobwatch asks"))}  '
                            '(type your answer)')
        strip.update('\n'.join(rows))
        strip.add_class('-on')

    def _set_status(self, text: str) -> None:
        extra = f' · {len(self.deferred)} deferred' if self.deferred else ''
        self.query_one('#status', Static).update(f'{text}{extra} · {_e(self.thread_id)}')

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
        if message:
            self._say(f'[bold cyan]›[/bold cyan] {_e(message)}')
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
            self._say(f'[dim]⏺[/dim] {_e(name)} …')
            self._set_status(f'running {name}')
        elif kind == 'tool_finished':
            name = str(data.get('tool') or data.get('name') or 'tool')
            took = time.monotonic() - self._tool_started.pop(name, time.monotonic())
            self._say(f'[dim]⏺[/dim] {_e(name)} [green]✓[/green] [dim]{took:.1f}s[/dim]')
            self._set_status('working')
        elif kind == 'execution_error':
            self._say(f'[red]! {_e(str(data.get("error") or "execution error"))}[/red]')

    def _render_done(self, result: dict, elapsed: float) -> None:
        self.busy = False
        status = result.get('status')
        self.checkpoint = result.get('checkpoint_id') or self.checkpoint
        answer = result.get('answer')
        if answer:
            self.query_one('#transcript', RichLog).write(Markdown(str(answer)))
        pending = result.get('interactions') or []
        self.pending = [i for i in pending if i.get('type') in ('approval', 'question')]
        if self.pending:
            self._render_pending(self.pending)
        for item in self.pending:
            args = ((item.get('action_requests') or [{}])[0].get('args') or {})
            if isinstance(args.get('posting_id'), int):
                self.posting_id = args['posting_id']
        self._refresh_pending()
        self._refresh_task_state()
        usage = result.get('usage') or {}
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
                request = (item.get('action_requests') or [{}])[0]
                self._say(f'  approve [bold]{_e(str(request.get("name", "operation")))}[/bold]?  '
                          f'a = approve · r = reject')
                args = request.get('args')
                if args:
                    self._say(f'  [dim]{_e(json.dumps(args)[:400])}[/dim]')
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
