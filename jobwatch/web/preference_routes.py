"""Owner-only explicit preference choices through the board's existing origin guard."""
import uuid
import sqlite3
from fastapi import Form, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
from jobwatch import preference_service as service
from jobwatch.preferences import PreferenceStore, PreferenceError, predict_set


def register(app, config, conn_factory, render):
    @app.get('/preferences')
    def preferences(request: Request):
        conn = conn_factory()
        try:
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
            return render(request, 'preferences.html', conn, preference_state=state, choices=sets,
                          preference_error=error)
        finally:
            conn.close()

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
