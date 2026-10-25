"""/welcome: upload a CV, build the person's profile and their own search config (TASK-111 child 3)."""
from fastapi import Request

from jobwatch import fieldgen, onboarding, users
from jobwatch.candidate.intake import extract_text  # noqa: F401  (moved; re-exported for this route)

# (field name, label, hint, needed)
KINDS = (("cv", "Your CV", "PDF, DOCX or text.", True),
         ("letter", "Cover letters", "Ones you wrote. They teach your style.", False),
         ("evidence", "Evidence", "Projects, diplomas, course lists, certificates.", False))


def register(app, config, conn_, render):
    @app.get("/welcome")
    def welcome(request: Request):
        return render(request, "welcome.html", None, stage="form", kinds=KINDS)

    @app.post("/welcome/cv")
    async def welcome_cv(request: Request):
        form = await request.form()
        try:
            docs = []
            for kind, *_ in KINDS:
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
            return render(request, "welcome.html", None, status=400, stage="form", kinds=KINDS, error=str(exc))
        summary = (f"Profile built for {profile['candidate'].get('name') or user}. "
                   f"Your searches now use {len(profile['target_titles'])} job titles. "
                   f"Saved {sum(1 for d in docs if d[0] == 'letter')} letter sample(s) and "
                   f"{len(profile['certifications']) + len(profile['actionable_evidence'])} evidence item(s).")
        return render(request, "welcome.html", None, stage="done", kinds=KINDS, summary=summary, questions=questions)
