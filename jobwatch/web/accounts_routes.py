"""Connect accounts: the user signs in to Seek / LinkedIn / Indeed themselves, inside the streamed browser.

The app never sees a password. Typed keys go straight to the browser page; only cookie NAMES are read
(never values) from the persistent browser profile to show connected / not connected.
"""
import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

SESSION_ID = 'accounts'
# key: (label, login URL, cookie host suffix, cookie names that only exist when signed in)
SITES = {
    'seek': ('Seek', 'https://www.seek.com.au/oauth/login/', 'seek.com.au', {'sol_id'}),
    'linkedin': ('LinkedIn', 'https://www.linkedin.com/login', 'linkedin.com', {'li_at'}),
    'indeed': ('Indeed', 'https://secure.indeed.com/auth', 'indeed.com', {'PPID'}),
}


def profile_path(data_root):
    return Path(data_root) / 'browser' / 'sessions' / hashlib.sha256(SESSION_ID.encode()).hexdigest() / 'profile'


def connected_sites(data_root):
    """{site: bool}. Reads cookie names only, from a throwaway copy of the profile's cookie file."""
    result = {key: False for key in SITES}
    prof = profile_path(data_root)
    src = next((p for p in (prof / 'Default' / 'Network' / 'Cookies', prof / 'Default' / 'Cookies') if p.is_file()), None)
    if src is None:
        return result
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / 'c.db'
        shutil.copyfile(src, copy)
        try:
            rows = sqlite3.connect(f'file:{copy}?mode=ro', uri=True).execute(
                'select host_key, name, expires_utc from cookies').fetchall()
        except sqlite3.Error:
            return result
    now = (time.time() + 11644473600) * 1_000_000  # Chrome epoch, microseconds
    for host, name, expires in rows:
        for key, (_, _, suffix, names) in SITES.items():
            if name in names and host.lstrip('.').endswith(suffix) and (not expires or expires > now):
                result[key] = True
    return result


def register(app, config, conn_factory, render, sessions):
    def is_open():
        try:
            return sessions.status(SESSION_ID).get('state') == 'ready'
        except Exception:
            return False

    @app.get('/accounts')
    def accounts_page(request: Request):
        state = connected_sites(sessions._root())
        sites = [dict(key=k, label=v[0], connected=state[k]) for k, v in SITES.items()]
        return render(request, 'accounts.html', sites=sites, browser_open=is_open())

    @app.post('/accounts/{site}/connect')
    def accounts_connect(site: str):
        if site not in SITES:
            return RedirectResponse('/accounts', status_code=303)
        try:
            if is_open():
                sessions.close(SESSION_ID)
            sessions.open(SESSION_ID, SITES[site][1])
        except Exception:
            return RedirectResponse('/accounts?error=1', status_code=303)
        return RedirectResponse('/accounts', status_code=303)

    @app.post('/accounts/browser/action')
    async def accounts_action(request: Request):
        try:
            raw = await request.body()
            if len(raw) > 100_000:
                raise ValueError
            await run_in_threadpool(sessions.action, SESSION_ID, json.loads(raw))
            return JSONResponse({'ok': True})
        except Exception:
            return JSONResponse({'ok': False}, status_code=409)

    @app.get('/accounts/browser/stream')
    def accounts_stream():
        def frames():
            while is_open():
                try:
                    jpeg = sessions.snapshot(SESSION_ID)['jpeg']
                    yield (b'--jobwatchframe\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                           str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                    time.sleep(0.5)
                except Exception:
                    break
        return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=jobwatchframe',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    @app.post('/accounts/browser/close')
    def accounts_close():
        try:
            sessions.close(SESSION_ID)
        except Exception:
            pass
        return RedirectResponse('/accounts', status_code=303)
