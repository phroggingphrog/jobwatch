"""End-to-end tests of the deterministic pipeline (pipeline/graph.py) with mock job payloads and a fake model
gateway: hardcoded edges, strict schemas, retry max 3 then dead letter queue, the 3.8 quality gate, the absolute
work-rights rule, resume after a stop, and that nothing is ever submitted. No network."""
import asyncio
import json
import os
import re
from pathlib import Path

import pytest
import yaml

from conftest import make_config
from jobwatch import db as dbm
from jobwatch.apply import chain
from jobwatch.dedupe import ingest as ingest_posting
from jobwatch.util.llm import LLM
from jobwatch.models import Posting
from pipeline import graph, store
from pipeline.nodes import gate
from pipeline.schemas import JobFacts, MatchScore, Stage, WorkRights

AD = ("Accounts Assistant (part time). You will process supplier invoices, reconcile statements and help with "
      "month-end in Excel and MYOB. Part-time hours, 3 days a week, Melbourne CBD. You must have the right to work "
      "in Australia. ") * 4


def facts(**kw):
    d = {"real_job": True, "role_family": "finance_clerical", "duties": ["process invoices"],
         "required_skills": ["Excel", "MYOB"], "preferred_skills": [], "seniority": "entry", "min_years": None,
         "hours": "part_time_ok", "program": False,
         "work_rights": {"requirement": "valid_work_rights", "quote": "You must have the right to work in Australia."},
         "screening_questions": ["Do you have MYOB experience?"]}
    d.update(kw)
    return d


def score(t=4, e=5, d=5, wanted="core"):
    m = lambda s: {"score": s, "evidence": "evidence words"}  # noqa: E731
    return {"technical_skills": m(t), "experience": m(e), "domain": m(d), "wanted": wanted,
            "justification": "Accounts work the candidate pursues, entry level."}


class Gateway:
    """Fake OmniRoute. Replies chosen by node (system prompt) and job title. A reply may be a list: one per call
    (to script bad replies before a good one)."""

    def __init__(self, extract=None, evaluate=None, answers=None):
        self.extract, self.evaluate, self.answers = extract or {}, evaluate or {}, answers
        self.calls, self.seen = [], {}

    def _pick(self, table, title, default):
        v = table.get(title, default)
        if isinstance(v, list):
            i = self.seen.get((id(table), title), 0)
            self.seen[(id(table), title)] = i + 1
            v = v[min(i, len(v) - 1)]
        return v

    def __call__(self, url, headers, body, timeout):
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        title = next((ln[6:].strip() for ln in user.splitlines() if ln.startswith("Role: ")), "")
        node = "extract" if "extract facts" in system else "evaluate" if "score how well" in system else "answers"
        self.calls.append((node, title))
        if node == "extract":
            out = self._pick(self.extract, title, facts())
        elif node == "evaluate":
            out = self._pick(self.evaluate, title, score())
        else:
            out = self.answers or {"answers": [{"question": "Do you have MYOB experience?",
                                                "answer": "Yes, I used MYOB in my accounts role.", "source": "evidence"}]}
        text = out if isinstance(out, str) else json.dumps(out)
        return 200, {"choices": [{"message": {"content": text}}], "usage": {}}


@pytest.fixture(autouse=True)
def confirmed_candidate(monkeypatch):
    """These graph fixtures explicitly confirm rights and region; no donor defaults."""
    from jobwatch.candidate.policy import build_policy
    policy = build_policy({'version': 1, 'facts': [
        {'section': 'work_rights', 'basis': 'evidence', 'value': {
            'valid_work_rights': True, 'citizen': False, 'permanent_resident': False,
            'unrestricted_work_rights': False}},
        {'section': 'location', 'basis': 'evidence', 'value': 'Victoria'}]})
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda *args, **kwargs: policy)
    return policy


