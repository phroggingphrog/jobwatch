"""TUI behaviour with Textual's headless pilot; dispatch is replaced, no model is called."""
import asyncio

import pytest

pytest.importorskip('textual')

import os  # noqa: E402
from pathlib import Path  # noqa: E402

from pipeline.agentic import tui  # noqa: E402
from pipeline.agentic.tui_data import Backend  # noqa: E402

SHOTS = Path(os.environ.get('JOBWATCH_TUI_SHOTS', os.path.expanduser('~/workspace/jobwatch-tui-build')))

ROWS = [
    {'posting_id': 42, 'employer': 'Acme Analytics', 'title': 'Senior Data Analyst', 'score': 4.2, 'state': 'draft ready', 'detail': ''},
    {'posting_id': 43, 'employer': 'Northwind', 'title': 'Data Analyst', 'score': 4.0, 'state': 'awaiting browser press', 'detail': ''},
    {'posting_id': 44, 'employer': 'Fabrikam', 'title': 'Vacation Intern', 'score': 3.8, 'state': 'outcome unknown',
     'detail': 'Outcome unknown; retries are paused. Check the employer site or your email before anything is sent again.'},
    {'posting_id': 45, 'employer': 'Contoso', 'title': 'Analyst', 'score': 3.6, 'state': 'submitted', 'detail': ''},
    {'posting_id': 46, 'employer': 'Globex', 'title': 'Data Scientist', 'score': 3.4, 'state': 'drafting', 'detail': ''},
    {'posting_id': 47, 'employer': 'Initech', 'title': 'Analyst', 'score': 3.1, 'state': 'queued', 'detail': ''},
    {'posting_id': 48, 'employer': 'Hooli', 'title': 'Analyst', 'score': 2.9, 'state': 'failed', 'detail': ''},
]


