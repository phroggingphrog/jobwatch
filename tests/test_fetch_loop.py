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
from jobwatch import adtext, reader
from jobwatch import db as dbm
from jobwatch import pipeline
from jobwatch.collectors import jsonld_pages
from jobwatch.dedupe import ingest
from jobwatch.llm import LLM
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


def review(w, **kw):
    return reader.review_pending(w.conn, w.config, llm=llm_of(w), limit=kw.pop("limit", 100), **kw)


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


def test_dead_ads_are_requested_once_not_on_every_run(world, monkeypatch):
    calls = []

    def run(ref):
        calls.append(ref.source_id)
        adtext._note("gone")                                    # a 404: the ad was taken down
        return ""

    use(monkeypatch, "jora", run)
    for i in range(3):
        world.add(f"Dead Clerk {i}")
    for _ in range(4):
        stats = review(world)
    assert len(calls) == 3 and len(set(calls)) == 3             # was 3, 6, 9, 12
    assert stats["skipped_same"] == 3 and stats["fetched"] == 0
    rows = [tuple(r) for r in world.conn.execute("SELECT tries, last_status FROM ad_fetch")]
    assert rows == [(1, "gone")] * 3
    assert world.conn.execute("SELECT COUNT(*) FROM ad_text").fetchone()[0] == 0


def test_a_failed_ad_is_retried_after_24_hours_and_at_most_three_times(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(1) or adtext._note("gone") or "")
    pid = world.add("Dead Clerk")
    review(world)
    age_fetch_log(world.conn, 23)
    review(world)
    assert len(calls) == 1                                      # 23 h: too soon
    for expect in (2, 3):
        age_fetch_log(world.conn, 25)
        review(world)
        assert len(calls) == expect
    age_fetch_log(world.conn, 24 * 30)
    review(world)
    assert len(calls) == 3                                      # three tries and never again
    assert world.conn.execute("SELECT tries FROM ad_fetch WHERE posting_id=?", (pid,)).fetchone()[0] == 3
    assert adtext.fetch_due(world.conn, pid) is False


def test_a_good_fetch_is_stored_in_ad_text_and_never_repeated(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(1) or LONG)
    pid = world.add("Clerk")
    assert review(world)["reviewed"] == 1
    assert adtext.get_text(world.conn, pid) == (LONG[:adtext.MAX_TEXT], "jora_detail")
    assert world.conn.execute("SELECT last_status FROM ad_fetch").fetchone()[0] == "ok"
    review(world, redo=True)
    assert len(calls) == 1
    assert world.conn.execute("SELECT text_source FROM ad_reviews").fetchone()[0] == "full"


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
def test_connection_errors_count_against_the_budget_are_paced_and_stop_the_host(world, monkeypatch):
    calls = []

    def run(ref):
        calls.append(ref.source_id)
        raise ConnectionResetError("reset by peer")

    use(monkeypatch, "jora", run)
    for i in range(10):
        world.add(f"Clerk {i}")
    stats = review(world)
    assert len(calls) == adtext.HOST_FAIL_LIMIT == 3            # was one unpaced request per pending ad
    assert stats["fetched"] == 3 and len(world.paces) == 3
    assert "3 failed fetches in a row" in stats["stopped"]
    assert stats["reviewed"] == 10                              # every ad is still read, from its teaser
    log = [tuple(r) for r in world.conn.execute("SELECT tries, last_status FROM ad_fetch")]
    assert len(log) == 3 and all(t == 1 and s.startswith("error: ConnectionResetError") for t, s in log)


def test_a_timeout_or_any_exception_is_handled_like_a_failed_fetch(world, monkeypatch):
    errors = iter([TimeoutError("slow"), adtext.FetchError("response too large"), ValueError("odd")])
    use(monkeypatch, "jora", lambda ref: (_ for _ in ()).throw(next(errors)))
    for i in range(5):
        world.add(f"Clerk {i}")
    stats = review(world)
    assert stats["fetched"] == 3 and stats["reviewed"] == 5 and stats["errors"] == 0
    assert {r[0].split(":")[1].strip() for r in world.conn.execute("SELECT last_status FROM ad_fetch")} == {
        "TimeoutError", "FetchError", "ValueError"}


def test_failures_spend_the_fetch_budget_and_pace_like_a_normal_fetch(world, monkeypatch):
    world.config.settings["reader"]["seek_fetches_per_run"] = 2
    use(monkeypatch, "jora", lambda ref: adtext._note("gone") or "")        # not a host failure: only the budget stops it
    for i in range(6):
        world.add(f"Clerk {i}")
    stats = review(world)
    assert stats["fetched"] == 2 and len(world.paces) == 2 and stats["reviewed"] == 6
    assert world.conn.execute("SELECT COUNT(*) FROM ad_fetch").fetchone()[0] == 2


