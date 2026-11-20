"""The page-fetch loop of the AI reader: the fetch log (a dead ad is not requested on every run), failures that count
against the budget and the pace and stop a host, one bad ad never aborts the batch, one review run at a time, the
wall-clock budget, and rederive using the same text kinds as the reader. Also the collector-side URL checks of
jsonld_pages. No network, no model: fetchers and the gateway are fakes."""
import json
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import confirm_discovery, make_config
from jobwatch.util import adtext as adtext
from jobwatch import db as dbm
from jobwatch import run as pipeline
from jobwatch.collectors import jsonld_pages
from jobwatch.dedupe import ingest
from jobwatch.util.llm import LLM
from jobwatch.models import Posting

FIX = Path(__file__).parent / "fixtures" / "adtext"
UTC = timezone.utc
ANSWER = {"real_job": True, "ad_kind": "employer", "archetype": "Accounts", "tldr": "x",
          "role": {"seniority": "junior", "work_mode": "onsite", "hours": "part_time_ok", "location_fit": "inner",
                   "min_years": None},
          "authorization": {"requirement": "none_stated", "quote": ""}, "requirements": [], "gaps": [],
          "dimensions": {"cv_match": 4, "north_star": 4, "comp": 3, "culture": 3, "red_flags": 5}, "score": 4.2,
          "recommendation": "apply", "legitimacy": {"tier": "high", "signals": []},
          "comp": {"company_type": "SMB", "reliability": "Low"}, "reason": "ok"}
LONG = "Process invoices and answer supplier queries. " * 30            # a fetched ad body (1350 chars)