@pytest.fixture
def world(tmp_path, monkeypatch):
    pdir = tmp_path / "data" / "profile"
    pdir.mkdir(parents=True)
    (pdir / "cv.md").write_text("# Jane Doe\n\n## Experience\nAccounts assistant\n")
    (pdir / "evidence.yaml").write_text(yaml.safe_dump({"items": [
        {"id": "s1", "kind": "skill", "text": "Excel", "source_file": "cv.md", "line": 1},
        {"id": "s2", "kind": "skill", "text": "MYOB", "source_file": "cv.md", "line": 1},
        {"id": "r1", "kind": "role", "text": "Accounts assistant", "source_file": "cv.md", "line": 3}]}))
    (pdir / "answers.yaml").write_text(yaml.safe_dump({"version": 1, "work_rights": {"visa_type": "Student (500)",
                                                                                    "visa_expiry": ""},
                                                       "availability": {"notice_period": "1 week"},
                                                       "referees": [{"name": "A Referee", "phone": ""}]}))
    (tmp_path / "data" / "interest").mkdir()
    (tmp_path / "data" / "interest" / "interest_model.md").write_text(
        "PURSUES: accounting, accounts payable, bookkeeping, admin. NOT WANTED: retail, hospitality, call centre.")
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(pdir))
    monkeypatch.setattr("jobwatch.util.adtext.pace", lambda *a, **k: None)
    config = make_config(tmp_path=tmp_path)
    conn = dbm.connect(config.db_path)
    drafts = {"n": 0, "fail": 0}

    def fake_start_draft(c, match_id, actor, *, llm=None, profile=None):
        """Stands in for the real chain: writes an application, a draft row and the files a verified draft has."""
        drafts["n"] += 1
        pid = c.execute("SELECT posting_id FROM matches WHERE id=?", (match_id,)).fetchone()[0]
        c.execute("INSERT OR IGNORE INTO applications(posting_id, match_id, status, created_at, updated_at) "
                  "VALUES(?,?,?,?,?)", (pid, match_id, "drafted", dbm.ts(), dbm.ts()))
        app = c.execute("SELECT id FROM applications WHERE posting_id=?", (pid,)).fetchone()[0]
        ver = (c.execute("SELECT MAX(version) FROM drafts WHERE application_id=?", (app,)).fetchone()[0] or 0) + 1
        vdir = tmp_path / "data" / "drafts" / str(app) / f"v{ver}"
        vdir.mkdir(parents=True)
        ok = drafts["fail"] == 0
        for f in ("cv.pdf", "letter.pdf"):
            (vdir / f).write_bytes(b"%PDF-1.4 test")
        (vdir / "letter.md").write_text("Dear hiring manager, ...")
        (vdir / "summary.json").write_text(json.dumps({"verify_ok": ok, "pages": {"cv": 1, "letter": 1}}))
        c.execute("INSERT INTO drafts(application_id, version, created_at, status, dir, error) VALUES(?,?,?,?,?,?)",
                  (app, ver, dbm.ts(), "ready" if ok else "failed", str(vdir), None if ok else "verify failed"))
        c.commit()
        return app
    monkeypatch.setattr(chain, "start_draft", fake_start_draft)

    def add(title, desc=AD, location="Melbourne VIC", company="Acme", raw=None, source="ats_pageup"):
        p = Posting(source=source, source_id=title.replace(" ", "-"), url=f"https://example.com/{title.replace(' ', '-')}",
                    title=title, company=company, location=location, description=desc, raw=raw or {})
        pid, _ = ingest_posting(conn, p)
        conn.commit()
        return pid

    def run(gw, **settings):
        s = graph.Settings(concurrency=2, **settings)
        g = graph.Graph(conn=conn, db_path=str(config.db_path), config=config, settings=s,
                        llm=LLM(transport=gw, keys=["test-key"]))
        return g, asyncio.run(g.run())

    run.config = config
    return conn, add, run, drafts


def stage(conn, pid):
    return store.get(conn, pid)["stage"]


