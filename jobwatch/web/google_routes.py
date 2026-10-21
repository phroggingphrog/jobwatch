"""Connect Google (per person). Mounted by app.py: google_routes.register(app, config, conn_, render)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import google_oauth, users

NEEDS = "needs the Google client ID in .env (see SETUP.md)"


def register(app, config, conn_, render):
    def page(msg: str, status: int = 200):
        return HTMLResponse(f'<!doctype html><meta name="viewport" content="width=device-width">'
                            f'<title>Connect Google</title><main style="font:16px sans-serif;max-width:32rem;'
                            f'margin:2rem auto;padding:0 1rem"><h1>Connect Google</h1><p>{msg}</p>'
                            f'<p><a href="/">Back to Jobwatch</a></p></main>', status_code=status)

    @app.get("/connect/google")
    def connect(request: Request):
        if not google_oauth.configured():
            return page(NEEDS)
        data = google_oauth.load()
        if data and data.get("email") and request.query_params.get("again") != "1":
            return page(f'Connected as {data["email"]}. '
                        f'<form method="post" action="/connect/google/disconnect" style="display:inline">'
                        f'<button>Disconnect</button></form> <a href="/connect/google?again=1">Reconnect</a>')
        return RedirectResponse(google_oauth.build_consent_url(google_oauth.make_state()), status_code=303)

    @app.get("/connect/google/callback")
    def callback(request: Request):
        if not google_oauth.configured():
            return page(NEEDS)
        p = request.query_params
        if p.get("error") or not p.get("code"):
            return page("Google did not give access. Nothing was saved.", 400)
        try:
            who = google_oauth.check_state(p.get("state", ""))
        except ValueError:
            return page("That sign-in link is invalid or expired. Start again from Connect Google.", 400)
        if who != users.current():
            return page("That sign-in link was started by someone else.", 403)
        try:
            data = google_oauth.exchange_code(p["code"])
        except Exception as exc:
            return page(f"Google refused the code ({type(exc).__name__}). Nothing was saved.", 502)
        return page(f'Connected as {data.get("email") or "your Google account"}.')

    @app.post("/connect/google/disconnect")
    def disconnect():
        google_oauth.disconnect()
        return RedirectResponse("/connect/google", status_code=303)
