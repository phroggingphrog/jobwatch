"""The owner's own voice and letter form for the drafter (form only; facts still come from cited evidence).

Sources, all owner-approved on 2026-10-05 (GENERATOR-CONTRACT.md in the career record):
- templates/cl_<id>.yaml: the letter's paragraph plan, word counts and opening/closing rules;
- style/owner_consult_cl_2026.yaml: the owner's own letter form and the weaknesses to avoid;
- career_master.yaml voice_dna and reusable cover_letter_blocks: tone, rules, banned phrases, own past phrasing;
- data/anti_slop.md: career-ops' anti-AI-slop list (MIT).
Missing files give a smaller guide, never an error: the writer still works from evidence alone.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from jobwatch.apply import paths

_HERE = Path(__file__).resolve().parent
_USABLE_BLOCKS = {"reusable", "needs_tense_update"}
_DOMAINS = (("data", "data_analytics"), ("analyt", "data_analytics"), ("report", "data_analytics"),
            ("accounts", "accounts_admin"), ("bookkeep", "accounts_admin"), ("payable", "accounts_admin"),
            ("receivable", "accounts_admin"), ("admin", "accounts_admin"), ("payroll", "accounts_admin"))


def career_dir() -> Path:
    env = os.environ.get("JOBWATCH_CAREER_DIR")
    return Path(os.path.expanduser(env)) if env else paths.data_dir().parent / "career"


def domain_for(title: str, archetype: str) -> str:
    text = f"{title} {archetype}".lower()
    return next((domain for word, domain in _DOMAINS if word in text), "general")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def writing_guide(cl_template: str, title: str, archetype: str, cv_template_id: str = "") -> dict:
    root = career_dir()
    guide: dict = {"how_to_use": (
        "Form and voice only. Facts still come only from cited candidate evidence and the ad. "
        "Follow letter_approach; write in the person's own voice; reuse their own phrasing where it fits "
        "(past tense, current titles); anti_slop applies to the CV and to claims about the candidate. In the letter, "
        "warm, eager, admiring words about the employer and the job are wanted (owner 2026-10-20: 'should be "
        "enthusiasm vibes voices style'); never let anti_slop flatten that.")}
    # No fixed letter template (owner 2026-10-20: "not hard coded template thats why its AI INTEGRATED").
    # The writer reasons out the structure for each job; real human letters from the person's own folder
    # give the feel ("IT SHOULD NOT READ LIKE A ROBOT ... THATS WHY I GAVE MY FRIENDS ... AND THE CONSULTATION").
    guide["letter_approach"] = (
        "1. Read employer_research (already gathered; search more with research_employer if it is thin). Use two or three real details about the company and say warmly why they make the candidate want to work there: eager, admiring, a little flattering, never flat. "
        "2. Write like the human_examples: who the candidate is, what draws them to this work, two or three true "
        "things they have done, told as a short story in plain words. Not mechanical or technical (owner 2026-10-20): "
        "no lists of courses, tools, software or skills, at most one named in passing; no jargon from the ad; "
        "say what the person did and what they enjoyed, like talking to someone. "
        "3. Mention a gap only if the ad lists it as essential, in one plain sentence; work rights or hours only if "
        "the ad asks, in one sentence. "
        "4. Close with one eager, warm sentence about joining this team and this role's real work.")
    examples = {p.stem: _read(p) for p in sorted((root / "style" / "examples").glob("*.md"))}
    if examples:
        guide["human_examples"] = {"how_to_use": "Feel, rhythm and plain-spoken voice only. Never copy their facts "
                                                 "or sentences; facts come only from the candidate's evidence.", **examples}
    try:
        master = yaml.safe_load(_read(root / "career_master.yaml")) or {}
    except yaml.YAMLError:
        master = {}
    voice = master.get("voice_dna") or {}
    if voice:
        guide["voice"] = {k: voice[k] for k in ("tone", "writing_rules", "banned_phrases") if k in voice}
    blocks = [b.get("text") for b in master.get("cover_letter_blocks") or []
              if b.get("use") in _USABLE_BLOCKS and b.get("text")]
    if blocks:
        guide["own_phrasing"] = blocks
    cv_template = _read(root / "templates" / f"{cv_template_id}.yaml") if cv_template_id else ""
    if cv_template:
        guide["cv_template"] = cv_template
    cv_guide = _read(_HERE / "data" / "cv_guide.md")
    if cv_guide:
        guide["cv_guide"] = cv_guide
    slop = _read(_HERE / "data" / "anti_slop.md")
    if slop:
        guide["anti_slop"] = slop
    return guide
