"""/welcome: upload a CV, build the person's profile and their own search config (TASK-111 child 3)."""
import html
import io

from fastapi import Request
from fastapi.responses import HTMLResponse

from jobwatch import fieldgen, onboarding, users

_PAGE = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
         "<title>Welcome</title><body style='font:16px system-ui;max-width:36rem;margin:2rem auto;padding:0 1rem'>"
         "<h1>Welcome</h1>{body}</body>")


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("PDF reading is not installed on this server. Please upload a .txt or .docx file.")
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    if name.endswith(".docx"):
        try:
            import docx
        except ImportError:
            raise ValueError("DOCX reading is not installed on this server. Please upload a .txt file.")
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    return data.decode("utf-8", errors="replace")


KINDS = (("cv", "Your CV"), ("letter", "Cover letters you have written (your own style samples)"),
         ("evidence", "Supporting evidence: project lists, diplomas, course lists, certificates"))


def register(app, config, conn_, render):
    @app.get("/welcome")
    def welcome(request: Request):
        rows = "".join(f"<p><b>{label}</b><br><input type=file name={k} multiple{' required' if k == 'cv' else ''}></p>"
                       for k, label in KINDS)
        body = ("<p>Upload your documents (PDF, DOCX or text). We build your profile, your evidence and your own "
                "job searches from them. Your files stay in your own folder and are never shown to anyone else.</p>"
                f"<form method=post action=/welcome/cv enctype=multipart/form-data>{rows}"
                "<button>Build my profile</button></form>")
        return HTMLResponse(_PAGE.format(body=body))

    @app.post("/welcome/cv")
    async def welcome_cv(request: Request):
        form = await request.form()
        try:
            docs = []
            for kind, _ in KINDS:
                for up in form.getlist(kind):
                    if not getattr(up, "filename", ""):
                        continue
                    text = extract_text(up.filename, await up.read()).strip()
                    if len(text) < (50 if kind == "cv" else 5):
                        raise ValueError(f"Could not read any text from {up.filename}.")
                    docs.append((kind, up.filename, text))
            user = users.current()
            profile, questions = onboarding.wrangle(docs, user)
            fieldgen.generate_config(profile, user)
        except Exception as exc:
            return HTMLResponse(_PAGE.format(body=f"<p>Could not build your profile: {html.escape(str(exc))}</p>"
                                                  "<p><a href=/welcome>Try again</a></p>"), status_code=400)
        qs = "".join(f"<li>{html.escape(q)}</li>" for q in questions) or "<li>None, the CV covered it.</li>"
        body = (f"<p>Profile built for {html.escape(str(profile['candidate'].get('name') or user))}. "
                f"Your searches now use {len(profile['target_titles'])} job titles. "
                f"Saved {sum(1 for d in docs if d[0] == 'letter')} letter sample(s) and "
                f"{len(profile['certifications']) + len(profile['actionable_evidence'])} evidence item(s).</p>"
                f"<h2>A few things the CV did not say</h2><ul>{qs}</ul>")
        return HTMLResponse(_PAGE.format(body=body))
