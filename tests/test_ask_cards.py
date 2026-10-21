"""Question cards: a click saves the answer into answers.yaml; job-specific answers are worked out, not asked."""
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from jobwatch.apply import jev_forms
from jobwatch.web import ask_cards

SRC = Path.home() / "brain/data/jobwatch/profile"
ANSWERS = '''version: 1
availability:
  earliest_start_date: ""  # YYYY-MM-DD
  hours_wanted: "casual"
misc:
  how_did_you_hear: ""
'''


def test_card_click_saves_and_job_answers_are_derived(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_BACKUP_DIR", str(tmp_path / "bk"))
    (tmp_path / "answers.yaml").write_text(ANSWERS)
    c = ask_cards.card()
    assert c["id"] == "availability.earliest_start_date"          # how_did_you_hear is never asked
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from jobwatch.web import chat_routes
    app = FastAPI()
    chat_routes.register(app, None, lambda: None, lambda *a, **k: PlainTextResponse(""))
    r = TestClient(app).post("/chat/ask", data={"field": c["id"], "choice": "0"}, follow_redirects=False)
    assert r.status_code == 303 and 'earliest_start_date: "immediately"  # YYYY-MM-DD' in (tmp_path / "answers.yaml").read_text()
    assert len(list((tmp_path / "bk").glob("answers.yaml.*"))) == 1
    (tmp_path / "master_resume.md").write_text("## Professional experience\n### Tax Assistant, Northside Tax Services\n## Education\n")
    if True:
        got = jev_forms.job_answers(tmp_path, {"company": "Northside Tax Services Pty Ltd", "source": "ats_greenhouse", "url": "https://x.com/j"})
        assert got["background.previously_worked_for_employer"][1] == "yes"
        assert got["misc.how_did_you_hear"][1] == "Employer careers site"
        assert jev_forms.job_answers(tmp_path, {"company": "Acme", "url": "https://www.seek.com.au/job/1"})["background.previously_worked_for_employer"][1] == "no"