# ------------------------------------------------------------------------------------------------ the whole graph
def test_a_good_job_goes_through_every_node_to_ready_and_nothing_is_submitted(world):
    conn, add, run, drafts = world
    pid = add("Accounts Assistant")
    gw = Gateway()
    _, stats = run(gw)
    assert stage(conn, pid) == "ready"
    nodes = [r["node"] for r in conn.execute("SELECT node FROM pipeline_events WHERE posting_id=? ORDER BY id", (pid,))]
    assert nodes == ["ingest", "extract", "evaluate", "gate", "draft", "form_map"]
    data = store.get(conn, pid)["data"]
    assert data["evaluate"]["overall"] == 4.6 and data["gate"]["passed"] is True
    fmap_path = Path(data["form_map"]["form_map"])
    fmap = json.loads(fmap_path.read_text())
    by = {f["field"]: f for f in fmap["fields"]}
    assert by["work_rights.visa_type"] == {"field": "work_rights.visa_type", "value": "Student (500)",
                                           "source": "answers_file"}
    assert by["work_rights.visa_expiry"]["source"] == "owner_to_answer" and by["contact.email"]["source"] == "owner_to_answer"
    assert by["referees"]["value"] == "name: A Referee" and "version" not in by
    assert fmap["owner_to_answer"] == sum(f["source"] == "owner_to_answer" for f in fmap["fields"])
    assert by["Q: Do you have MYOB experience?"]["source"] == "evidence"
    assert oct(os.stat(fmap_path).st_mode & 0o777) == "0o600"
    ev = conn.execute("SELECT detail_json FROM application_events WHERE source='pipeline'").fetchone()
    assert json.loads(ev[0])["ready_to_submit"] is True
    apps = conn.execute("SELECT status FROM applications").fetchall()
    assert [a[0] for a in apps] == ["drafted"]                      # never 'applied': the owner submits by hand
    assert drafts["n"] == 1


def test_a_low_score_remains_advisory_and_supported_job_can_be_drafted(world):
    conn, add, run, drafts = world
    pid = add("Data Entry Clerk")
    run(Gateway(evaluate={"Data Entry Clerk": score(2, 3, 4)}))
    row = store.get(conn, pid)
    assert row["stage"] == "ready" and drafts["n"] == 1
    assert row["data"]["evaluate"]["overall"] == 2.9


@pytest.mark.parametrize("marks,route", [((5, 3, 3), "draft"), ((4, 4, 3), "draft"), ((4, 4, 4), "draft")])
def test_computed_scores_are_preserved_without_unconfirmed_cutoff(marks, route):
    sc = MatchScore.model_validate(score(*marks))
    got, dec = gate.decide(JobFacts.model_validate(facts()), sc, AD, "Accounts Assistant", posting={"location": "Melbourne VIC"})
    assert got == route and dec.score == sc.overall


def test_model_not_wanted_is_not_a_confirmed_person_exclusion():
    got, dec = gate.decide(JobFacts.model_validate(facts()), MatchScore.model_validate(score(5, 5, 5, "not_wanted")), AD, posting={"location": "Melbourne VIC"})
    assert (got, dec.reason) == ("draft", "eligible")


# ------------------------------------------------------------------------------------------------ work rights (absolute)
def test_citizenship_quoted_from_the_ad_is_an_absolute_fail(world):
    conn, add, run, drafts = world
    text = AD + "Applicants must be Australian citizens or permanent residents. " * 3
    pid = add("Payroll Officer", desc=text)
    run(Gateway(extract={"Payroll Officer": facts(work_rights={
        "requirement": "citizen_or_pr", "quote": "Applicants must be Australian citizens or permanent residents."})},
        evaluate={"Payroll Officer": score(5, 5, 5)}))
    row = store.get(conn, pid)
    # prescreen now catches the explicit citizenship text first (reason "prescreened"); the gate's own check is the backstop
    assert row["stage"] == "archived" and row["reason"] in ("prescreened", "work_rights_incompatible") and drafts["n"] == 0


def test_a_rights_claim_the_ad_does_not_say_goes_to_review_not_to_a_guess(world):
    conn, add, run, _ = world
    pid = add("Accounts Officer")
    run(Gateway(extract={"Accounts Officer": facts(work_rights={"requirement": "citizen_only",
                                                                "quote": "Australian citizens only"})}))
    row = store.get(conn, pid)
    assert row["stage"] == "dlq"
    dlq = conn.execute("SELECT * FROM pipeline_dlq WHERE posting_id=?", (pid,)).fetchone()
    assert "verification_required" in dlq["error"]