def test_a_block_status_stops_the_host_at_once_but_is_counted_and_paced(world, monkeypatch):
    def run(ref):
        raise adtext.Blocked("jora HTTP 429")

    use(monkeypatch, "jora", run)
    for i in range(4):
        world.add(f"Clerk {i}")
    stats = review(world)
    assert stats["fetched"] == 1 and len(world.paces) == 1 and stats["stopped"] == "jora HTTP 429"
    assert world.conn.execute("SELECT last_status FROM ad_fetch").fetchone()[0] == "blocked: jora HTTP 429"
    assert stats["reviewed"] == 4


def test_a_good_fetch_resets_the_run_of_failures(world, monkeypatch):
    plan = iter(["boom", "boom", "ok", "boom", "boom"])

    def run(ref):
        if next(plan) == "boom":
            raise OSError("reset")
        return LONG

    use(monkeypatch, "jora", run)
    for i in range(5):
        world.add(f"Clerk {i}")
    stats = review(world)
    assert stats["fetched"] == 5 and stats["stopped"] is None


def test_a_200_challenge_page_is_a_failure_and_three_stop_the_host(world, monkeypatch):
    requests = []

    def do_get(url, browser, timeout):
        requests.append(url)
        return adtext._Resp(200, url, (FIX / "jora_challenge.html").read_text(), "")

    monkeypatch.setattr(adtext, "_do_get", do_get)
    for i in range(6):
        world.add(f"Clerk {i}")                                 # real au.jora.com urls, so the real fetch_jora runs
    stats = review(world)
    assert len(requests) == 3 and "3 failed fetches in a row (wall)" in stats["stopped"]
    assert len(world.paces) == 3
    for _ in range(3):
        review(world)
    assert len(requests) == 6 and len(set(requests)) == 6      # every ad exactly once, however many runs follow
    assert {r[0] for r in world.conn.execute("SELECT last_status FROM ad_fetch")} == {"wall"}


def test_ads_the_reader_cannot_fetch_do_not_use_the_budget(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(1) or LONG)
    world.add("Long Ad", desc="The whole ad is in the feed. " * 40)                 # 1200 chars: nothing to fetch
    world.add("No Fetcher", source="ats_techone", url="https://example.com/x")
    stats = review(world)
    assert calls == [] and stats["fetched"] == 0 and world.paces == []


# ------------------------------------------------------- the cut description goes through the same loop
def test_a_cut_description_is_fetched_and_a_cut_one_without_a_fetcher_is_partial(world, monkeypatch):
    cut = ("Process invoices and answer supplier queries. " * 60)[:2000]
    seen = []
    use(monkeypatch, "ats_successfactors", lambda ref: seen.append(ref.source_id) or LONG * 2)
    fetched = world.add("Banking Consultant", source="ats_successfactors", desc=cut,
                        url="https://careers.example.com/job/x/1", source_id="careers.example.com:1")
    nofetch = world.add("Support Officer", source="ats_techone", desc=cut, url="https://careers.example.com/job/2")
    review(world)
    kinds = {r["posting_id"]: (r["text_source"], r["text_len"]) for r in world.conn.execute("SELECT * FROM ad_reviews")}
    assert seen == ["careers.example.com:1"]
    assert kinds[fetched] == ("full", len(LONG * 2)) and kinds[nofetch] == ("partial", len(cut.strip()))


# --------------------------------------------------- one bad ad never aborts the batch
def test_every_exception_for_one_posting_is_caught(world, monkeypatch):
    for title in ("Good One", "Decide Boom", "Store Boom", "Sponsor Boom", "Good Two"):
        world.add(title, desc="The whole ad is in the feed. " * 40)
    real_decide, real_store, real_sponsored = reader.decide, reader.store, reader.is_sponsored

    def decide(model_out, text, kind, cfg, sponsored=False, title="", **kwargs):
        if title == "Decide Boom":
            raise RuntimeError("rules crashed")
        return real_decide(model_out, text, kind, cfg, sponsored=sponsored, title=title, **kwargs)

    def store(conn, posting_id, *a, **kw):
        if posting_id == ids["Store Boom"]:
            raise RuntimeError("write crashed")
        return real_store(conn, posting_id, *a, **kw)

    def sponsored(raw):
        if raw and "Sponsor Boom" in raw:
            raise RuntimeError("raw crashed")
        return real_sponsored(raw)

    ids = {r["title"]: r["id"] for r in world.conn.execute("SELECT id, title FROM postings")}
    world.conn.execute("UPDATE postings SET raw_json=? WHERE id=?", (json.dumps({"x": "Sponsor Boom"}), ids["Sponsor Boom"]))
    world.conn.commit()
    monkeypatch.setattr(reader, "decide", decide)
    monkeypatch.setattr(reader, "store", store)
    monkeypatch.setattr(reader, "is_sponsored", sponsored)
    stats = review(world)
    done = {r["posting_id"] for r in world.conn.execute("SELECT posting_id FROM ad_reviews")}
    assert done == {ids["Good One"], ids["Good Two"]} and stats["reviewed"] == 2 and stats["errors"] == 3


