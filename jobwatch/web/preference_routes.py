"""Owner-only explicit preference choices through the board's existing origin guard."""
import uuid
import sqlite3
from fastapi import Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from jobwatch import users
from jobwatch import preference_service as service
from jobwatch.preferences import PreferenceStore, PreferenceError, predict_set
from pipeline.agentic import discovery_settings


def register(app, config, conn_factory, render):
    def render_preferences(request, conn, *, token_mode=None, token_value=None, token_error='', status=200):
        store = PreferenceStore(conn)
        error = ''
        try:
            identity, alternatives = service.pool(conn, config)
            state = store.status(identity)
            current = {a['posting_id']: a for a in alternatives}
            sets = store.list_sets(identity)
            for item in sets:
                item['current'] = all(current.get(a['posting_id']) == a for a in item['alternatives'])
                item['request_id'] = uuid.uuid4().hex
                item['prediction'] = None
                if item['answered'] and item['current'] and state['status'] == 'valid':
                    item['prediction'] = predict_set(store, item['alternatives'], identity)
        except (ValueError, OSError, sqlite3.DatabaseError):
            state, sets = store.status(), []
            error = 'Current profile or evaluated jobs are unavailable. Choices are paused.'

        settings_error = ''
        try:
            settings = discovery_settings.get_settings(users.current(), config)
            ceiling = settings['daily_token_ceiling']
        except (ValueError, OSError, sqlite3.DatabaseError):
            ceiling = None
            settings_error = 'The saved daily allowance could not be read. Choose a replacement below.'
        if token_mode not in ('limited', 'unlimited'):
            token_mode = '' if settings_error else 'unlimited' if ceiling is None else 'limited'
        if token_value is None:
            token_value = '' if ceiling is None or settings_error else str(ceiling)
        return render(request, 'preferences.html', conn, status=status,
                      preference_state=state, choices=sets, preference_error=error,
                      daily_token_ceiling=ceiling, token_mode=token_mode,
                      token_value=token_value, token_error=token_error,
                      token_settings_error=settings_error)

    @app.get('/preferences')
    def preferences(request: Request):
        conn = conn_factory()
        try:
            return render_preferences(request, conn)
        finally:
            conn.close()

    @app.post('/preferences/discovery-settings')
    def save_discovery_settings(request: Request, mode: str = Form(''), daily_token_ceiling: str = Form('')):
        conn = conn_factory()
        try:
            ceiling = None
            token_error = ''
            if mode == 'limited':
                value = daily_token_ceiling.strip()
                if (not value or not value.isascii() or not value.isdecimal() or len(value) > 100
                        or int(value) < 1):
                    token_error = 'Enter a positive whole-number daily token limit, or choose Unlimited.'
                else:
                    ceiling = int(value)
            elif mode != 'unlimited':
                token_error = 'Choose Unlimited or Limited for the daily token allowance.'

            if token_error:
                return render_preferences(request, conn, token_mode=mode,
                    token_value='', token_error=token_error, status=400)

            discovery_settings.set_settings(users.current(), config, ceiling)
        except (ValueError, OSError, sqlite3.DatabaseError):
            return PlainTextResponse('The daily token allowance could not be saved.', status_code=400)
        finally:
            conn.close()
        return RedirectResponse('/preferences', status_code=303)

    @app.post('/preferences/new')
    def new_set():
        conn = conn_factory()
        try:
            service.create_next(conn, config)
        except (ValueError, OSError, sqlite3.DatabaseError):
            return PlainTextResponse('Three new, current eligible job evaluations are required.', status_code=409)
        finally:
            conn.close()
        return RedirectResponse('/preferences', status_code=303)

    @app.post('/preferences/{set_id}/pick')
    def pick(set_id: str, selected: str = Form(...), request_id: str = Form(...)):
        conn = conn_factory()
        try:
            choice = None if selected == 'none' else int(selected)
            service.record_pick(conn, config, set_id, choice, request_id)
        except (ValueError, OSError, sqlite3.DatabaseError):
            return PlainTextResponse('Choice was not saved: it is invalid, already answered, or no longer current.', status_code=409)
        finally:
            conn.close()
        return RedirectResponse('/preferences', status_code=303)