def test_a_visa_alternative_is_held_until_approved_facts_establish_the_branch():
    text = AD + "You must be an Australian citizen, permanent resident or hold a valid visa with work rights."
    got, _ = gate.decide(JobFacts.model_validate(facts(work_rights={"requirement": "valid_work_rights", "quote": "You must have the right to work in Australia."})),
                         MatchScore.model_validate(score()), text, posting={"location": "Melbourne VIC"})
    assert got == "review"  # Valid rights alone do not establish the advertised visa alternative.


# ------------------------------------------------------------------------------------------------ retries and the DLQ
def test_bad_replies_are_retried_and_the_third_valid_one_is_used(world):
    conn, add, run, _ = world
    pid = add("Bookkeeper")
    gw = Gateway(extract={"Bookkeeper": ["not json at all", {**facts(), "seniority": "boss"}, facts()]})
    run(gw)
    assert stage(conn, pid) == "ready"
    ev = conn.execute("SELECT attempts FROM pipeline_events WHERE posting_id=? AND node='extract'", (pid,)).fetchone()
    assert ev[0] == 3 and [c for c in gw.calls if c[0] == "extract"].count(("extract", "Bookkeeper")) == 3


def test_three_failures_go_to_the_dead_letter_queue_and_can_be_retried(world):
    conn, add, run, _ = world
    pid = add("Accounts Clerk")
    gw = Gateway(extract={"Accounts Clerk": {"real_job": True}})     # always incomplete
    run(gw)
    assert stage(conn, pid) == "dlq" and gw.calls.count(("extract", "Accounts Clerk")) == 3
    d = conn.execute("SELECT * FROM pipeline_dlq WHERE posting_id=?", (pid,)).fetchone()
    assert d["node"] == "extract" and d["attempts"] == 3 and d["stage"] == "ingested" and "schema" in d["error"]
    store.retry_dlq(conn, d["id"])
    conn.commit()
    assert stage(conn, pid) == "ingested"
    run(Gateway())
    assert stage(conn, pid) == "ready"




def test_a_failed_draft_is_retried_three_times_then_dead_lettered(world):
    conn, add, run, drafts = world
    drafts["fail"] = 1
    pid = add("Accounts Assistant")
    run(Gateway())
    assert stage(conn, pid) == "dlq" and drafts["n"] == 3
    assert conn.execute("SELECT node, attempts FROM pipeline_dlq").fetchone()[:] == ("draft", 3)


# ------------------------------------------------------------------------------------------------ edges, resume, node 1
def test_a_move_outside_the_edges_raises(world):
    conn, add, run, _ = world
    pid = add("Accounts Assistant")
    g, _ = run(Gateway(), drafts_per_run=0)
    with pytest.raises(RuntimeError, match="illegal move"):
        g._move(pid, Stage.DRAFT_QUEUED, Stage.READY, {})


def test_the_drafting_cap_waits_and_the_next_run_resumes(world):
    conn, add, run, drafts = world
    pid = add("Accounts Assistant")
    run(Gateway(), drafts_per_run=0)
    assert stage(conn, pid) == "draft_queued" and drafts["n"] == 0
    gw = Gateway()
    run(gw)
    assert stage(conn, pid) == "ready" and not [c for c in gw.calls if c[0] in ("extract", "evaluate")]


def test_the_daily_drafting_cap_counts_drafts_from_earlier_runs(world):
    conn, add, run, drafts = world
    pid = add("Accounts Assistant")
    store.ensure(conn)
    for i in range(2):                                     # two drafts finished earlier today
        store.event(conn, 900 + i, "draft", Stage.DRAFT_QUEUED, Stage.DRAFTED, 1, None)
    conn.commit()
    run(Gateway(), drafts_per_day=2)
    assert stage(conn, pid) == "draft_queued" and drafts["n"] == 0
    run(Gateway(), drafts_per_day=3)
    assert stage(conn, pid) == "ready" and store.drafted_since(conn) == 3