def test_a_crashing_model_call_for_one_ad_does_not_stop_the_others(world, monkeypatch):
    for title in ("Good One", "Model Boom", "Good Two"):
        world.add(title, desc="The whole ad is in the feed. " * 40)
    real = reader.ask

    def ask(llm, model, posting, *a, **kw):
        if posting["title"] == "Model Boom":
            raise RuntimeError("client crashed")
        return real(llm, model, posting, *a, **kw)

    monkeypatch.setattr(reader, "ask", ask)
    stats = review(world)
    assert stats["reviewed"] == 2 and stats["model_failed"] == 1 and stats["errors"] == 1


# --------------------------------------------------- wall-clock budget
def test_review_pending_stops_starting_work_after_max_seconds(world):
    world.gw.delay = 0.3
    for i in range(6):
        world.add(f"Clerk {i}", desc="The whole ad is in the feed. " * 40)
    stats = review(world, max_seconds=0.4)
    assert 1 <= stats["reviewed"] < 6 and world.gw.calls == stats["reviewed"]
    assert str(6 - stats["reviewed"]) in stats["time_limit"] and "max_seconds=0" in stats["time_limit"]
    again = review(world)                                       # the rest is simply still pending
    assert again["reviewed"] == 6 - stats["reviewed"] and again["time_limit"] is None


def test_a_spent_budget_starts_nothing(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(1) or LONG)
    for i in range(3):
        world.add(f"Clerk {i}")
    stats = review(world, max_seconds=1e-9)
    assert calls == [] and world.gw.calls == 0 and stats["reviewed"] == 0 and "3 ads left" in stats["time_limit"]


def test_no_limit_by_default_for_the_cli(world):
    for i in range(3):
        world.add(f"Clerk {i}", desc="The whole ad is in the feed. " * 40)
    assert review(world)["time_limit"] is None


def test_after_collect_passes_the_configured_budget_down(world, monkeypatch):
    seen = []
    monkeypatch.setattr(reader, "review_pending", lambda conn, config, **kw: seen.append(kw["max_seconds"]) or {"x": 1})
    monkeypatch.setattr("jobwatch.recall.triage_new", lambda *a, **kw: {"asked": 0})
    reader.after_collect(world.conn, world.config)
    assert 470 < seen[0] <= 480                                 # default 480 s for the pipeline hook
    world.config.settings["reader"]["max_seconds"] = 100
    reader.after_collect(world.conn, world.config)
    assert 90 < seen[1] <= 100
    world.config.settings["reader"]["max_seconds"] = 0
    reader.after_collect(world.conn, world.config)
    assert seen[2] is None                                      # 0 = unlimited
    reader.after_collect(world.conn, world.config, max_seconds=50)
    assert 40 < seen[3] <= 50


def test_after_collect_stops_recall_between_batches_and_skips_the_review(world, monkeypatch):
    for i in range(90):                                         # three triage batches of 40
        world.add(f"Practice Coordinator {i}", match=False, desc="Front desk and billing")
    reviews = []
    monkeypatch.setattr(reader, "review_pending", lambda *a, **kw: reviews.append(1) or {})
    monkeypatch.setattr(reader, "LLM", lambda: llm_of(world))
    from jobwatch import recall
    monkeypatch.setattr(recall, "LLM", lambda: llm_of(world))
    out = reader.after_collect(world.conn, world.config, max_seconds=1e-9)
    assert world.gw.calls == 1                                  # one batch was asked, the loop then stopped
    assert out["recall"] == {"stopped": "max_seconds=0 reached"} and reviews == []
    assert "before the review started" in out["review"]["time_limit"]


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


def test_a_second_pipeline_hook_skips_quietly_while_the_first_runs(world, monkeypatch, caplog):
    world.add("Clerk", desc="The whole ad is in the feed. " * 40)
    monkeypatch.setattr(reader, "LLM", lambda: llm_of(world))
    with adtext.review_lock(adtext.lock_path(world.config)):
        with caplog.at_level("INFO"):
            out = reader.after_collect(world.conn, world.config)
    assert out["skipped"] == "busy" and "review.lock" in out["note"]
    assert world.gw.calls == 0 and "holds review.lock" in caplog.text
    assert world.conn.execute("SELECT COUNT(*) FROM ad_reviews").fetchone()[0] == 0
    out = reader.after_collect(world.conn, world.config)        # the lock is free again
    assert "skipped" not in out and out["review"]["reviewed"] == 1