class FakeBackend(Backend):
    def __init__(self, rows=None):
        self.rows = ROWS if rows is None else rows

    def overview(self):
        return self.rows

    def counts(self, rows):
        return {'needs_you': 2, 'needs_info': 0, 'outcome_unknown': 1, 'submitted': 1}

    def services(self):
        return [('Watcher', 'Healthy'), ('Web board', 'Healthy'), ('Indeed read', 'Attention')]

    def chat_model(self):
        return '[model]'

    def nav_counts(self):
        return {'applications': 5, 'inbox': 1}

    def today(self):
        return {'total': 6, 'progress': {'read': 8, 'total': 8, 'left': 0}, 'rows': [
            dict(id=11, score5=4.6, title='Junior Data Analyst', company='Acme Analytics', where='Melbourne VIC', listed_ago='13h',
                 salary='$70,000 - $85,000', status='seen'),
            dict(id=12, score5=4.3, title='Business Intelligence Analyst', company='Northwind', where='Sydney NSW', listed_ago='37h',
                 salary='$70,000 - $85,000', status='saved'),
            dict(id=13, score5=None, title='Data Analyst (Graduate)', company='Globex', where='Remote', listed_ago='2d',
                 salary='$70,000 - $85,000', status='saved', app_status='drafted'),
            dict(id=14, score5=None, title='Reporting Analyst', company='Initech', where='Brisbane QLD', listed_ago='3d',
                 salary='$70,000 - $85,000', status='applied')]}

    def job(self, posting_id):
        return {'job': {'title': 'Data Analyst (Graduate)', 'company': 'Globex', 'where': 'Remote', 'posted_ago': '2d',
                        'salary': '$70,000 - $85,000', 'wt_label': 'full_time', 'src_labels': ['Greenhouse'],
                        'posted_abs': 'Fri 23 Oct 2026', 'rec_word': 'Decent match', 'score5': None, 'url': 'https://example.org/ad',
                        'ai': {'reason': 'Graduate-friendly, SQL, Python, Excel and Tableau named in the ad.'},
                        'blocks': [{'text': 'Globex is hiring a Data Analyst (Graduate). You will build dashboards.'}]},
                'draft': {'state': 'ready'}, 'draft_links': {'cv': '/files/drafts/a/cv.pdf', 'letter': '/files/drafts/a/letter.pdf'}}

    def applications(self):
        def a(pid, title, company, status, files=None):
            return {'posting_id': pid, 'title': title, 'company': company, 'status': status, 'files': files or {}}
        return {'total': 5, 'cols': [
            ('interested', 'Saved', [a(1, 'Business Intelligence Analyst', 'Northwind', 'interested')]),
            ('drafted', 'Drafted', [a(13, 'Data Analyst (Graduate)', 'Globex', 'drafted', {'cv': '/files/drafts/x/cv.pdf', 'letter': '/files/drafts/x/letter.pdf'})]),
            ('applied', 'Applied', [a(14, 'Reporting Analyst', 'Initech', 'applied'), a(15, 'Research Data Officer', 'Umbrella', 'applied')]),
            ('interview', 'Interview', [a(16, 'Analytics Engineer', 'Hooli', 'interview')])],
            'closed': [a(17, 'Operations Analyst', 'Vandelay', 'rejected')]}

    def inbox(self):
        return {'open': [{'id': 1, 'posting_id': 14, 'title': 'Reporting Analyst', 'company': 'Initech', 'subject': 'Interview invitation - Reporting Analyst',
                          'from_addr': 'recruiter@initech.example', 'received_ago': 'just now', 'confidence': 0.9,
                          'proposed_status': 'interview', 'app_status': 'applied'}], 'closed': []}

    def inbox_decide(self, proposal_id, decision):
        self.decided = (proposal_id, decision)
        return 'Approved'

    def table(self, **params):
        self.table_params = params
        rows = [dict(id=11, score5=4.6, title='Junior Data Analyst', company='Acme Analytics', archetype='Data analyst', where='Melbourne VIC',
                     salary='$70k - $85k', listed_ago='13h', status='seen', ai_state='show'),
                dict(id=12, score5=4.3, title='Business Intelligence Analyst', company='Northwind', archetype='Data analyst', where='Sydney NSW',
                     salary='$70k - $85k', listed_ago='37h', status='saved', ai_state='show'),
                dict(id=14, score5=None, title='Reporting Analyst', company='Initech', archetype='', where='Brisbane QLD',
                     salary='$70k - $85k', listed_ago='3d', status='applied', ai_state='show')]
        return {'rows': rows, 'total': 6, 'counts': {'ai': {'show': 6, 'hide': 2, 'pending': 0}}, 'ai_text': 'Worth a look',
                'progress': {'read': 8, 'total': 8, 'left': 0}}

    def sources(self, sector='', enabled=''):
        names = ['Deloitte Australia', 'KPMG Australia', 'BDO Australia (experienced)', 'RSM Australia']
        return {'health': [], 'sectors': ['Accounting', 'Finance'],
                'employers': [{'name': n, 'sector': 'accounting', 'provider': 'workday', 'live': 0, 'vc_total': 245, 'vc_au': 245, 'vc_vic': 51,
                               'verified_at': '2026-10-06', 'notes': 'Careers system checked.'} for n in names]}

    def insights(self):
        return {'totals': {'postings': 8, 'matches': 8, 'matches_7d': 6, 'matches_30d': 8, 'employers_live': 0},
                'series': [(f'2026-10-{d:02d}', n) for d, n in zip(range(1, 31), [0, 1, 0, 2] * 8)],
                'by_arm': [['ict', 'core', 8, 'ICT data (backup)']], 'by_src': [['greenhouse', 8, 'Greenhouse']],
                'top': [('Vandelay', 3, 1), ('Umbrella', 2, 1)], 'remote': {'matches': (1, 8), 'all': (1, 8)},
                'callbacks': {'_all': {'mean': 0.111, 'hdi': (0.0, 0.25), 'successes': 1, 'n': 2}},
                'progress': {'read': 8, 'total': 8}}

    def models(self):
        roles = ['Reads and scores ads', 'Judges how well you fit', 'Writes CV + letter', 'Checks the letter', 'Answers chat', 'Fills form answers']
        return {'rows': [{'role': r.split()[0].lower(), 'label': r, 'value': 'gpt-4o', 'custom': False} for r in roles],
                'options': [], 'gateway_ok': False, 'gateway': {'base_url': 'https://openrouter.ai/api/v1'}}

    def save_models(self, picks):
        self.saved = picks
        return 'saved'

    def review_form(self, posting_id):
        return {'employer': 'Acme Analytics', 'role': 'Senior Data Analyst', 'rows': [
            ('Employer', 'Acme Analytics', 'form'), ('Role', 'Senior Data Analyst', 'posting 42'),
            ('Full name', '[Full name]', 'profile'), ('Why this role', '[3 lines typed into the form]', 'drafted by agent'),
            ('CV', 'cv-acme-senior-data-analyst.pdf', 'attached · p change'),
            ('Cover letter', 'cover-acme-senior-data-analyst.pdf', 'attached · p change')]}