def test_node_1_dedupes_by_ad_text_skips_other_states_and_archives_paid_ads(world):
    conn, add, run, _ = world
    a = add("Accounts Assistant")
    b = add("Accounts Assistant - Repost", company="Acme")
    away = add("Accounts Assistant Sydney", location="Sydney NSW")
    paid = add("Payables Officer", source="seek", raw={"displayType": "promoted"},
               desc=AD.replace("Accounts", "Payables"))
    run(Gateway())
    assert stage(conn, a) == "ready"
    assert store.get(conn, b)["reason"] == f"duplicate_of:{a}"
    excluded = store.get(conn, away)
    assert excluded['stage'] == 'archived' and excluded['reason'] == 'prescreened'
    from jobwatch.prescreen.store import latest_decision
    decision = latest_decision(conn, away)
    assert decision['outcome'] == 'skip' and decision['category'] == 'location_outside'
    assert store.get(conn, paid)["reason"] == "sponsored_ad"


def test_a_short_teaser_is_not_admitted_until_the_whole_ad_is_there(world):
    conn, add, run, _ = world
    pid = add("Accounts Assistant", desc="Short teaser only.")
    run(Gateway())
    assert store.get(conn, pid) is None


def test_no_new_node_starts_after_the_time_limit_and_the_next_run_resumes(world):
    conn, add, run, _ = world
    pid = add("Accounts Assistant")
    gw = Gateway()
    g = graph.Graph(conn=conn, db_path=str(Path(conn.execute("PRAGMA database_list").fetchone()[2])),
                    config=run.config, settings=graph.Settings(), llm=LLM(transport=gw, keys=["k"]))
    stats = asyncio.run(g.run(max_seconds=1e-9))                      # the limit is already over after node 1
    assert stage(conn, pid) == "ingested" and gw.calls == [] and stats["time_limit"] == 1
    run(Gateway())
    assert stage(conn, pid) == "ready"


def test_the_timer_hook_is_off_unless_the_owner_switches_it_on():
    class C:
        settings = {"pipeline": {"enabled": False}}
    assert graph.enabled(C()) is False and graph.enabled(None) is False
    C.settings = {"pipeline": {"enabled": True}}
    assert graph.enabled(C()) is True


# ------------------------------------------------------------------------------------------------ BUI-96 not-target kinds
class SortGateway(Gateway):
    """Gateway that also answers the not-target sorting call (a list of {id, kind})."""

    def __init__(self, kinds=None, bad=0, **kw):
        super().__init__(**kw)
        self.kinds, self.bad = kinds or {}, bad

    def __call__(self, url, headers, body, timeout):
        system = body["messages"][0]["content"]
        if "Name the MAIN" not in system:
            return super().__call__(url, headers, body, timeout)
        self.calls.append(("sort", ""))
        if self.bad > 0:
            self.bad -= 1
            return 200, {"choices": [{"message": {"content": '{"results": [{"id": 1, "kind": "astronaut"}]}'}}], "usage": {}}
        ids = [int(ln.split(" | ", 1)[0]) for ln in body["messages"][1]["content"].splitlines() if " | " in ln]
        res = [{"id": i, "kind": self.kinds.get(i, "hospitality")} for i in ids] + [{"id": 99999, "kind": "sales"}]
        return 200, {"choices": [{"message": {"content": json.dumps({"results": res})}}], "usage": {}}