def _args(**over):
    base = dict(cmd="review", action="run", config_dir=None, limit=None, posting=None, redo=False, model=None,
                workers=None, fetch=None)
    return types.SimpleNamespace(**{**base, **over})


def test_cli_review_and_recall_skip_while_another_run_holds_the_lock(world, monkeypatch, capsys):
    from jobwatch import review_cli
    confirm_discovery(world.config)
    monkeypatch.setenv("JOBWATCH_DB", str(world.config.db_path))
    ran = []
    monkeypatch.setattr(reader, "review_pending", lambda *a, **kw: ran.append(kw) or {"reviewed": 0})
    monkeypatch.setattr("jobwatch.recall.triage_new", lambda *a, **kw: ran.append("recall") or {"asked": 0})
    with adtext.review_lock(adtext.lock_path(world.config)):
        for action in ("run", "recall"):
            assert review_cli.handle(_args(action=action)) == 0
            assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["skipped"] == "busy"
    assert ran == []
    assert review_cli.handle(_args()) == 0 and review_cli.handle(_args(action="recall")) == 0
    assert len(ran) == 2 and ran[1] == "recall"
    assert "max_seconds" not in ran[0]                          # the CLI has no time limit


# --------------------------------------------------- the pipeline hook
def _pipeline_world(tmp_path, monkeypatch, order, confirmed=True):
    config = make_config(settings={"tiers": {"fast": [], "slow": []}}, tmp_path=tmp_path)
    if confirmed:
        confirm_discovery(config)       # the AI step runs only for a person whose profile was confirmed with its scope
    real_publish, real_prune = pipeline.publish, dbm.prune
    monkeypatch.setattr(pipeline, "publish", lambda conn, dry_run=False: order.append("publish") or real_publish(conn, dry_run))
    monkeypatch.setattr(dbm, "prune", lambda conn, days: order.append("prune") or real_prune(conn, days))
    return config


def test_pipeline_runs_the_ai_step_last_so_a_timeout_cannot_cost_publish_and_prune(tmp_path, monkeypatch):
    order = []
    config = _pipeline_world(tmp_path, monkeypatch, order)
    monkeypatch.setattr(reader, "after_collect", lambda conn, cfg, **kw: order.append("ai") or {"enabled": False})
    summary = pipeline.run(config, "fast")
    assert order == ["publish", "prune", "ai"] and summary["ai"] == {"enabled": False, "execution_mode": "reader"}


