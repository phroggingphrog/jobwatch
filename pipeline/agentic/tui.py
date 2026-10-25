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
from rich.padding import Padding
from rich.text import Text
from rich.markup import escape as _escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, RichLog, Static

from jobwatch import users
from jobwatch.config import load_config
from pipeline.agentic.chat import dispatch, job_connection
from pipeline.agentic.execution import Execution
from pipeline.agentic.runtime import RuntimeErrorSafe
from pipeline.agentic import tui_theme as theme
from pipeline.agentic import tui_views as views
from pipeline.agentic.tui_data import Backend, WebBackend

# Idea from deepagents-code (LangChain, MIT): strip hidden/bidi control characters from
# model, tool and posting text before it is shown. Reimplemented, no code copied.

_clean = theme.clean
_e = theme.esc


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
    """Lets the app take a / r / e / tab before they are typed, while a decision is pending."""

    def on_key(self, event) -> None:
        self.app.decision_key(event)


class JobwatchTUI(App):
    """Main board: job feed, the conversation, the approval strip and one prompt line."""

    CSS = theme.BASE_CSS + f"""
    #tabs {{ height: 1; }}
    #main {{ height: 1fr; }}
    #left {{ width: 1fr; padding: 0 1; }}
    #transcript {{ height: 1fr; background: {theme.BG}; scrollbar-size-vertical: 1; }}
    #taskstate {{ height: auto; color: {theme.AMETHYST}; }}
    #status {{ display: none; }}
    #pending {{ height: auto; background: {theme.PANEL}; padding: 0 2; border-left: thick {theme.AMBER}; display: none; }}
    #pending.-on {{ display: block; }}
    #chips {{ height: auto; display: none; color: {theme.MUTED}; }}
    #chips.-on {{ display: block; }}
    #promptbox {{ height: auto; background: {theme.INPUT}; border-left: thick {theme.AMETHYST}; padding: 0 1; margin-top: 1; }}
    #hint {{ height: 1; color: {theme.MUTED}; }}
    #prompt {{ background: {theme.INPUT}; border: none; height: 1; padding: 0; }}
    #prompt:focus {{ border: none; background-tint: transparent; }}
    #agentline {{ height: 1; color: {theme.MUTED}; }}
    #sidebar {{ width: 31; background: {theme.SIDE}; padding: 1 2 0 2; }}
    #sidebar.-hidden {{ display: none; }}
    #sidebar.-overlay {{ display: block; width: 100%; dock: top; height: 1fr; layer: above; }}
    #narrowfeed {{ height: auto; display: none; border-bottom: solid {theme.RULE}; }}
    #narrowfeed.-on {{ display: block; }}
    #footer {{ height: 1; background: {theme.BG}; }}
    """

    BINDINGS = [
        Binding('ctrl+c', 'cancel_turn', 'cancel turn', priority=True),
        Binding('ctrl+n', 'new_thread', 'new thread'),
    ]

    def __init__(self, person: str, thread_id: str | None = None, backend: Backend | None = None) -> None:
        super().__init__()
        self.person = person
        self.backend: Backend = backend if backend is not None else WebBackend(person)
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
        # main-board state
        self.rows: list[dict] = []
        self.counts: dict = {'needs_you': 0, 'needs_info': 0, 'outcome_unknown': 0, 'submitted': 0}
        self.services: list[tuple[str, str]] = []
        self.feed_focus = False
        self.feed_index = 0
        self.entries: list[tuple] = []
        self.title_text = 'New thread'
        self.narrow = False
        self.model_name = ''
        self.current_tool = ''
        self.status_text = 'ready'

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Static('', id='tabs')
        with Horizontal(id='main'):
            with Vertical(id='left'):
                yield Static('', id='narrowfeed')
                yield RichLog(id='transcript', wrap=True, markup=True)
                yield Static('', id='taskstate')
                yield Static('', id='status')
                yield Static('', id='pending')
                yield Static('', id='chips')
                with Vertical(id='promptbox'):
                    yield Static('', id='hint')
                    yield PromptInput(placeholder='', id='prompt')
                    yield Static('', id='agentline')
            yield Static('', id='sidebar')
        yield Static('', id='footer')

    def on_mount(self) -> None:
        self.query_one('#prompt', Input).focus()
        self._banner()
        self.set_interval(0.12, self._drain)
        self._set_status('ready')
        self._load_feed()
        self._layout_for(self.size.width)
        self._refresh_chrome()

    def on_resize(self, event) -> None:
        self._layout_for(event.size.width)

    def _layout_for(self, width: int) -> None:
        narrow = width < 100
        self.cols = width
        side = self.query_one('#sidebar')
        if narrow != self.narrow or not side.has_class('-hidden') and narrow:
            self.narrow = narrow
        side.set_class(narrow, '-hidden')
        if narrow:
            side.remove_class('-overlay')
        self.query_one('#narrowfeed').set_class(narrow, '-on')
        self._refresh_chrome()
        self._rewrite_log()

    # ------------------------------------------------------------- feed data
    def _load_feed(self) -> None:
        try:
            self.rows = self.backend.overview()
            self.counts = self.backend.counts(self.rows)
        except Exception:  # noqa: BLE001 - a missing database must not break the screen
            self.rows, self.counts = [], {'needs_you': 0, 'needs_info': 0, 'outcome_unknown': 0, 'submitted': 0}
        try:
            self.services = self.backend.services()
        except Exception:  # noqa: BLE001
            self.services = []
        try:
            self.model_name = self.backend.chat_model()
        except Exception:  # noqa: BLE001
            self.model_name = ''
        self.feed_index = min(self.feed_index, max(len(self.rows) - 1, 0))

    def _refresh_chrome(self) -> None:
        width = max(getattr(self, 'cols', 0) or self.size.width, 20)
        inner = max(width - 2, 20)
        tabs = Text()
        tabs.append(' ' + theme.fit(self.title_text, 30).ljust(34), style=f'bold on {theme.PANEL}')
        tabs.append('  +', style=theme.MUTED)
        self.query_one('#tabs', Static).update(tabs)
        selected = self.feed_index if self.feed_focus else None
        side = self.query_one('#sidebar', Static)
        side.update(Text('\n').join(views.sidebar(self.title_text, self.counts, self.rows, selected, self.services,
                                                  27 if not side.has_class('-overlay') else min(width - 6, 60))))
        narrow = self.query_one('#narrowfeed', Static)
        if self.narrow:
            lines = [views.narrow_header(self.counts, inner)] + views.narrow_feed(self.rows, inner, selected)
            narrow.update(Text('\n').join(lines))
        self.query_one('#hint', Static).update(views.hint(self.pending, self.busy, self.query_one('#prompt', Input).value))
        agent = Text()
        agent.append('Agent', style=theme.AMETHYST).append(' · ', style=theme.MUTED).append('Jobwatch', style='bold')
        if self.model_name:
            agent.append(f' [{theme.plain(self.model_name)}]'.replace('[', '\\[') if False else f' {theme.plain(self.model_name)}',
                         style=theme.MUTED)
        self.query_one('#agentline', Static).update(agent)
        keys = ([('tab', 'queue'), ('ctrl+p', 'commands')] if self.narrow else [('tab', 'sidebar'), ('ctrl+p', 'commands')])
        if self.busy:
            keys = [('ctrl+c', 'cancel turn')] + keys
        self.query_one('#footer', Static).update(views.footer(width, '~ ' + theme.fit(self.status_text, width // 2), keys))

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one('#hint', Static).update(views.hint(self.pending, self.busy, event.value))

    # ------------------------------------------------------------ transcript
    def _log_width(self) -> int:
        return max(self.query_one('#transcript', RichLog).size.width - 2, 40)

    def _write_entry(self, entry: tuple) -> None:
        log = self.query_one('#transcript', RichLog)
        kind = entry[0]
        width = self._log_width()
        if kind == 'raw':
            log.write(entry[1])
        elif kind == 'user':
            if self.narrow:
                for line in views.gutter('you', entry[1], theme.MUTED, width):
                    log.write(line)
            else:
                for line in views.user_block(entry[1], width):
                    log.write(line)
                log.write('')
        elif kind == 'meta':
            log.write(Text(f'  {theme.plain(entry[1])}', style=theme.MUTED))
            log.write('')
        elif kind == 'tool':
            log.write(views.tool_line(entry[1], entry[2], 7 if self.narrow else 2, entry[3] if len(entry) > 3 else None))
        elif kind == 'agent':
            if self.narrow:
                for n, line in enumerate(views.gutter('agent', _clean(entry[1]), theme.AMETHYST, width)):
                    log.write(line)
            else:
                log.write(Padding(Markdown(_clean(str(entry[1]))), (0, 0, 1, 2)))

    def _add(self, entry: tuple) -> None:
        self.entries.append(entry)
        self._write_entry(entry)

    def _rewrite_log(self) -> None:
        try:
            log = self.query_one('#transcript', RichLog)
        except Exception:  # noqa: BLE001
            return
        log.clear()
        for entry in self.entries:
            self._write_entry(entry)

    def _banner(self) -> None:
        previous = _read_session(self.person)
        if previous.get('unfinished'):
            self.thread_id = previous.get('thread_id', self.thread_id)
            self.checkpoint = previous.get('checkpoint')
            self._say(f'[yellow]A previous turn for {_e(self.person)} did not report completion.[/yellow]')
            self._say(f'  thread {_e(self.thread_id)} · last checkpoint {_e(self.checkpoint or "none")}')
            self._say('  Type /resume to continue it, or just ask something new.\n')
        else:
            self._say(f'[dim]Jobwatch · {_e(self.person)} · thread {_e(self.thread_id)}[/dim]\n')
        if self.rows == [] and not previous.get('unfinished'):
            pass

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
        else:
            strip.update(views.approval_strip(self.pending))
            strip.add_class('-on')
        self._refresh_chrome()

    def _set_status(self, text: str) -> None:
        extra = f' · {len(self.deferred)} deferred' if self.deferred else ''
        self.status_text = f'{text}{extra}'
        self.query_one('#status', Static).update(f'{text}{extra} · {_e(self.thread_id)}')
        if self.is_mounted:
            self._refresh_chrome()

    # ----------------------------------------------------------------- input
    def decision_key(self, event) -> None:
        prompt = self.query_one('#prompt', Input)
        key = event.key
        if key == 'tab':
            event.prevent_default()
            event.stop()
            self.action_toggle_sidebar()
            return
        if self.feed_focus and key in ('up', 'down', 'enter', 'escape'):
            event.prevent_default()
            event.stop()
            if key == 'up':
                self.feed_index = max(self.feed_index - 1, 0)
            elif key == 'down':
                self.feed_index = min(self.feed_index + 1, max(len(self.rows) - 1, 0))
            elif key == 'enter':
                self.open_job(self.feed_index)
            else:
                self.action_toggle_sidebar()
            self._refresh_chrome()
            return
        approval = bool(self.pending) and self.pending[0].get('type') == 'approval'
        if approval and not prompt.value:
            submit = self.pending[0].get('operation') == 'submit_application'
            if key == 'enter' and submit:
                event.prevent_default()
                event.stop()
                self.open_review()
            elif key in ('a', 'r', 'e'):
                event.prevent_default()
                event.stop()
                if key == 'a' and submit:
                    self._say('[dim]A Submit is approved only on the review screen: press enter.[/dim]')
                elif key == 'e':
                    self.reject_with_reason = True
                    self._say('[dim]type the reason and press Enter (sent as a rejection)[/dim]')
                else:
                    self._answer_key(key)

    def action_toggle_sidebar(self) -> None:
        side = self.query_one('#sidebar')
        if self.narrow:
            overlay = not side.has_class('-overlay')
            side.set_class(not overlay, '-hidden')
            side.set_class(overlay, '-overlay')
            self.feed_focus = overlay
        else:
            self.feed_focus = not self.feed_focus
        self._refresh_chrome()

    def open_job(self, index: int) -> None:
        if 0 <= index < len(self.rows):
            self.posting_id = self.rows[index]['posting_id']
            self._refresh_task_state()
            self.show_view('detail', self.posting_id)

    def open_review(self) -> None:
        pid = self.pending[0].get('posting_id') if self.pending else self.posting_id
        self.show_view('review', pid)

    def show_view(self, name: str, arg=None) -> None:
        """Other boards are added in tui_screens; until a board exists the command says so."""
        try:
            from pipeline.agentic import tui_screens
        except ImportError:
            self._say(f'[dim]{_e(name)} is not available yet[/dim]')
            return
        tui_screens.open_view(self, name, arg)

    # ---- hooks the board screens call
    def open_link(self, link: str) -> None:
        """Open an ad URL or a drafted PDF with the desktop's default program; say where it is either way."""
        if not link:
            self._say('[yellow]Nothing to open here.[/yellow]')
            return
        target = self.backend.resolve_link(link)
        self._say(f'[dim]opening {_e(target)}[/dim]')
        try:
            import webbrowser
            webbrowser.open(target if target.startswith('http') else Path(target).as_uri())
        except Exception:  # noqa: BLE001 - a headless terminal has nothing to open it with
            pass

    def ask_agent(self, text: str) -> None:
        while len(self.screen_stack) > 1:
            self.pop_screen()
        if self.pending:
            self._say('[yellow]Answer the waiting decision first.[/yellow]')
        elif self.busy:
            self.deferred.append(text)
        else:
            self._start_turn(text)

    def fill_form(self, posting_id) -> None:
        """Fill the form: if a Submit for this job waits, open its review; otherwise ask the agent to prepare it."""
        waiting = [i for i in self.pending if i.get('operation') == 'submit_application' and i.get('posting_id') == posting_id]
        if waiting:
            self.show_view('review', posting_id)
        else:
            self.ask_agent(f'Prepare the application for posting {posting_id} and fill in the employer form. Do not submit it.')

    def begin_edit(self, prefix: str) -> None:
        self.reject_with_reason = True
        prompt = self.query_one('#prompt', Input)
        prompt.value = prefix
        prompt.focus()
        self._say('[dim]type the change and press Enter (sent as a rejection with your note)[/dim]')

    def decide_submit(self, decision: str) -> None:
        """Called only by the review screen: the single place a Submit is approved."""
        if not self.pending or self.pending[0].get('operation') != 'submit_application':
            return
        self._answer_key('a' if decision == 'approve' else 'r')

    def pick_file(self, purpose: str = 'chat') -> None:
        try:
            from pipeline.agentic import tui_files
        except ImportError:
            self._say('[dim]the file picker is not available yet[/dim]')
            return
        tui_files.open_picker(self, purpose)

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
        if text in VIEW_COMMANDS:
            self.show_view(VIEW_COMMANDS[text])
            return
        if text in AGENT_COMMANDS:
            text = AGENT_COMMANDS[text]
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
        self._add(('raw', markup))

    def action_new_thread(self) -> None:
        if self.busy:
            self._say('[yellow]Finish or cancel the current turn first.[/yellow]')
            return
        self.thread_id = f'tui-{time.strftime("%Y%m%d-%H%M%S")}'
        self.checkpoint = None
        self.pending = []
        self.posting_id = None
        self.entries = []
        self.title_text = 'New thread'
        self.query_one('#transcript', RichLog).clear()
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
        """Typed text never approves: `r` rejects, any other text rejects with that message (an edit)."""
        decisions = []
        reason, self.reject_with_reason = self.reject_with_reason, False
        for item in self.pending:
            kind = item.get('type')
            if kind == 'approval':
                if reason or text.lower() not in ('r', 'reject', 'n', 'no'):
                    decisions.append({'type': 'reject', 'message': text})
                else:
                    decisions.append({'type': 'reject'})
            else:
                decisions.append({'type': 'respond', 'message': text})
        if len(text) == 1 and text.lower() == 'a':
            self._say('[yellow]Typing never approves. Press a with the prompt empty (or enter on a Submit).[/yellow]')
            return
        self.pending = []
        self._refresh_pending()
        self._start_turn(None, decisions=decisions)

    def _answer_key(self, key: str) -> None:
        """a / r pressed with an empty prompt on a non-submit approval."""
        decisions = [{'type': 'approve' if key == 'a' else 'reject'} if item.get('type') == 'approval'
                     else {'type': 'respond', 'message': ''} for item in self.pending]
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
        self.turn_started = time.monotonic()
        if message:
            if self.title_text == 'New thread':
                self.title_text = message[:30]
            self._add(('user', message))
        elif decisions:
            self._say('[dim]› answering the pending decision[/dim]')
        else:
            self._say('[dim]› resuming the unfinished turn[/dim]')
        _write_session(self.person, {'thread_id': self.thread_id, 'run_id': self.run_id,
                                     'checkpoint': self.checkpoint, 'unfinished': True})
        self._set_status('◐ working')
        self._refresh_chrome()
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
            self._set_status(f'◐ {role} thinking…')
        elif kind == 'model_finished':
            self._set_status('◐ working')
        elif kind == 'tool_started':
            name = str(data.get('tool') or data.get('name') or 'tool')
            self._tool_started[name] = time.monotonic()
            self.current_tool = name
            self._set_status(f'◐ running {name} · ctrl+c cancels this turn, nothing is sent')
        elif kind == 'tool_finished':
            name = str(data.get('tool') or data.get('name') or 'tool')
            took = time.monotonic() - self._tool_started.pop(name, time.monotonic())
            self._add(('tool', name, 'done', took))
            self._set_status('◐ working')
        elif kind == 'execution_error':
            self._say(f'[red]✕ {_e(str(data.get("error") or "execution error"))}[/red]')

    def _render_done(self, result: dict, elapsed: float) -> None:
        self.busy = False
        status = result.get('status')
        self.checkpoint = result.get('checkpoint_id') or self.checkpoint
        answer = result.get('answer')
        pending = result.get('interactions') or []
        self.pending = [i for i in pending if i.get('type') in ('approval', 'question')]
        usage = result.get('usage') or {}
        finish = 'waiting on you' if self.pending else status
        self._add(('meta', f'Jobwatch{" · " + self.model_name if self.model_name else ""} · {elapsed:.0f}s · {finish}'))
        if answer:
            self._add(('agent', str(answer)))
        for item in self.pending:
            if isinstance(item.get('posting_id'), int):
                self.posting_id = item['posting_id']
        self._refresh_pending()
        self._refresh_task_state()
        self._load_feed()
        if usage:
            self._say(f'[dim]  {_e(usage)}[/dim]\n')
        _write_session(self.person, {'thread_id': self.thread_id, 'run_id': self.run_id,
                                     'checkpoint': self.checkpoint,
                                     'unfinished': bool(self.pending)})
        self._set_status('waiting for your decision' if self.pending else 'ready')
        self._refresh_chrome()
        if self.deferred and not self.pending:
            nxt = self.deferred.pop(0)
            self._say(f'[dim]sending the parked message: {_e(nxt)}[/dim]')
            self._start_turn(nxt)

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
            self._say(f'[red]✕ failed[/red]  {_e(str(error))}')
            self._say('[dim]Nothing was submitted. Send the message again to retry.[/dim]')
            self._set_status('failed')
        _write_session(self.person, {'thread_id': self.thread_id, 'run_id': self.run_id,
                                     'checkpoint': self.checkpoint, 'unfinished': False})
        self._refresh_chrome()
        if self.deferred:
            nxt = self.deferred.pop(0)
            self._start_turn(nxt)


VIEW_COMMANDS = {'/today': 'today', '/jobs': 'jobs', '/applications': 'applications', '/inbox': 'inbox',
                 '/table': 'table', '/sources': 'sources', '/insights': 'insights', '/models': 'models'}
AGENT_COMMANDS = {'/run': 'Start a watcher run now.', '/profile': 'Check the career profile you score against.'}


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
