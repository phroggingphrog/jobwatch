import os
# Tests never read the machine's own install settings (~/.config/jobwatch/settings.env): same results on any computer.
os.environ["JOBWATCH_SETTINGS"] = os.devnull
# The runtime enforces paid combos at the configured loopback gateway. A test
# never inherits a real gateway or uses the generic external-provider default.
os.environ['JOBWATCH_LLM_BASE_URL'] = 'http://127.0.0.1:1/v1'
os.environ['JOBWATCH_LLM_MODEL'] = 'openai/sol'
os.environ.setdefault("JOBWATCH_PUBLIC_HOST", "jobs.example.com")
import shutil
import json
from unittest import mock
from pathlib import Path

import pytest
import yaml

from jobwatch.collectors.base import CollectorContext
from jobwatch.config import Config, DEFAULT_SETTINGS, DEFAULT_CONFIG_DIR, _merge
from jobwatch.filters import Rules
from jobwatch.util.http import HttpError

FIX = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIX / name).read_text()


def fixture_json(name: str):
    return json.loads(fixture_text(name))


class FakeResponse:
    def __init__(self, text, headers=None, status=200):
        self.text, self.headers, self.status_code = text, headers or {}, status


class FakeHttp:
    """Maps URL substrings to fixture payloads. Values: dict/list (JSON), str (text),
    or an int status code to raise HttpError."""

    def __init__(self, routes: dict, disallow: tuple = (), headers: dict | None = None):
        self.routes, self.disallow, self.headers = routes, disallow, headers or {}
        self.calls: list[tuple[str, str]] = []

    def _find(self, url):
        for key in sorted(self.routes, key=len, reverse=True):
            if key in url:
                value = self.routes[key]
                if isinstance(value, int):
                    raise HttpError(url, value)
                return value
        raise HttpError(url, 404)

    def get_json(self, url, params=None, **kw):
        self.calls.append(("GET", url, params))
        value = self._find(url)
        return json.loads(value) if isinstance(value, str) else value

    def post_json(self, url, body, **kw):
        self.calls.append(("POST", url, body))
        return self._find(url)

    def get_text(self, url, params=None, robots=False, **kw):
        self.calls.append(("GET", url, params))
        if robots and not self.allowed(url):
            raise HttpError(url, 0, "robots.txt disallows")
        value = self._find(url)
        return value if isinstance(value, str) else json.dumps(value)

    def request(self, method, url, **kw):
        self.calls.append((method, url, None))
        return FakeResponse(self._find(url), self.headers)

    def allowed(self, url):
        return not any(d in url for d in self.disallow)


def make_config(employers=None, searches=None, feeds=None, settings=None, tmp_path=None):
    rules = yaml.safe_load((DEFAULT_CONFIG_DIR / "rules.yaml").read_text())
    feeds_doc = feeds if feeds is not None else yaml.safe_load((DEFAULT_CONFIG_DIR / "feeds.yaml").read_text())
    base = _merge(DEFAULT_SETTINGS, settings or {})
    if tmp_path is not None:
        base["db_path"] = str(tmp_path / "test.db")
    return Config(config_dir=DEFAULT_CONFIG_DIR, settings=base, rules=rules, searches=searches or {},
                  feeds=feeds_doc, employers=employers or [])


def make_ctx(http, employers=None, searches=None, feeds=None, limit=None, known=()):
    config = make_config(employers, searches, feeds)
    rules = Rules(config.rules, config.employers)
    state = {}
    return CollectorContext(config=config, http=http, limit=limit, title_relevant=rules.title_relevant,
                            is_known=lambda s, sid: sid in known,
                            state_get=lambda k, d=None: state.get(k, d),
                            state_set=lambda k, v: state.__setitem__(k, v))