class Gateway:
    """Stands in for OmniRoute: every ad gets the same good reading; counts the calls."""

    def __init__(self, delay: float = 0.0):
        self.calls, self.delay = 0, delay

    def __call__(self, url, headers, body, timeout):
        self.calls += 1
        text = "\n".join(m["content"] for m in body["messages"])
        if self.delay:
            time.sleep(self.delay)
        if "JOBS (id | title | company | place | start of ad):\n" in text:
            ids = [int(line.split(" | ")[0]) for line in text.split("JOBS (id | title | company | place | start of ad):\n")[1].splitlines() if line.strip()]
            out = {"results": [{"id": i, "relevant": False} for i in ids]}
        else:
            out = ANSWER
        return 200, {"model": body["model"], "choices": [{"message": {"content": json.dumps(out)}}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    pdir = tmp_path / "profile"
    pdir.mkdir()
    (pdir / "career_ops_profile.md").write_text("Target roles: accounts. Policy: part-time only.")
    (pdir / "cv.md").write_text("Jane Doe\nSomewhere | 0400 000 000 | jane@example.com\nAccounting graduate.")
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(pdir))
    config = make_config(tmp_path=tmp_path, settings={"reader": {"seek_delay": 0, "workers": 1, "enabled": True}})
    conn = dbm.connect(config.db_path)
    paces: list[float] = []
    monkeypatch.setattr(adtext, "pace", lambda seconds=0: paces.append(seconds))
    counter = {"n": 0}
    base = datetime.now(UTC)

    def add(title, source="jora", desc="short teaser", url=None, source_id=None, raw=None, match=True):
        counter["n"] += 1
        slug = title.replace(" ", "-")
        p = Posting(source=source, source_id=source_id or slug, url=url or f"https://au.jora.com/job/{slug}",
                    title=title, company="Acme", location="Melbourne VIC", description=desc, raw=raw or {})
        pid, _ = ingest(conn, p)
        if match:                                           # distinct, falling times: the pending query is newest first
            conn.execute("INSERT INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, matched_at) "
                         "VALUES(?,?,?,?,?,?,?)", (pid, "general_clerk", "core", "[]", "{}", "[]",
                                                   dbm.ts(base - timedelta(seconds=counter["n"]))))
        conn.commit()
        return pid

    return types.SimpleNamespace(config=config, conn=conn, add=add, paces=paces, tmp=tmp_path, gw=Gateway())


def llm_of(w):
    return LLM(transport=w.gw, keys=["test-key"])


def use(monkeypatch, source, run, host=None):
    """Replace one source's page fetcher (the network call) with `run(ref) -> text`."""
    old = adtext._FETCHERS[source]
    monkeypatch.setitem(adtext._FETCHERS, source, adtext._Fetcher(host or old.host, old.label, run))


def age_fetch_log(conn, hours):
    old = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
    conn.execute("UPDATE ad_fetch SET last_try_at=?", (old,))
    conn.commit()


# ------------------------------------------------------------------------- the fetch log (dead ads, no refetch)
def test_ad_fetch_table_exists_and_follows_its_posting(world):
    pid = world.add("Clerk")
    adtext._record_fetch(world.conn, pid, "gone")
    assert tuple(world.conn.execute("SELECT tries, last_status FROM ad_fetch").fetchone()) == (1, "gone")
    world.conn.execute("DELETE FROM postings WHERE id=?", (pid,))
    assert world.conn.execute("SELECT COUNT(*) FROM ad_fetch").fetchone()[0] == 0


def test_fetch_due_rules(world):
    pid = world.add("Clerk")
    assert adtext.fetch_due(world.conn, pid)                    # never tried
    adtext._record_fetch(world.conn, pid, "empty")
    now = datetime.now(UTC)
    assert not adtext.fetch_due(world.conn, pid, now + timedelta(hours=23))
    assert adtext.fetch_due(world.conn, pid, now + timedelta(hours=25))
    adtext._record_fetch(world.conn, pid, "empty")
    adtext._record_fetch(world.conn, pid, "empty")
    assert not adtext.fetch_due(world.conn, pid, now + timedelta(days=90))


# ----------------------------------------------- failures: budget, pace, and three in a row stop the host
# ------------------------------------------------------- the cut description goes through the same loop
# --------------------------------------------------- one bad ad never aborts the batch
# --------------------------------------------------- wall-clock budget
# --------------------------------------------------- one review or recall run at a time
def test_review_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "data" / "review.lock"
    with adtext.review_lock(path) as first:
        assert first is True
        with adtext.review_lock(path) as second:
            assert second is False
    with adtext.review_lock(path) as again:
        assert again is True


def test_lock_file_sits_next_to_the_database(world):
    assert adtext.lock_path(world.config) == world.tmp / "review.lock"


def _args(**over):
    base = dict(cmd="review", action="run", config_dir=None, limit=None, posting=None, redo=False, model=None,
                workers=None, fetch=None)
    return types.SimpleNamespace(**{**base, **over})


# --------------------------------------------------- the pipeline hook
def _pipeline_world(tmp_path, monkeypatch, order, confirmed=True):
    config = make_config(settings={"tiers": {"fast": [], "slow": []}}, tmp_path=tmp_path)
    if confirmed:
        confirm_discovery(config)       # the AI step runs only for a person whose profile was confirmed with its scope
    real_publish, real_prune = pipeline.publish, dbm.prune
    monkeypatch.setattr(pipeline, "publish", lambda conn, dry_run=False: order.append("publish") or real_publish(conn, dry_run))
    monkeypatch.setattr(dbm, "prune", lambda conn, days: order.append("prune") or real_prune(conn, days))
    return config


# --------------------------------------------------- rederive uses the reader's text kinds
# --------------------------------------------------- collector side: jsonld_pages URLs
EMP = {"name": "Example Council", "careers_url": "https://careers.example.vic.gov.au/careers"}


def job(**over):
    return {"@type": "JobPosting", "title": "Payroll Officer", "description": "<p>Pay people.</p>",
            "jobLocation": {"address": {"addressLocality": "Melbourne", "addressRegion": "VIC",
                                        "addressCountry": "AU"}}, **over}


@pytest.mark.parametrize("url", ["https://127.0.0.1.nip.io/hook?x=1", "https://localtest.me/x", "http://10.0.0.5/jobs/1",
                                 "https://careers.example.vic.gov.au\\@evil.example.org/jobs/1",
                                 "https://user@careers.example.vic.gov.au/jobs/1", "javascript:alert(1)"])
def test_a_job_url_named_by_the_page_is_dropped_unless_it_is_on_the_employers_site(url):
    p = jsonld_pages.to_posting(job(url=url), EMP["careers_url"], EMP)
    assert p.url == EMP["careers_url"] and p.url != url


def test_a_job_url_on_the_employers_site_is_kept_and_its_hosts_are_recorded():
    own = "https://careers.example.vic.gov.au/jobs/102-payroll-officer"
    p = jsonld_pages.to_posting(job(url=own), EMP["careers_url"], EMP)
    assert p.url == own and p.raw["_site_hosts"] == ["careers.example.vic.gov.au"]
    other = {**EMP, "allowed_hosts": ["jobs.example.vic.gov.au"]}
    p = jsonld_pages.to_posting(job(url="https://jobs.example.vic.gov.au/j/1"), EMP["careers_url"], other)
    assert p.url == "https://jobs.example.vic.gov.au/j/1"
    assert p.raw["_site_hosts"] == ["careers.example.vic.gov.au", "jobs.example.vic.gov.au"]


def test_a_page_cannot_widen_its_own_recorded_hosts():
    p = jsonld_pages.to_posting(job(url="https://careers.example.vic.gov.au/jobs/1", _site_hosts=["evil.example.org"]),
                                EMP["careers_url"], EMP)
    assert p.raw["_site_hosts"] == ["careers.example.vic.gov.au"]


def test_listing_page_job_with_a_foreign_url_gets_no_shared_page_url():
    p = jsonld_pages.to_posting(job(url="https://evil.example.org/jobs/1"), EMP["careers_url"], EMP, shared_page=True)
    assert p.url == "" and ":" in p.source_id


@pytest.mark.parametrize("href", [
    "http://127.0.0.1:20128\\@careers.example.vic.gov.au/jobs/analyst-1",
    "https://careers.example.vic.gov.au\\@127.0.0.1/jobs/analyst-1",
    "https://careers.example.vic.gov.au/jobs/an\talyst-1",
    "https://user:pw@careers.example.vic.gov.au/jobs/analyst-1",
    "http://careers.example.vic.gov.au/jobs/analyst-1",          # plain http from an https page
    "https://careers.example.vic.gov.au:8443/jobs/analyst-1",
    "https://other.example.org/jobs/analyst-1",
])
def test_detail_links_refuse_backslash_userinfo_odd_ports_and_other_hosts(href):
    page = f'<a href="{href}">Analyst</a><a href="/jobs/analyst-2">Analyst two</a>'
    links = jsonld_pages.detail_links(page, EMP["careers_url"], EMP, lambda t: True)
    assert links == ["https://careers.example.vic.gov.au/jobs/analyst-2"]


# --------------------------------------------------- round 2: no fetcher, no slot
# --------------------------------------------------- round 2: --posting and --refetch override the fetch log
def _exhaust_log(world, pid):
    for _ in range(adtext.FETCH_MAX_TRIES):
        adtext._record_fetch(world.conn, pid, "blocked: jora HTTP 429")


# --------------------------------------------------- round 2: rederive takes review.lock
# --------------------------------------------------- round 2: partial is reported like teaser
# --------------------------------------------------- round 2: the run's wall clock
def test_ai_budget_is_what_is_left_of_the_unit_time():
    now = time.monotonic()
    assert 775 < pipeline.ai_budget(now) <= 780
    assert 375 < pipeline.ai_budget(now - 400) <= 380
    assert pipeline.ai_budget(now - 5000) == 0                  # an exhausted invocation has no remaining time
    cfg = make_config(settings={"reader": {"max_seconds": 100}})
    assert pipeline.ai_budget(now, cfg) == 100                  # the owner's own, lower limit still counts
    assert 375 < pipeline.ai_budget(now - 400, make_config(settings={"reader": {"max_seconds": 0}})) <= 380


# --------------------------------------------------- round 2: legacy jsonld_pages rows
# --------------------------------------------------- round 2: collector URL checks
@pytest.mark.parametrize("careers,job_url", [
    ("https://careers.example.com/jobs", "https://www.careers.example.com/job/1"),
    ("https://www.careers.example.com/jobs", "https://careers.example.com/job/1"),
])
def test_a_job_url_differing_from_the_careers_host_only_by_www_is_kept(careers, job_url):
    emp = {"name": "Example", "careers_url": careers}
    p = jsonld_pages.to_posting(job(url=job_url), careers, emp, shared_page=True)
    assert p.url == job_url and p.raw["_site_hosts"] == ["careers.example.com"]
    other = jsonld_pages.to_posting(job(url="https://www.evil.example.org/job/1"), careers, emp, shared_page=True)
    assert other.url == ""


def test_detail_links_treat_www_as_the_same_site_in_both_directions():
    emp = {"name": "Example", "careers_url": "https://careers.example.com/jobs"}
    page = '<a href="https://www.careers.example.com/jobs/a-1">A</a><a href="https://evil.example.com/jobs/b-1">B</a>'
    assert jsonld_pages.detail_links(page, emp["careers_url"], emp, lambda t: True) == [
        "https://www.careers.example.com/jobs/a-1"]
    emp = {"name": "Example", "careers_url": "https://www.careers.example.com/jobs"}
    page = '<a href="https://careers.example.com/jobs/a-1">A</a>'
    assert jsonld_pages.detail_links(page, emp["careers_url"], emp, lambda t: True) == [
        "https://careers.example.com/jobs/a-1"]


def test_a_hostile_href_loses_only_itself_not_the_employer():
    emp = {"name": "Example", "careers_url": "https://careers.example.com/jobs"}
    page = '<a href="https://x[::1]/jobs/a">bad</a><a href="/jobs/good-1">good</a>'
    assert jsonld_pages.detail_links(page, emp["careers_url"], emp, lambda t: True) == [
        "https://careers.example.com/jobs/good-1"]
    urls = jsonld_pages.page_job_urls('x https://x[::1]/jobs/a-1 and /jobs/b-1 y', emp["careers_url"], r"(?:https://x\[::1\])?/jobs/[a-z]-1")
    assert urls == {"b-1": ["https://careers.example.com/jobs/b-1"]}


def test_jobs_search_list_uses_the_same_plain_host_check():
    from jobwatch.collectors import ats_jobs_search
    emp = {"name": "Kingston", "careers_url": "https://careers.example.vic.gov.au/jobs/search"}

    def card(href):
        return (f'<article class="job-search-results-card-col"><h3><a href="{href}">Clerk</a></h3></article>')
    page = "".join(card(h) for h in (
        "/jobs/clerk-1", "https://www.careers.example.vic.gov.au/jobs/clerk-2", "https://x[::1]/jobs/clerk-3",
        "https://careers.example.vic.gov.au\\@127.0.0.1/jobs/clerk-4", "https://evil.example.org/jobs/clerk-5"))
    postings, _ = ats_jobs_search.parse_list(page, emp)
    assert [p.url for p in postings] == ["https://careers.example.vic.gov.au/jobs/clerk-1",
                                         "https://www.careers.example.vic.gov.au/jobs/clerk-2"]


# --------------------------------------------------- round 3: the limit is spent on ads that need work
def _stuck_indeed(world, n=3):
    for i in range(n):                                          # newer than the retryable ad: they come first in the queue
        world.add(f"Indeed {i}", source="jobspy_src", desc="short", source_id=f"indeed:in-{i}",
                  url=f"https://au.indeed.com/viewjob?jk={i}", raw={"site": "indeed"})


# --------------------------------------------------- round 3: the model call gets what is left of the wall clock
class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _timed_gateway(clock, takes, replies):
    """Records the timeout of every call, moves the fake clock by `takes` seconds per call, answers from `replies`."""
    calls = []

    def gateway(url, headers, body, timeout):
        calls.append(timeout)
        clock.t += takes
        content = replies[min(len(calls), len(replies)) - 1]
        return 200, {"model": body["model"], "choices": [{"message": {"content": content}}], "usage": {}}

    return calls, gateway


_POSTING = {"id": 7, "title": "Accounts Clerk", "company": "Acme", "location": "Melbourne VIC", "work_type": None,
            "salary_text": None, "posted_at": None, "first_seen_at": None, "seen_count": None, "same_title_count": 0}


# --------------------------------------------------- round 3: --redo with --posting forces only the named ads
# --------------------------------------------------- round 3: a crashed run is recorded as one
def test_a_run_that_crashes_records_the_error_class_and_still_finishes(tmp_path, monkeypatch):
    config = _pipeline_world(tmp_path, monkeypatch, [])

    def boom(conn, dry_run=False):
        raise RuntimeError("disk full at /home/someone/secret.db")

    monkeypatch.setattr(pipeline, "publish", boom)
    with pytest.raises(RuntimeError):
        pipeline.run(config, "fast")
    conn = dbm.connect(config.db_path)
    row = conn.execute("SELECT finished_at, stats_json FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    stats = json.loads(row["stats_json"])
    assert row["finished_at"] and stats["error"] == "RuntimeError"
    assert "disk full" not in row["stats_json"] and "secret" not in row["stats_json"]      # the class only

