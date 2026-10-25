"""TUI behaviour with Textual's headless pilot; dispatch is replaced, no model is called."""
import asyncio

import pytest

pytest.importorskip('textual')

from pipeline.agentic import tui  # noqa: E402

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
        return {'status': 'interrupted', 'answer': 'needs you', 'checkpoint_id': 'c1', 'interactions': [APPROVAL]}

    monkeypatch.setattr(tui, 'dispatch', fake_dispatch)
    instance = tui.JobwatchTUI('default')
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
            assert strip.has_class('-on') and 'submit_application' in str(strip.render())
            assert app.posting_id == 7
            assert 'job 7:' in str(app.query_one('#taskstate').render())
            assert 'cancel turn' in {b.description for b in app.BINDINGS}
            app.save_screenshot('tui-phaseA.svg', path='/tmp/tui-shot')
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


def test_startup_screen_then_chat_with_sidebar(app):
    async def run():
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.pause(0.2)
            assert app.screen.has_class('-welcome')
            assert app.query_one('#transcript').display is False
            assert 'jobwatch' in str(app.query_one('#welcome').render()) or app.query_one('#welcome').display
            app.query_one('#prompt').value = 'prepare job 7'
            await pilot.press('enter')
            await _settle(pilot, app)
            assert not app.screen.has_class('-welcome')
            side = str(app.query_one('#sidebar').render())
            assert 'Needs you (1)' in side and 'submit_application' in side and 'job 7' in side
            assert app.query_one('#prompt').has_class('-working')
            await pilot.press('a')
            await _settle(pilot, app)
            side = str(app.query_one('#sidebar').render())
            assert 'Needs you (0)' in side and 'nothing waiting' in side
            assert not app.query_one('#prompt').has_class('-working')
    asyncio.run(run())


def test_sidebar_hides_on_narrow_terminals(app):
    async def run():
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.2)
            assert app.query_one('#sidebar').has_class('-hidden')
        async with tui.JobwatchTUI('default').run_test(size=(130, 30)) as pilot:
            await pilot.pause(0.2)
            assert not pilot.app.query_one('#sidebar').has_class('-hidden')
    asyncio.run(run())