def test_archived_not_target_jobs_get_a_named_kind_without_moving(world):
    conn, add, run, drafts = world
    cafe = add("Barista", desc=AD.replace("Accounts", "Cafe"))
    shop = add("Shop Assistant", desc=AD.replace("Accounts", "Shop"))
    good = add("Accounts Assistant")
    nw = score(2, 3, 1, wanted="not_wanted")
    conn.execute("INSERT INTO ad_reviews(posting_id, content_hash, prompt_version, model, verdict, reviewed_at, model_json) "
                 "VALUES(?,?,?,?,?,?,?)", (shop, "c", 5, "m", "hide", "t", json.dumps({"not_target_kind": "shop_retail"})))
    conn.commit()
    store.ensure(conn)
    for pid in (cafe, shop):
        store.admit(conn, pid, "old-" + str(pid), {}, stage=Stage.ARCHIVED, reason="not_target")
    conn.commit()
    gw = SortGateway(kinds={cafe: "hospitality"}, evaluate={"Barista": nw, "Shop Assistant": nw})
    _, stats = run(gw)
    assert stats["sort"] == {"candidates": 2, "from_reader": 1, "from_model": 1, "failed_batches": 0}
    for pid, kind, src in ((cafe, "hospitality", "model"), (shop, "shop_retail", "reader")):
        row = store.get(conn, pid)
        assert (row["stage"], row["reason"]) == ("archived", "not_target")          # never moved
        assert row["data"]["sort"] == {"not_target_kind": kind, "source": src}
    assert stage(conn, good) == "ready" and "sort" not in store.get(conn, good)["data"]
    assert [c for c in gw.calls if c[0] == "sort"] == [("sort", "")]                # the reader's kind cost no call
    n = conn.execute("SELECT COUNT(*) FROM pipeline_events WHERE node='sort'").fetchone()[0]
    assert n == 0                                                                   # labels are not moves
    _, again = run(SortGateway())
    assert again["sort"]["candidates"] == 0                                         # sorted once only


def test_a_bad_sort_reply_is_retried_then_left_for_the_next_run(world):
    conn, add, run, _ = world
    cafe = add("Barista", desc=AD.replace("Accounts", "Cafe"))
    nw = score(2, 3, 1, wanted="not_wanted")
    store.ensure(conn)
    store.admit(conn, cafe, "old-cafe", {}, stage=Stage.ARCHIVED, reason="not_target")
    conn.commit()
    _, stats = run(SortGateway(bad=3, evaluate={"Barista": nw}))
    assert stats["sort"]["failed_batches"] == 1 and "sort" not in store.get(conn, cafe)["data"]
    assert conn.execute("SELECT COUNT(*) FROM pipeline_dlq").fetchone()[0] == 0     # no job dead-lettered for a label
    _, stats = run(SortGateway(bad=1))                                              # one bad reply, then a good one
    assert stats["sort"]["from_model"] == 1 and store.get(conn, cafe)["data"]["sort"]["not_target_kind"] == "hospitality"


def test_annotate_only_touches_archived_jobs(world):
    conn, add, run, _ = world
    pid = add("Accounts Assistant")
    run(Gateway(), drafts_per_run=0)
    before = store.get(conn, pid)
    store.annotate(conn, pid, "sort", {"not_target_kind": "sales", "source": "model"})
    assert store.get(conn, pid) == before


def test_a_slow_ad_page_does_not_crash_the_run(world, monkeypatch):
    """Run 224 (2026-10-08 06:40 UTC): a curl timeout inside node 1's fetch killed the whole AI step."""
    conn, add, run, _ = world
    from jobwatch.util import adtext as adtext
    real = adtext.ensure_text
    calls = {"n": 0}

    def flaky(c, r, fetcher=None, *, allow_fetch=True, **kw):
        if allow_fetch and r["title"] == "Slow Page":
            calls["n"] += 1
            raise TimeoutError("curl: (28) Operation too slow")
        return real(c, r, fetcher, allow_fetch=allow_fetch, **kw)
    monkeypatch.setattr(adtext, "ensure_text", flaky)
    monkeypatch.setattr(adtext, "fetch_host", lambda s: "example.com")
    monkeypatch.setattr(adtext, "wants_fetch", lambda c, r: True)
    slow = add("Slow Page", desc="Short teaser only.")
    ok = add("Accounts Assistant")
    _, stats = run(Gateway())
    assert calls["n"] == 1 and stats["ingest"]["fetch_errors"] == 1
    assert store.get(conn, slow) is None and stage(conn, ok) == "ready"


def test_legacy_mode_prompts_name_no_one_person():
    from pipeline.nodes import evaluate, extract
    for text in (evaluate.SYSTEM, extract.SYSTEM):
        assert not re.search(r'\bstudent\b|student-visa|Melbourne|Victoria', text, re.I)