def test_pipeline_survives_a_crashing_ai_step(tmp_path, monkeypatch):
    config = _pipeline_world(tmp_path, monkeypatch, [])

    def boom(conn, cfg, **kw):
        raise RuntimeError("lock dir gone")

    monkeypatch.setattr(reader, "after_collect", boom)
    summary = pipeline.run(config, "fast")
    assert summary["ai"]["error"].startswith("RuntimeError")
    conn = dbm.connect(config.db_path)
    assert conn.execute("SELECT finished_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]


# --------------------------------------------------- rederive uses the reader's text kinds
def test_rederive_and_review_pending_agree_on_full_partial_and_teaser(world):
    cut = ("Process invoices and answer supplier queries. " * 60)[:2000]
    whole = "<p>" + "Process invoices and answer supplier queries. " * 80 + "</p>"
    world.add("Teaser", source="ats_techone", desc="short teaser", url="https://example.com/1")
    world.add("Whole", source="ats_techone", desc="The whole ad is in the feed. " * 40, url="https://example.com/2")
    world.add("Cut", source="ats_techone", desc=cut, url="https://example.com/3")
    world.add("Raw", source="ats_greenhouse", desc=cut, url="https://example.com/4", raw={"content": whole})
    fetched = world.add("Fetched", source="ats_techone", desc=cut, url="https://example.com/5")
    adtext.save_text(world.conn, fetched, LONG, "test")
    review(world)
    q = "SELECT p.title, r.text_source, r.text_len FROM ad_reviews r JOIN postings p ON p.id=r.posting_id ORDER BY p.id"
    before = [tuple(r) for r in world.conn.execute(q)]
    assert [b[:2] for b in before] == [("Teaser", "teaser"), ("Whole", "full"), ("Cut", "partial"), ("Raw", "full"),
                                       ("Fetched", "full")]
    world.conn.execute("UPDATE ad_reviews SET text_source='full'")     # what the old code stored for every cut ad
    world.conn.commit()
    out = reader.rederive(world.conn, world.config)
    assert out["checked"] == 5
    assert [tuple(r) for r in world.conn.execute(q)][:5] == [b[:2] + (r[2],) for b, r in zip(before, world.conn.execute(q))]
    assert [r[1] for r in world.conn.execute(q)] == ["teaser", "full", "partial", "full", "full"]


def test_rederive_holds_an_old_cut_review_that_was_labelled_full(world):
    cut = ("Process invoices and answer supplier queries. " * 60)[:2000]
    pid = world.add("Cut Ad", source="ats_techone", desc=cut, url="https://example.com/3")
    review(world)
    world.conn.execute("UPDATE ad_reviews SET text_source='full', verdict='show', hide_reason=NULL")
    world.conn.commit()
    reader.rederive(world.conn, world.config)
    row = world.conn.execute("SELECT text_source, verdict FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert tuple(row) == ("partial", "review")                  # shown only on a cut text -> held for a look


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


def test_the_stored_hosts_gate_the_reader_fetch_for_a_jsonld_row(world, monkeypatch):
    def do_get(url, browser, timeout):
        raise AssertionError(f"no request expected, got {url}")

    monkeypatch.setattr(adtext, "_do_get", do_get)
    raw = {"_site_hosts": ["careers.example.vic.gov.au"]}
    pid = world.add("Payroll Officer", source="jsonld_pages", url="https://127.0.0.1.nip.io/hook?x=1", raw=raw,
                    source_id="Example Council:abc")
    stats = review(world)                                       # refused up front: no slot, no pause, no logged try
    assert stats["fetched"] == 0 and adtext.get_text(world.conn, pid) is None and world.paces == []
    assert world.conn.execute("SELECT COUNT(*) FROM ad_fetch").fetchone()[0] == 0


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
def test_postings_a_fetcher_would_refuse_cost_no_slot_pause_or_logged_try(world, monkeypatch):
    def do_get(url, browser, timeout):
        raise AssertionError(f"no request expected, got {url}")

    monkeypatch.setattr(adtext, "_do_get", do_get)
    cut = ("Process invoices and answer supplier queries. " * 60)[:2000]
    indeed = world.add("Indeed Clerk", source="jobspy_src", desc=cut, source_id="indeed:in-abc123def",
                       url="https://au.indeed.com/viewjob?jk=abc123def", raw={"site": "indeed", "id": "in-abc123def"})
    nonsense = world.add("Odd Clerk", source="jora", desc="short teaser", url="https://example.com/job/x")
    for _ in range(3):
        stats = review(world, redo=True)
    assert stats["fetched"] == 0 and world.paces == []
    assert world.conn.execute("SELECT COUNT(*) FROM ad_fetch").fetchone()[0] == 0
    kinds = {r["posting_id"]: r["text_source"] for r in world.conn.execute("SELECT * FROM ad_reviews")}
    assert kinds == {indeed: "partial", nonsense: "teaser"}
    row = world.conn.execute("SELECT * FROM postings WHERE id=?", (indeed,)).fetchone()
    assert adtext.wants_fetch(world.conn, row) is False


def test_a_refused_ad_does_not_crowd_real_ads_out_of_the_budget(world, monkeypatch):
    seen = []
    use(monkeypatch, "jora", lambda ref: seen.append(ref.source_id) or LONG)
    world.config.settings["reader"]["fetches_per_run"] = 2
    for i in range(3):                                          # newer than the real ads: they are asked first
        world.add(f"Indeed {i}", source="jobspy_src", desc="short", source_id=f"indeed:in-{i}",
                  url=f"https://au.indeed.com/viewjob?jk={i}", raw={"site": "indeed"})
    real = [world.add(f"Real {i}", source_id=f"real-{i}") for i in range(2)]
    # the replaced jora fetcher has no dry check (test double) and runs; the Indeed rows never reach any fetcher
    stats = review(world)
    assert sorted(seen) == ["real-0", "real-1"] and stats["fetched"] == 2 and len(real) == 2


# --------------------------------------------------- round 2: --posting and --refetch override the fetch log
def _exhaust_log(world, pid):
    for _ in range(adtext.FETCH_MAX_TRIES):
        adtext._record_fetch(world.conn, pid, "blocked: jora HTTP 429")


def test_pipeline_runs_keep_the_cap_but_posting_and_refetch_bypass_it(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(ref.source_id) or LONG)
    pid = world.add("Stuck Clerk")
    _exhaust_log(world, pid)
    review(world)
    assert calls == []                                          # a normal run: 3 tries used, so no request
    review(world, posting_ids=[pid])
    assert calls == ["Stuck-Clerk"]
    assert adtext.get_text(world.conn, pid) is not None


def test_refetch_bypasses_the_24h_wait_and_the_try_cap_for_pending_ads(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(ref.source_id) or adtext._note("wall") or "")
    pid = world.add("Waiting Clerk")
    review(world)
    assert len(calls) == 1                                      # first try; now within the 24 h wait
    review(world)
    assert len(calls) == 1
    review(world, refetch=True)
    assert len(calls) == 2
    _exhaust_log(world, pid)
    review(world, refetch=True)
    assert len(calls) == 3
    review(world)
    assert len(calls) == 3                                      # without the flag the cap holds again


def test_cli_refetch_flag_reaches_review_pending(world, monkeypatch):
    from jobwatch import review_cli
    confirm_discovery(world.config)
    monkeypatch.setenv("JOBWATCH_DB", str(world.config.db_path))
    seen = []
    monkeypatch.setattr(reader, "review_pending", lambda *a, **kw: seen.append(kw) or {"reviewed": 0})
    assert review_cli.handle(_args(refetch=True)) == 0 and review_cli.handle(_args()) == 0
    assert seen[0]["refetch"] is True and seen[1]["refetch"] is False


# --------------------------------------------------- round 2: rederive takes review.lock
def test_cli_rederive_exits_1_without_touching_rows_while_a_review_runs(world, monkeypatch, capsys):
    from jobwatch import review_cli
    confirm_discovery(world.config)
    monkeypatch.setenv("JOBWATCH_DB", str(world.config.db_path))
    pid = world.add("Clerk", desc="The whole ad is in the feed. " * 40)
    review(world)
    world.conn.execute("UPDATE ad_reviews SET verdict='hide', hide_reason='x'")
    world.conn.commit()
    with adtext.review_lock(adtext.lock_path(world.config)):
        assert review_cli.handle(_args(action="rederive")) == 1
    assert "review.lock" in capsys.readouterr().out
    row = world.conn.execute("SELECT verdict, hide_reason FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert tuple(row) == ("hide", "x")                          # untouched
    assert review_cli.handle(_args(action="rederive")) == 0     # lock free: it runs
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"checked": 1, "changed": 1}


# --------------------------------------------------- round 2: partial is reported like teaser
def test_review_stats_and_printer_count_partial_like_teaser(world, capsys, monkeypatch):
    from jobwatch import review_cli
    cut = ("Process invoices and answer supplier queries. " * 60)[:2000]
    world.add("Teaser Clerk", source="ats_techone", desc="short", url="https://example.com/1")
    world.add("Cut Clerk", source="ats_techone", desc=cut, url="https://example.com/2")
    world.add("Whole Clerk", source="ats_techone", desc="The whole ad is in the feed. " * 40, url="https://example.com/3")
    lines = []
    stats = review(world, printer=lines.append)
    assert (stats["teaser"], stats["partial"], stats["reviewed"]) == (1, 1, 3)
    assert sum("[teaser]" in x for x in lines) == 1 and sum("[partial]" in x for x in lines) == 1
    monkeypatch.setenv("JOBWATCH_DB", str(world.config.db_path))
    assert review_cli.handle(_args(action="stats")) == 0
    assert "1 from a teaser only, 1 from a cut text only" in capsys.readouterr().out


# --------------------------------------------------- round 2: the run's wall clock
def test_ai_budget_is_what_is_left_of_the_unit_time():
    now = time.monotonic()
    assert 775 < pipeline.ai_budget(now) <= 780
    assert 375 < pipeline.ai_budget(now - 400) <= 380
    assert pipeline.ai_budget(now - 5000) == 0                  # an exhausted invocation has no remaining time
    cfg = make_config(settings={"reader": {"max_seconds": 100}})
    assert pipeline.ai_budget(now, cfg) == 100                  # the owner's own, lower limit still counts
    assert 375 < pipeline.ai_budget(now - 400, make_config(settings={"reader": {"max_seconds": 0}})) <= 380


def test_pipeline_hands_the_ai_step_the_remaining_time_and_records_the_run_even_if_it_dies(tmp_path, monkeypatch):
    config = _pipeline_world(tmp_path, monkeypatch, [])
    seen = []
    monkeypatch.setattr(reader, "after_collect", lambda conn, cfg, **kw: seen.append(kw["max_seconds"]) or {"x": 1})
    pipeline.run(config, "fast")
    assert 60 <= seen[0] <= 780

    def interrupted(conn, cfg, **kw):
        raise KeyboardInterrupt()                               # not an Exception: the old code lost finish_run here

    monkeypatch.setattr(reader, "after_collect", interrupted)
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(config, "fast")
    conn = dbm.connect(config.db_path)
    assert conn.execute("SELECT finished_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]


def test_after_collect_gives_recall_its_remaining_time_when_recall_accepts_it(world, monkeypatch):
    got = {}
    monkeypatch.setattr(reader, "review_pending", lambda *a, **kw: {})
    monkeypatch.setattr("jobwatch.recall.triage_new",
                        lambda conn, config, *, limit=1, llm=None, printer=None, max_seconds=None: got.update(m=max_seconds) or {})
    reader.after_collect(world.conn, world.config, max_seconds=100)
    assert 90 < got["m"] <= 100
    got.clear()
    monkeypatch.setattr("jobwatch.recall.triage_new", lambda conn, config, *, limit=1, llm=None, printer=None: got.update(old=1) or {})
    reader.after_collect(world.conn, world.config, max_seconds=100)     # an older recall without the parameter still works
    assert got == {"old": 1}


# --------------------------------------------------- round 2: legacy jsonld_pages rows
def test_a_jsonld_row_without_its_own_host_list_is_fetched_only_from_registry_hosts(world, monkeypatch):
    asked = []

    def do_get(url, browser, timeout):
        asked.append(url)
        return adtext._Resp(404, url, "", "")

    monkeypatch.setattr(adtext, "_do_get", do_get)
    world.config.employers = [{"name": "Example Council", "provider": "jsonld", "enabled": False,
                               "careers_url": "https://www.careers.example.vic.gov.au/careers"}]
    legacy = world.add("Payroll Officer", source="jsonld_pages", source_id="Example Council:1", raw={"title": "x"},
                       url="https://careers.example.vic.gov.au/jobs/1")
    hook = world.add("Hook Officer", source="jsonld_pages", source_id="Example Council:2", raw={"title": "x"},
                     url="https://127.0.0.1.nip.io/hook?x=1")
    stats = review(world)
    assert asked == ["https://careers.example.vic.gov.au/jobs/1"] and stats["fetched"] == 1
    assert world.conn.execute("SELECT COUNT(*) FROM ad_fetch WHERE posting_id=?", (hook,)).fetchone()[0] == 0
    assert legacy and world.conn.execute("SELECT last_status FROM ad_fetch WHERE posting_id=?", (legacy,)).fetchone()[0] == "gone"


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


def test_ads_that_cannot_be_read_again_do_not_use_the_limit(world, monkeypatch):
    calls = []
    _stuck_indeed(world)
    retry = world.add("Retry Clerk")                            # a jora teaser: its first fetch fails, then it can be retried
    use(monkeypatch, "jora", lambda ref: calls.append(ref.source_id) or adtext._note("gone") or "")
    first = review(world)
    assert first["reviewed"] == 4 and calls == ["Retry-Clerk"]
    age_fetch_log(world.conn, 25)
    use(monkeypatch, "jora", lambda ref: calls.append(ref.source_id) or LONG)
    stats = review(world, limit=1)                              # the 3 Indeed rows (skipped_same) are ahead of it
    assert stats["skipped_same"] == 3 and stats["fetched"] == 1 and stats["reviewed"] == 1, stats
    assert calls == ["Retry-Clerk", "Retry-Clerk"]
    assert world.conn.execute("SELECT text_source FROM ad_reviews WHERE posting_id=?", (retry,)).fetchone()[0] == "full"


def test_the_limit_still_stops_after_that_many_ads_that_need_a_model_call(world):
    for i in range(5):
        world.add(f"Clerk {i}", desc="The whole ad is in the feed. " * 40)
    stats = review(world, limit=2)
    assert stats["reviewed"] == 2 and world.gw.calls == 2 and stats["pending"] == 5
    assert review(world, limit=0)["reviewed"] == 3             # no limit: the rest


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


@pytest.mark.parametrize("left, want", [(500, 180), (180, 180), (100, 100), (20, 20), (5, 10), (-3, 10)])
def test_each_attempt_waits_at_most_what_is_left_but_at_least_ten_seconds(monkeypatch, left, want):
    clock = _Clock()
    monkeypatch.setattr(reader.time, "monotonic", clock)
    calls, gw = _timed_gateway(clock, 0, [json.dumps(ANSWER)])
    out, _ = reader.ask(LLM(transport=gw, keys=["k"]), "claude/sonnet", _POSTING, "Process invoices.", "full", "P", 9000,
                        deadline=clock.t + left)
    assert out and calls == [want]


def test_no_deadline_keeps_the_old_180_second_timeout(monkeypatch):
    calls, gw = _timed_gateway(_Clock(), 0, [json.dumps(ANSWER)])
    reader.ask(LLM(transport=gw, keys=["k"]), "claude/sonnet", _POSTING, "x", "full", "P", 9000)
    assert calls == [180]


def test_no_second_attempt_when_less_than_thirty_seconds_are_left(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(reader.time, "monotonic", clock)
    calls, gw = _timed_gateway(clock, 80, ["not json at all"])         # the first attempt takes 80 s and is not valid JSON
    out = reader.ask(LLM(transport=gw, keys=["k"]), "claude/sonnet", _POSTING, "x", "full", "P", 9000, deadline=clock.t + 100)
    assert out == (None, None) and calls == [100]                      # 20 s left: no retry
    clock.t = 1000.0
    calls, gw = _timed_gateway(clock, 80, ["not json at all", json.dumps(ANSWER)])
    out, _ = reader.ask(LLM(transport=gw, keys=["k"]), "claude/sonnet", _POSTING, "x", "full", "P", 9000, deadline=clock.t + 150)
    assert out and calls == [150, 70]                                  # 70 s left: retried, with 70 s


def test_a_review_run_hands_every_model_call_its_remaining_budget(world, monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(reader.time, "monotonic", clock)
    calls, gw = _timed_gateway(clock, 45, [json.dumps(ANSWER)])
    world.add("Clerk One", desc="The whole ad is in the feed. " * 40)
    world.add("Clerk Two", desc="The whole ad is in the feed. " * 40)
    stats = reader.review_pending(world.conn, world.config, llm=LLM(transport=gw, keys=["k"]), limit=10, max_seconds=60)
    assert calls == [60, 15] and stats["reviewed"] == 2                # the second call could never outlive the 60 s budget
    clock.t = 1000.0
    world.conn.execute("DELETE FROM ad_reviews")
    world.conn.commit()
    calls.clear()
    stats = reader.review_pending(world.conn, world.config, llm=LLM(transport=gw, keys=["k"]), limit=10, max_seconds=30)
    assert calls == [30] and stats["reviewed"] == 1 and "1 ads left" in stats["time_limit"]       # 45 s taken: the rest waits


def test_after_collect_passes_the_unit_budget_down_to_the_model_calls(world, monkeypatch):
    seen = {}
    monkeypatch.setattr("jobwatch.recall.triage_new", lambda *a, **kw: {})
    monkeypatch.setattr(reader, "LLM", lambda: llm_of(world))        # after_collect builds its own client: a fake one
    real_ask = reader.ask
    monkeypatch.setattr(reader, "ask", lambda *a, **kw: seen.setdefault("deadline", kw.get("deadline")) and real_ask(*a, **kw))
    world.add("Clerk One", desc="The whole ad is in the feed. " * 40)
    reader.after_collect(world.conn, world.config, max_seconds=780)
    assert seen["deadline"] is not None and 700 < seen["deadline"] - time.monotonic() <= 780


# --------------------------------------------------- round 3: --redo with --posting forces only the named ads
def test_redo_with_posting_refetches_only_the_named_ads(world, monkeypatch):
    calls = []
    use(monkeypatch, "jora", lambda ref: calls.append(ref.source_id) or LONG)
    named, other = world.add("Named Clerk"), world.add("Other Clerk")
    _exhaust_log(world, named)
    _exhaust_log(world, other)
    stats = review(world, redo=True, posting_ids=[named])
    assert calls == ["Named-Clerk"] and stats["fetched"] == 1       # the other redo row keeps the 3-try cap
    assert world.conn.execute("SELECT COUNT(*) FROM ad_text").fetchone()[0] == 1
    review(world, redo=True, refetch=True)                          # --refetch still forces every row
    assert calls == ["Named-Clerk", "Other-Clerk"]                  # (the named ad is already read in full)


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


def test_a_clean_run_has_no_error_field(tmp_path, monkeypatch):
    config = _pipeline_world(tmp_path, monkeypatch, [])
    monkeypatch.setattr(reader, "after_collect", lambda conn, cfg, **kw: {"enabled": False})
    assert "error" not in pipeline.run(config, "fast")


def test_pipeline_gate_skips_every_tier_without_a_confirmed_profile(tmp_path, monkeypatch):
    from jobwatch import execution_mode
    import pipeline.graph as graph
    from pipeline.agentic import service as agentic
    config = _pipeline_world(tmp_path, monkeypatch, [], confirmed=False)
    called = []
    for mod in (reader, graph, agentic):
        monkeypatch.setattr(mod, "after_collect", lambda *a, **k: called.append(1) or {})
    for mode in ("agentic", "pipeline", "reader"):
        monkeypatch.setattr(execution_mode, "effective_mode", lambda cfg, m=mode: m)
        assert pipeline.run(config, "fast")["ai"] == {"skipped": "no_confirmed_profile", "execution_mode": mode}
    assert called == []