_PNG = """
import sys
from playwright.sync_api import sync_playwright
svg = open(sys.argv[1]).read()
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1400, 'height': 800})
    pg.set_content('<body style="margin:0;background:#000">' + svg + '</body>')
    pg.screenshot(path=sys.argv[2], full_page=True); b.close()
"""


async def ashot(pilot, app, name):
    """Screenshots wait for a quiet screen: exporting mid-refresh can hit a half-built frame."""
    last = None
    for _ in range(10):
        await pilot.pause(0.3)
        try:
            shot(app, name)
            return
        except TypeError as exc:
            last = exc
    raise last


def shot(app, name):
    """Save the screen as SVG and, when playwright is available, as a PNG next to it."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    svg = app.export_screenshot()
    (SHOTS / f'{name}.svg').write_text(svg)
    import subprocess
    import sys
    try:
        subprocess.run([sys.executable, '-c', _PNG, str(SHOTS / f'{name}.svg'), str(SHOTS / f'{name}.png')],
                       check=False, timeout=60, capture_output=True)
    except Exception:  # noqa: BLE001 - screenshots are a visual aid, never a test failure
        pass

# the shape chat._chat_interactions produces
APPROVAL = {'type': 'approval', 'interaction_id': 'a-0', 'posting_id': 7, 'operation': 'submit_application',
            'binding': None, 'summary': 'Submit job 7'}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(tui, 'job_connection', lambda *a, **k: (_ for _ in ()).throw(OSError('no db')))
    calls = []

    def fake_dispatch(**kw):
        calls.append(kw)
        if kw.get('decisions'):
            return {'status': 'completed', 'answer': 'done [red]x[/red]', 'checkpoint_id': 'c2'}
        op = 'submit_application' if 'submit' in (kw.get('message') or '') else 'prepare_application'
        return {'status': 'interrupted', 'answer': 'needs you', 'checkpoint_id': 'c1',
                'interactions': [dict(APPROVAL, operation=op)]}

    monkeypatch.setattr(tui, 'dispatch', fake_dispatch)
    instance = tui.JobwatchTUI('default', backend=FakeBackend())
    instance.calls = calls
    return instance


async def _settle(pilot, app):
    for _ in range(40):
        await pilot.pause(0.1)
        if not app.busy:
            break
    await pilot.pause(0.2)


def test_pending_strip_keys_state_line_and_footer(app):
    async def run():
        async with app.run_test(size=(110, 30)) as pilot:
            app.query_one('#prompt').value = 'prepare job 7'
            await pilot.press('enter')
            await _settle(pilot, app)
            strip = app.query_one('#pending')
            assert strip.has_class('-on') and 'prepare_application' in str(strip.render())
            assert app.posting_id == 7
            assert 'job 7:' in str(app.query_one('#taskstate').render())
            assert 'cancel turn' in {b.description for b in app.BINDINGS}
            await pilot.press('a')
            await _settle(pilot, app)
            assert app.calls[-1]['decisions'] == [{'type': 'approve'}]
            assert app.calls[-1]['human_decision'] is True
            assert not app.query_one('#pending').has_class('-on')
    asyncio.run(run())


def test_reject_with_reason(app):
    async def run():
        async with app.run_test(size=(110, 30)) as pilot:
            app.query_one('#prompt').value = 'go'
            await pilot.press('enter')
            await _settle(pilot, app)
            await pilot.press('e')
            app.query_one('#prompt').value = 'wrong salary'
            await pilot.press('enter')
            await _settle(pilot, app)
            assert app.calls[-1]['decisions'] == [{'type': 'reject', 'message': 'wrong salary'}]
    asyncio.run(run())


def test_hidden_control_characters_are_stripped():
    assert tui._e('ok‮evil​[red]x\x1b') == 'okevil\\[red]x'


def test_submit_is_not_approved_from_the_main_board(app):
    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.query_one('#prompt').value = 'submit job 7'
            await pilot.press('enter')
            await _settle(pilot, app)
            assert 'enter' in str(app.query_one('#pending').render()) and 'a approve' not in str(app.query_one('#pending').render())
            n = len(app.calls)
            await pilot.press('a')                      # no a on a Submit
            await pilot.pause(0.3)
            assert len(app.calls) == n and app.pending
            app.query_one('#prompt').value = 'yes please'    # typing never approves: it is sent as an edit
            await pilot.press('enter')
            await _settle(pilot, app)
            assert app.calls[-1]['decisions'] == [{'type': 'reject', 'message': 'yes please'}]
    asyncio.run(run())


def test_main_board_wide_and_narrow(app):
    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.query_one('#prompt').value = 'Draft the Acme application.'
            await pilot.press('enter')
            await _settle(pilot, app)
            side = str(app.query_one('#sidebar').render())
            assert 'Acme Analytics' in side and '2 need you' in side and 'awaiting browser press' in side
            assert 'Watcher' in side
            await ashot(pilot, app, 'Main')
            await pilot.resize_terminal(80, 24)
            await pilot.pause(0.3)
            assert app.query_one('#sidebar').has_class('-hidden')
            assert 'draft ready' in str(app.query_one('#narrowfeed').render())
            await ashot(pilot, app, 'Narrow')
    asyncio.run(run())


def test_today_detail_and_review(app):
    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.pause(0.2)
            app.show_view('today')
            await pilot.pause(0.6)
            body = app.screen.plain_text
            assert 'Check and submit' in body and 'Junior Data Analyst' in body and '100%' in body
            await ashot(pilot, app, 'Today')
            await pilot.press('enter')                   # first needs-you item is Acme (draft ready)
            await pilot.pause(0.6)
            assert type(app.screen).__name__ == 'DetailScreen'
            await ashot(pilot, app, 'Detail')
            await pilot.press('escape')
            await pilot.press('escape')
            await pilot.pause(0.2)
            assert type(app.screen).__name__ != 'TodayScreen'
    asyncio.run(run())


def test_submit_only_from_review(app):
    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.query_one('#prompt').value = 'submit job 7'
            await pilot.press('enter')
            await _settle(pilot, app)
            n = len(app.calls)
            await pilot.press('enter')                   # empty prompt + Submit waiting: opens the review
            await pilot.pause(0.6)
            assert type(app.screen).__name__ == 'ReviewScreen'
            assert len(app.calls) == n                   # opening it sent nothing
            await ashot(pilot, app, 'Review')
            await pilot.press('a')
            await _settle(pilot, app)
            assert app.calls[-1]['decisions'] == [{'type': 'approve'}] and app.calls[-1]['human_decision'] is True
            assert type(app.screen).__name__ != 'ReviewScreen'
    asyncio.run(run())


def test_review_escape_sends_nothing(app):
    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.query_one('#prompt').value = 'submit job 7'
            await pilot.press('enter')
            await _settle(pilot, app)
            n = len(app.calls)
            await pilot.press('enter')
            await pilot.pause(0.4)
            await pilot.press('escape')
            await pilot.pause(0.3)
            assert len(app.calls) == n and app.pending
    asyncio.run(run())


def test_file_picker_chip_upload_and_size_limit(app, tmp_path, monkeypatch):
    home = tmp_path / 'home'
    (home / 'jobwatch' / 'drafts').mkdir(parents=True)
    (home / 'jobwatch' / 'cv-master.pdf').write_bytes(b'%PDF-1.4 small')
    (home / 'jobwatch' / 'cv-big.pdf').write_bytes(b'0' * (10 * 1024 * 1024 + 1))
    (home / 'notes.txt').write_text('hello')
    monkeypatch.setenv('HOME', str(home))
    uploads = []

    class Up(FakeBackend):
        def upload(self, path, kind):
            uploads.append((path.name, kind))
            return {'upload_id': 'u1'}
    app.backend = Up()

    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.press('@')                       # opens the picker, nothing is typed into the prompt
            await pilot.pause(0.4)
            assert type(app.screen).__name__ == 'FilePicker' and app.query_one('#prompt').value == ''
            for ch in 'cvbig':
                await pilot.press(ch)
            await pilot.press('enter')                   # too large: refused, picker stays
            await pilot.pause(0.3)
            assert type(app.screen).__name__ == 'FilePicker' and 'too large' in app.screen.message
            await ashot(pilot, app, 'FilePicker')
            for _ in range(3):
                await pilot.press('backspace')
            for ch in 'master':
                await pilot.press(ch)
            await pilot.press('enter')
            await pilot.pause(0.4)
            assert type(app.screen).__name__ != 'FilePicker' and len(app.attachments) == 1
            app.query_one('#prompt').value = 'read my CV'
            await pilot.press('enter')
            await _settle(pilot, app)
            assert uploads == [('cv-master.pdf', 'cv')]
            assert app.calls[0]['upload_ids'] == ['u1'] and not app.attachments
    asyncio.run(run())


def test_slash_boards_render(app):
    boards = [('applications', 'Applications', ['Fill the form (f)', 'Operations Analyst', 'CLOSED']),
              ('inbox', 'Inbox', ['Reporting Analyst', 'Approve (a)', '90% sure']),
              ('table', 'Table', ['All jobs', 'Download CSV (x)', 'Junior Data Analyst']),
              ('sources', 'Sources', ['Employers watched', 'Deloitte Australia', 'checked 2026-10-06']),
              ('insights', 'Insights', ['Postings seen', 'Callback rate', 'ICT data (backup)']),
              ('models', 'Models', ['Writes CV + letter', 'Save models (s)', 'Could not load the model list'])]

    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            for command, shot_name, expect in boards:
                app.query_one('#prompt').value = '/' + command
                await pilot.press('enter')
                await pilot.pause(0.7)
                text = app.screen.plain_text
                for item in expect:
                    assert item in text, (command, item)
                await ashot(pilot, app, shot_name)
                await pilot.press('escape')
                await pilot.pause(0.2)
                assert type(app.screen).__name__ not in ('ApplicationsScreen', 'InboxScreen')
    asyncio.run(run())


def test_inbox_decision_and_models_edit(app):
    backend = app.backend

    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.show_view('inbox')
            await pilot.pause(0.7)
            await pilot.press('a')
            await pilot.pause(0.5)
            assert backend.decided == (1, 'approve')
            app.show_view('models')
            await pilot.pause(0.7)
            await pilot.press('down', 'down', 'enter')
            await pilot.pause(0.3)
            app.screen.query_one('#modelinput').value = 'gpt-5'
            await pilot.press('enter')
            await pilot.pause(0.3)
            assert 'Your pick (unsaved)' in app.screen.plain_text
            await pilot.press('s')
            await pilot.pause(0.4)
            assert backend.saved == {'writer'.replace('writer', 'writes'): 'gpt-5'} or list(backend.saved.values()) == ['gpt-5']
    asyncio.run(run())


def test_table_sort_and_filter_keys(app):
    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.show_view('table')
            await pilot.pause(0.7)
            await pilot.press('s')
            await pilot.pause(0.5)
            assert app.backend.table_params['sort'] == 'new'
            await pilot.press('/')
            for ch in 'sql':
                await pilot.press(ch)
            await pilot.press('enter')
            await pilot.pause(0.5)
            assert app.backend.table_params['q'] == 'sql'
    asyncio.run(run())


def test_state_empty_feed(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(tui, 'job_connection', lambda *a, **k: (_ for _ in ()).throw(OSError('no db')))
    instance = tui.JobwatchTUI('default', backend=FakeBackend(rows=[]))

    async def run():
        async with instance.run_test(size=(120, 34)) as pilot:
            await pilot.pause(0.4)
            assert any('Nothing in the queue yet' in str(e[1]) for e in instance.entries)
            assert any('/run' in str(e[1]) for e in instance.entries)
            await ashot(pilot, instance, 'States-empty')
    asyncio.run(run())


def test_state_failed_step_and_retry_keys(app, monkeypatch):
    def failing(**kw):
        app.calls.append(kw)
        if len(app.calls) == 1:
            kw['execution'].emit('tool_started', {'tool': 'prepare_application'})
            kw['execution'].emit('tool_finished', {'tool': 'prepare_application', 'error': 'timeout after 30s on acme.example/careers'})
            return {'status': 'completed', 'answer': '', 'checkpoint_id': 'c1'}
        return {'status': 'completed', 'answer': 'retrying', 'checkpoint_id': 'c2'}
    monkeypatch.setattr(tui, 'dispatch', failing)

    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.posting_id = 42
            app.query_one('#prompt').value = 'prepare job 42'
            await pilot.press('enter')
            await _settle(pilot, app)
            text = ' '.join(str(e[1]) for e in app.entries if e[0] == 'raw')
            assert 'failed' in text and 'Nothing was submitted' in text and 'timeout after 30s' in text
            await ashot(pilot, app, 'States-failed')
            await pilot.press('r')
            await _settle(pilot, app)
            assert 'Retry the step prepare_application' in app.calls[-1]['message']
    asyncio.run(run())


def test_state_working_shows_step_and_cancel_hint(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(tui, 'job_connection', lambda *a, **k: (_ for _ in ()).throw(OSError('no db')))
    gate = threading.Event()

    def slow(**kw):
        kw['execution'].emit('tool_started', {'tool': 'prepare_application'})
        gate.wait(5)
        return {'status': 'completed', 'answer': 'done', 'checkpoint_id': 'c1'}
    monkeypatch.setattr(tui, 'dispatch', slow)
    instance = tui.JobwatchTUI('default', backend=FakeBackend())

    async def run():
        async with instance.run_test(size=(120, 34)) as pilot:
            instance.query_one('#prompt').value = 'draft the Globex letter'
            await pilot.press('enter')
            await pilot.pause(0.6)
            assert instance.busy and instance.query_one('#working').has_class('-on')
            assert 'prepare_application' in instance.current_tool
            assert 'Working. Typing queues a reply' in str(instance.query_one('#hint').render())
            await ashot(pilot, instance, 'States-working')
            gate.set()
            await _settle(pilot, instance)
            assert not instance.query_one('#working').has_class('-on')
    asyncio.run(run())


def test_state_outcome_unknown_line(app, monkeypatch):
    from contextlib import contextmanager
    from pipeline.agentic import task_state

    @contextmanager
    def fake_conn(*a, **k):
        yield object()
    monkeypatch.setattr(tui, 'job_connection', fake_conn)
    monkeypatch.setattr(task_state, 'task_card', lambda conn, pid: {'state': 'outcome unknown'})

    async def run():
        async with app.run_test(size=(120, 34)) as pilot:
            app.query_one('#prompt').value = '/job 44'
            await pilot.press('enter')
            await pilot.pause(0.3)
            line = str(app.query_one('#taskstate').render())
            assert 'outcome unknown' in line and 'retries are paused' in line and 'Nothing will resend' in line
            await ashot(pilot, app, 'States-unknown')
    asyncio.run(run())
