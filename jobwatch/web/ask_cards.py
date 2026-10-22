"""Friendly question cards for the owner's saved form answers (owner 2026-10-19: "should be based on profile ... agent
should ask it over the chat ... like AskUserQuestion ... not robotic"). Answers still live in answers.yaml.

Never asked: how you heard about a job and whether you worked for the employer before. Those are worked out per job
from the posting and the resume (jobwatch.apply.jev_forms.job_answers). Also skipped: anything that does not apply
(visa details for a citizen, a WWCC number without a WWCC).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from jobwatch.apply import paths
from . import answers_routes as ar

DERIVED = {"background.previously_worked_for_employer", "misc.how_did_you_hear"}
YN = [("Yes", "yes"), ("No", "no")]
# key -> (question, options [(label, saved value)]); no options = just the free-text box
Q = {
    "australian_citizen_or_pr": ("Are you an Australian citizen or permanent resident?", YN),
    "visa_type": ("Which visa are you on?", []),
    "visa_expiry": ("When does your visa expire? (like 2028-03-15)", []),
    "work_hour_limit": ("What is your work-hour limit?", [("No limit", "none")]),
    "notice_period": ("How soon could you start after an offer?", [("Straight away", "immediate"), ("In 2 weeks", "2 weeks"), ("In a month", "4 weeks")]),
    "earliest_start_date": ("What is the earliest day you could start? (like 2026-11-02)", [("As soon as possible", "immediately")]),
    "hours_wanted": ("What hours do you want?", [("Part-time", "part-time"), ("Casual", "casual"), ("Full-time", "full-time"), ("Any", "any")]),
    "days_or_times_available": ("Which days or times are you free?", [("Any day", "everyday"), ("Weekdays", "weekdays"), ("Weekends", "weekends")]),
    "willing_to_relocate_in_victoria": ("Would you move within {region} for a job?", YN),
    "expected_annual_aud": ("What yearly pay do you expect?", [("Award rate", "award"), ("Negotiable", "negotiable")]),
    "expected_hourly_aud": ("What hourly pay do you expect for casual work?", [("Award rate", "award"), ("Negotiable", "negotiable")]),
    "national_police_check": ("Do you have a current police check?", [("Yes, I have one", "have current"), ("No, but I would get one", "willing to get"), ("No", "no")]),
    "working_with_children_check": ("Do you have a Working with Children Check?", [("Yes, I have one", "have"), ("No, but I would get one", "willing to get"), ("No", "no")]),
    "wwcc_number": ("What is your Working with Children Check number?", []),
    "ndis_worker_screening": ("Do you have an NDIS worker screening clearance?", [("Yes, I have one", "have"), ("No, but I would get one", "willing to get"), ("No", "no")]),
    "criminal_convictions_to_declare": ("Is there any criminal conviction you would need to declare?", YN),
    "drivers_licence": ("What driver's licence do you hold?", [("Full licence", "full"), ("Provisional", "provisional"), ("Learner", "learner"), ("None", "none")]),
    "own_car": ("Do you have your own car?", YN),
    "highest_qualification": ("What is your highest qualification, as forms should show it?", []),
    "currently_studying": ("Are you studying right now?", [("No", "no")]),
    "related_to_employee_or_conflict": ("Are you related to anyone at the employer, or any conflict of interest?", YN),
    "gender": ("How should forms show your gender?", [("Nonbinary", "Nonbinary"), ("Female", "Female"), ("Male", "Male"), ("Prefer not to say", "prefer not to say")]),
    "aboriginal_or_torres_strait_islander": ("Are you Aboriginal or Torres Strait Islander?", [("No", "no"), ("Yes", "yes"), ("Prefer not to say", "prefer not to say")]),
    "disability_or_adjustments": ("Do you have a disability or need adjustments?", [("No", "no"), ("Yes", "yes"), ("Prefer not to say", "prefer not to say")]),
    "culturally_linguistically_diverse": ("What cultural or language background should forms show?", [("Prefer not to say", "prefer not to say")]),
    "linkedin_on_forms": ("Should I put your LinkedIn on forms?", YN),
}
REF = {"name": "Who could be a referee? Their full name.", "role": "What is {n}'s job title?",
       "relationship": "How do you know {n}? (like your manager at your last job)", "phone": "What is {n}'s phone number?",
       "email": "What is {n}'s email address?"}


def _region() -> str:
    """State or region from candidate.location (text after the first comma, or the whole text); else "your state"."""
    from jobwatch.apply.render import _candidate
    loc = _candidate().get("location")
    loc = (loc.get("state") or loc.get("region") or loc.get("city") or "") if isinstance(loc, dict) else str(loc or "")
    parts = [x.strip() for x in loc.split(",") if x.strip()]
    return (parts[1] if len(parts) > 1 else parts[0]) if parts else "your state"


def _personal(key: str, question: str, options: list) -> tuple[str, list]:
    """Fill the person's own values from profile.yaml candidate; generic when it has none."""
    from jobwatch.apply.render import _candidate
    cand = _candidate()
    question = question.replace("{region}", _region())
    rights = cand.get("work_rights") or {}
    rights = rights if isinstance(rights, dict) else {}
    if key == "visa_type":
        options = [("Citizen", "Australian citizen"), ("Permanent resident", "Permanent resident"),
                   ("Temporary visa with work rights", "Temporary visa with work rights"), ("Other", "other")]
        if rights.get("visa"):
            options = [(str(rights["visa"]), str(rights["visa"]))] + options
    elif key == "work_hour_limit" and rights.get("work_conditions"):
        options = [(str(rights["work_conditions"]), str(rights["work_conditions"]))] + options
    elif key == "currently_studying":
        edu = cand.get("education") or []
        first = edu[0] if isinstance(edu, list) and edu else edu
        if isinstance(first, dict):
            first = ", ".join(str(first[k]) for k in ("degree", "institution", "school") if first.get(k))
        if first and isinstance(first, str):
            options = [(f"Yes, {first}", f"yes, {first}")] + options
        else:
            options = [("Yes", "yes")] + options
    return question, options


