"""/models: each person picks the model for each job and brings their own gateway key."""
import time

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from jobwatch import model_choice as mc
from jobwatch import users

_CACHE: dict = {}          # (person, gateway url) -> (time, [model ids])
TTL = 300


def list_models(user: str) -> tuple[list[str], bool]:
    """Model ids from the person's gateway /models (cached 5 min). (ids, gateway_ok)."""
    url = mc.gateway_url(user)
    hit = _CACHE.get((user, url))
    if hit and time.time() - hit[0] < TTL:
        return hit[1], True
    try:
        import requests
        from jobwatch.llm import load_keys
        keys = load_keys()
        with requests.Session() as s:
            s.trust_env = False
            r = s.get(f"{url}/models", headers={"Authorization": f"Bearer {keys[0]}"} if keys else {},
                      timeout=8, allow_redirects=False)
        ids = sorted({m["id"] for m in r.json()["data"] if isinstance(m.get("id"), str)})
        if r.status_code != 200 or not ids:
            raise ValueError
    except Exception:
        return [], False
    _CACHE[(user, url)] = (time.time(), ids)
    return ids, True


def register(app, config, conn_factory, render):
    @app.get("/models")
    async def models_page(request: Request):
        user = users.current()
        ids, ok = await run_in_threadpool(list_models, user)
        picks = mc.chosen(user)
        rows = []
        for role, (label, _) in mc.ROLES.items():
            value = picks.get(role) or mc.get_model(role, user)
            rows.append({"role": role, "label": label, "value": value, "custom": role in picks,
                         "why": mc.refusal(value, role, user)})
        options = ids
        conn = conn_factory()
        try:
            return render(request, "models.html", conn, rows=rows, options=options, gateway_ok=ok,
                          gw=mc.gateway_view(user), 
                          error=request.query_params.get("error"), saved=request.query_params.get("saved"))
        finally:
            conn.close()

    @app.post("/models")
    async def models_save(request: Request):
        form = dict((await request.form()).items())
        user = users.current()
        try:
            mc.set_models({r: str(form.get(r, "")) for r in mc.ROLES if r in form}, user)
            if "base_url" in form:
                mc.set_gateway(str(form.get("base_url", "")), str(form.get("api_key", "")), user)
                _CACHE.clear()
        except (mc.ModelRefused, ValueError) as exc:
            return RedirectResponse("/models?error=" + str(exc).replace(" ", "+")[:200], status_code=303)
        return RedirectResponse("/models?saved=1", status_code=303)

    @app.post("/models/test")
    async def models_test(request: Request):
        """One tiny prompt to the model currently saved for this role."""
        role = str((await request.json()).get("role", ""))
        if role not in mc.ROLES:
            return JSONResponse({"ok": False, "error": "unknown job"}, status_code=400)
        user = users.current()
        model = mc.get_model(role, user)
        why = mc.refusal(model, role, user)
        if why:
            return JSONResponse({"ok": False, "error": why})

        def run():
            from jobwatch.llm import LLM
            return LLM().chat(model, [{"role": "user", "content": "reply OK"}], json_mode=False,
                              max_tokens=16, timeout=40).text

        try:
            text = await run_in_threadpool(run)
            return JSONResponse({"ok": True, "model": model, "text": (text or "").strip()[:40]})
        except Exception as exc:
            return JSONResponse({"ok": False, "model": model, "error": str(exc)[:160]})