@pytest.fixture(autouse=True)
def _no_env(monkeypatch, tmp_path):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'private-data'))
    for var in ("JOBWATCH_DB", "JOBWATCH_CONFIG_DIR", "JOBWATCH_EMPLOYERS"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    """No test may reach the real OmniRoute: an LLM() built without keys finds none and refuses before any request.
    Tests that need a model pass a fake transport and their own keys."""
    from jobwatch.util import llm as llmmod
    monkeypatch.setattr(llmmod, "load_keys", lambda: [])


@pytest.fixture(autouse=True)
def _no_tinyfish_fallback(monkeypatch):
    """No test may reach the paid TinyFish fallback: a key file on the machine made blocked-fetch tests fetch a real
    page instead of raising. A test that covers the fallback sets the key itself."""
    from jobwatch.util import adtext
    monkeypatch.setattr(adtext, "_tinyfish_key", lambda: "")

@pytest.fixture(autouse=True)
def _cv_printer_without_browser(monkeypatch, request):
    """Drafts print the CV through career-ops' template in Chromium; tests keep the old in-process printer
    (the draft module's render_pdf, which many tests replace) unless marked real_cv_printer."""
    if request.node.get_closest_marker("real_cv_printer"):
        # The marker only means "do not install the stand-in". It is not a gate, so without the browser
        # extra or its Chromium build the test used to error instead of skipping.
        pytest.importorskip("playwright.sync_api", reason="real_cv_printer needs the browser extra")
        if not shutil.which("pdftotext") or not shutil.which("pdfinfo"):
            pytest.skip("real_cv_printer needs poppler (pdftotext, pdfinfo)")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as play:
                play.chromium.launch(headless=True).close()
        except Exception as exc:                                    # no downloaded browser, no sandbox
            pytest.skip(f"real_cv_printer needs a launchable Chromium: {type(exc).__name__}")
        return
    from pipeline.agentic import draft

    def fake(content, profile, cv_tpl):
        pdf, _ = draft.render_pdf(draft.cv_markdown(content, profile, cv_tpl=cv_tpl), max_pages=draft.CV_PAGES[cv_tpl])
        return pdf, {"ats": {"score": 100, "grade": "A", "issues": []}, "pages": 1, "max_pages": 2}
    monkeypatch.setattr(draft, "render_cv_pdf", fake)


@pytest.fixture(autouse=True)
def _no_openrouter_key(monkeypatch):
    # Tests never reach OpenRouter (Jev) or OmniRoute (embeddings): no key means both return None and the pipeline runs as before.
    import jobwatch.util.openrouter_extras as extras
    monkeypatch.setattr(extras, "_key", lambda cfg: None)
    monkeypatch.setattr(extras, "embed", lambda texts, config=None: None)



@pytest.fixture(autouse=True)
def _person_in_melbourne(monkeypatch):
    """The app is per person (jobwatch.util.place); tests use the owner's values: Brunswick, VIC, Melbourne time."""
    import jobwatch.util.place as place
    monkeypatch.setattr(place, "_candidate", lambda: {"location": "Brunswick, VIC", "state": "VIC",
                                                       "timezone": "Australia/Melbourne"})


@pytest.fixture(autouse=True)
def _person_profile(tmp_path_factory, monkeypatch):
    """A profile dir with one example person's values; tests of the person-specific rules rely on it.
    Tests that need another person (or none) set JOBWATCH_PROFILE_DIR themselves."""
    d = tmp_path_factory.mktemp("person_profile")
    (d / "profile.yaml").write_text(yaml.safe_dump({"candidate": {"work_rights": {
        "visa": "Australian Student visa (subclass 500)",
        "work_conditions": "work rights up to 48 hours per fortnight during study periods",
        "hours_limit_per_fortnight": 48, "full_time_programs_ok": True}}}))
    (d / "interests_and_criteria.yaml").write_text(yaml.safe_dump({"target_roles": {"excluded_families": [
        "customer_service", "hospitality", "retail", "shop_floor", "engineering", "health", "education",
        "trades", "it", "sales_marketing", "other"]}}))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(d))


_HAND_NAMES = ("master_resume.md", "cv.md", "profile.yaml", "evidence.yaml", "transferable_skills_taxonomy.yaml",
               "career_ops_profile.md", "interests_and_criteria.yaml")
SYNTHETIC_CV = b"Alex Example\nAccounts Assistant\n\nExperience\nLedger Co, Accounts Assistant, 2021 - 2023\n"


def confirm_discovery(config, person=None):
    """Synthetic: turn discovery on for a person through the public intake API (adopt any hand-made files, propose from a
    synthetic CV with a fake model, confirm with the scope shown). Returns the new version number."""
    from jobwatch.util import model_choice as model_choice
    from jobwatch import users
    from jobwatch.candidate import intake
    from jobwatch.util.llm import LLM
    person = person or users.current()
    facts = {"facts": [{"section": "experience", "value": "Accounts Assistant, Ledger Co", "basis": "evidence", "upload": 1,
                        "sources": [{"line": 5, "quote": "Ledger Co, Accounts Assistant, 2021 - 2023"}]}], "questions": []}
    with mock.patch.object(model_choice, "SERVER_URL", "http://127.0.0.1:20128/v1"), \
            mock.patch.object(intake, "get_model", lambda role, user=None: "claude/sonnet"):     # the approved paid route
        llm = LLM(transport=lambda url, headers, body, timeout: (200, {"choices": [{"message": {"content": json.dumps(facts)}}],
                  "usage": {}}), keys=["synthetic"], base_url=model_choice.SERVER_URL)
        return _confirm(config, person, llm)


def _confirm(config, person, llm):
    from jobwatch import users
    from jobwatch.apply import paths as apaths
    from jobwatch.candidate import intake
    with users.use(person):
        pdir = apaths.profile_dir()
        if intake.current_version(person) is None and any(os.path.lexists(pdir / n) for n in _HAND_NAMES):
            if not any(os.path.lexists(pdir / n) for n in ("cv.md", "master_resume.md")):
                (pdir / "master_resume.md").write_text("# Synthetic\n\nAccounts Assistant, 2021\n")      # adoption needs a CV source
            intake.adopt_existing(person, actor="person")
        cur = intake.current_version(person)
        up = intake.save_upload(person, "cv.txt", SYNTHETIC_CV, "cv")["upload_id"]
        prop = intake.propose(person, [up], llm, base_version=cur["version"] if cur else None)
        shown = intake.confirmation(person, prop.id, config)
        return intake.confirm(person, prop.id, proposal_digest=shown["proposal_digest"], scope_digest=shown["scope_digest"],
                              actor="person", config=config)