def _applies(f, values) -> bool:
    if f["id"] in DERIVED:
        return False
    if f["id"] in ("work_rights.visa_type", "work_rights.visa_expiry", "work_rights.work_hour_limit"):
        return values.get("work_rights.australian_citizen_or_pr", "").lower() not in ("yes", "y")
    if f["id"] == "checks.wwcc_number":
        return values.get("checks.working_with_children_check", "").lower() == "have"
    if f["id"].startswith("referees.") and not f["id"].endswith(".name"):
        return bool(values.get(re.sub(r"\.\w+$", ".name", f["id"])))   # no details for a referee with no name
    return True


def load():
    fields, _ = ar.parse(ar._path().read_text())
    return fields, {f["id"]: f["value"] for f in fields}


def todo(skip=()) -> list[dict]:
    fields, values = load()
    return [f for f in fields if not f["value"] and _applies(f, values) and f["id"] not in skip]


def card(skip=(), verify=False, change=None):
    """The next question as {id, question, options, current, verify}, or None when nothing is left."""
    fields, values = load()
    pool = [f for f in fields if f["id"] == change] or sorted(
        (f for f in fields if _applies(f, values) and f["id"] not in skip and (not f["value"] or verify)),
        key=lambda f: bool(f["value"]))      # missing first, then ones to verify
    if not pool:
        return None
    f = pool[0]
    key = f["id"].split(".")[-1]
    if f["id"].startswith("referees."):
        ref = int(f["id"].split(".")[1])
        name = values.get(f"referees.{ref}.name") or f"referee {ref}"
        question = REF[key].format(n=name) + ("" if ref == 1 else " (second referee)" if key == "name" else "")
        options = []
    else:
        question, options = _personal(key, *Q.get(key, (f["label"] + "?", [])))
    is_verify = bool(f["value"]) and f["id"] != change
    if is_verify:
        question = f"I have “{f['value']}” for this: {question[0].lower() + question[1:]} Still right?"
    return {"id": f["id"], "question": question, "options": options, "current": f["value"], "verify": is_verify,
            "left": len(todo(skip)), "total": len(fields)}


def _backup(path: Path):
    global _done
    if _done == str(path):
        return
    d = Path(os.environ.get("JOBWATCH_BACKUP_DIR") or Path.home() / "backups" / "jobwatch")
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, d / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}")
    for old in sorted(d.glob(f"{path.name}.*"))[:-3]:
        old.unlink()
    _done = str(path)


_done = ""


def save_answer(field_id: str, value: str) -> None:
    value = " ".join(value.split())
    if not value:
        return
    p = ar._path()
    _backup(p)
    new = ar.save(p.read_text(), {field_id: value})
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".answers-")
    with os.fdopen(fd, "w") as fh:
        fh.write(new)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def notify_missing() -> int:
    """Tell the person once per change in the number of waiting questions. Returns how many are waiting."""
    n = len(todo())
    flag = paths.data_dir() / "ask_cards_notified"
    last = flag.read_text().strip() if flag.exists() else ""
    if n and last != str(n) and not os.environ.get("PYTEST_CURRENT_TEST"):
        from jobwatch.settings import get as _setting
        cmd = _setting("JOBWATCH_NOTIFY_CMD")  # e.g. "notify-owner jobwatch"; unset = no notification
        if cmd:
            board = _setting("JOBWATCH_BOARD_URL", "http://127.0.0.1:8960").rstrip("/")
            subprocess.run(cmd.split() + [f"Jobwatch has {n} quick questions for you: {board}/chat"], check=False, timeout=60)
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        flag.write_text(str(n))
    return n
