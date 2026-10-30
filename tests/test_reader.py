"""AI ad reader and AI recall: the hiding rules in code, the cache, and the model calls (fake transport)."""
from jobwatch.settings import DEFAULT_MODEL
import json

import pytest

from conftest import make_config
from jobwatch.util import adtext as adtext
from jobwatch import reader, recall
from jobwatch import db as dbm
from jobwatch.util.llm import LLM
from jobwatch.models import Posting
from jobwatch.dedupe import ingest

CFG = dict(reader.DEFAULTS)


def model(**over):
    """A v3 (career-ops style) evaluation as the model returns it. Keyword overrides: top-level keys, plus
    rights/quote/hours/loc/seniority/years/score shortcuts."""
    base = {"real_job": True, "ad_kind": "employer", "archetype": "Accounts & Administration",
            "tldr": "Entry-level accounts role.",
            "role": {"seniority": "junior", "work_mode": "onsite", "hours": "part_time_ok", "location_fit": "inner",
                     "min_years": None},
            "authorization": {"requirement": "none_stated", "quote": ""},
            "requirements": [{"requirement": "Process invoices", "importance": "critical", "tier": "inferred",
                              "jd_signal": "", "match": "strong", "evidence": "Reconciliations in the CV"}],
            "gaps": [], "dimensions": {"cv_match": 4, "north_star": 4, "comp": 3, "culture": 3, "red_flags": 5},
            "score": 4.1, "recommendation": "apply", "legitimacy": {"tier": "high", "signals": []},
            "comp": {"company_type": "SMB", "reliability": "Low"}, "reason": "Entry-level accounts role."}
    rights, quote = over.pop("rights", None), over.pop("quote", "")
    for key, field in (("hours", "hours"), ("loc", "location_fit"), ("seniority", "seniority"), ("years", "min_years")):
        if key in over:
            base["role"][field] = over.pop(key)
    if rights:
        base["authorization"] = {"requirement": rights, "quote": quote}
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def confirmed_candidate(monkeypatch):
    """Synthetic confirmed facts, never the former default owner's assumed visa or preferences."""
    from jobwatch.candidate.policy import build_policy
    approved = {'version': 1, 'facts': [
        {'id': 'r', 'section': 'work_rights', 'basis': 'evidence', 'value': {
            'citizen': False, 'permanent_resident': False, 'valid_work_rights': True,
            'unrestricted_work_rights': False}},
        {'id': 's', 'section': 'skill', 'basis': 'evidence', 'value': 'Accounting graduate. MYOB.'}]}
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda *args, **kwargs: build_policy(approved))
    monkeypatch.setattr('jobwatch.candidate.intake.current_version', lambda person: approved)
    return approved


# ------------------------------------------------------------------------------ hiding rules (decide)
def test_good_ad_is_shown_with_a_score_out_of_five():
    v = reader.decide(model(), "Process invoices. Excel needed.", "full", CFG, title="Accounts Clerk")
    assert (v["verdict"], v["hide_reason"], v["score"], v["fit"]) == ("show", None, 4.1, 82)
    assert v["archetype"] == "Accounts & Administration" and v["report"]["requirements"][0]["match"] == "strong"


def test_citizenship_claim_needs_a_real_quote():
    text = "You must be an Australian citizen or permanent resident. Apply now."
    hit = reader.decide(model(rights="citizen_or_pr", quote="must be an Australian citizen or permanent resident"),
                        text, "full", CFG, title="Clerk")
    assert (hit["verdict"], hit["hide_reason"], hit["rights"]) == ("hide", "work_rights_incompatible", "citizen_or_pr")
    assert hit["score"] == 4.1  # Eligibility does not rewrite the model comparison score.
    fake = reader.decide(model(rights="citizen_or_pr", quote="Australian citizens only"),
                         "A friendly team. Visa holders welcome.", "full", CFG, title="Clerk")
    # a claim that cannot be shown in the ad never lets the job through: it is held for review (rule 1 fails closed)
    assert fake["verdict"] == "review" and fake["hide_reason"] is None and "rights_claim_unverified" in fake["flags"]
    assert fake["rights"] == "none_stated"


def test_rule_backstop_catches_what_the_model_missed():
    v = reader.decide(model(), "Applicants must be Australian citizens or permanent residents.", "full", CFG, title="Clerk")
    assert (v["verdict"], v["hide_reason"]) == ("hide", "work_rights_incompatible") and "rights_found_by_rule" in v["flags"]


def test_unrestricted_work_rights_exclude_but_plain_right_to_work_does_not():
    hit = reader.decide(model(), "Candidates need unrestricted Australian work rights.", "full", CFG, title="Clerk")
    assert (hit["verdict"], hit["hide_reason"], hit["rights"]) == ("hide", "work_rights_incompatible", "unrestricted_work_rights")
    ok = reader.decide(model(rights="valid_work_rights", quote="right to work in Australia"),
                       "Must have the right to work in Australia.", "full", CFG, title="Clerk")
    assert ok["verdict"] == "show" and ok["rights"] == "valid_work_rights"


@pytest.mark.parametrize("text", [
    "We welcome applicants regardless of citizenship status.",
    "Citizenship is not required. Visa holders with work rights may apply.",
    "Must have the right to work in Australia (full working rights).",
    "Australian citizens are welcome to apply alongside visa holders.",
    "You will liaise with the PR and communications team.",
])
def test_equal_opportunity_and_plain_work_rights_do_not_hide(text):
    v = reader.decide(model(), text, "full", CFG, title="Clerk")
    assert v["verdict"] == "show", text


def test_aps_title_alone_needs_verified_ad_requirements():
    v = reader.decide(model(), "Corporate support in Canberra.", "full", CFG, title="APS4 Corporate Administration Officer")
    assert (v["verdict"], v["hide_reason"]) == ("review", None)


def test_unconfirmed_hours_and_model_distance_labels_do_not_exclude_or_cap_score():
    ft = reader.decide(model(hours="full_time_only", score=4.6), "x", "full", CFG)
    assert (ft["verdict"], ft["hide_reason"], ft["score"]) == ("show", None, 4.6)
    far = reader.decide(model(loc="out_of_scope", score=4.2), "x", "full", CFG)
    assert (far["verdict"], far["hide_reason"], far["score"]) == ("show", None, 4.2)
    assert reader.decide(model(hours="casual"), "x", "full", CFG)["verdict"] == "show"
    assert reader.decide(model(loc="remote"), "x", "full", CFG)["verdict"] == "show"


def test_other_hide_reasons_and_order():
    assert reader.decide(model(real_job=False, ad_kind="talent_pool", score=2.0), "x", "full", CFG)["verdict"] == "review"
    assert reader.decide(model(real_job=False, ad_kind="other"), "x", "full", CFG)["hide_reason"] == "not_a_real_job"
    assert reader.decide(model(seniority="senior"), "x", "full", CFG)["verdict"] == "show"
    assert reader.decide(model(years=5), "x", "full", CFG)["verdict"] == "show"
    assert reader.decide(model(score=2.4), "x", "full", CFG)["verdict"] == "show"
    assert reader.decide(model(score=3.4), "x", "full", CFG)["verdict"] == "show"
    assert reader.decide(model(score=3.5), "x", "full", CFG)["verdict"] == "show"
    held = reader.decide(model(score="n/a"), "x", "full", CFG)                  # no score: held, never a permanent hide
    assert (held["verdict"], held["hide_reason"]) == ("review", None) and "score_invalid" in held["flags"]
    # a paid ad is hidden first, even if the model liked it
    assert reader.decide(model(), "x", "full", CFG, sponsored=True)["hide_reason"] == "sponsored_ad"


def test_requirement_rows_follow_the_career_ops_gate():
    ad = "Requirements: you must have a degree in accounting. Nice to have: Xero."
    rows = reader.decide(model(requirements=[
        {"requirement": "Degree", "importance": "critical", "tier": "stated", "jd_signal": "you must have a degree in accounting",
         "match": "strong", "evidence": "BBus"},
        {"requirement": "Invented", "importance": "critical", "tier": "stated", "jd_signal": "must hold a unicorn",
         "match": "missing", "evidence": ""},
        {"requirement": "Market guess", "importance": "high", "tier": "inferred", "jd_signal": "", "match": "partial",
         "evidence": ""}]), ad, "full", CFG)["report"]["requirements"]
    assert (rows[0]["importance"], rows[0]["tier"]) == ("critical", "stated")
    assert (rows[1]["importance"], rows[1]["tier"], rows[1]["jd_signal"]) == ("meaningful", "inferred", "")   # quote not in the ad
    assert rows[2]["importance"] == "meaningful"                                                          # inferred never high


def test_unread_ad_is_held_not_shown():
    v = reader.decide(model(), "short teaser", "teaser", CFG, title="Clerk")
    assert v["verdict"] == "review" and "ad_text_not_read" in v["flags"]


def test_failed_reading_is_held_and_sponsored_still_hidden():
    assert reader.decide(None, "x", "full", CFG)["verdict"] == "review"
    assert reader.decide(None, "x", "teaser", CFG, sponsored=True)["hide_reason"] == "sponsored_ad"


def test_sponsored_detection_from_seek_json():
    assert reader.is_sponsored(json.dumps({"displayType": "promoted", "isFeatured": True}))
    assert reader.is_sponsored(json.dumps({"solMetadata": {"jobAdType": "SPONSORED"}}))
    assert not reader.is_sponsored(json.dumps({"displayType": "standard", "isFeatured": False,
                                               "solMetadata": {"jobAdType": "ORGANIC"}}))
    assert not reader.is_sponsored("not json")
    # Jora: the card link carries its own paid-placement flag
    assert reader.is_sponsored(json.dumps({"badges": ["New to you"], "href": "/job/Clerk-0123?sp=sserp&sponsored=true&disallow=true"}))
    assert not reader.is_sponsored(json.dumps({"badges": ["New to you"], "href": "/job/Clerk-0123?sp=serp&sponsored=false"}))


def test_model_output_is_clamped_and_cleaned():
    v = reader.decide(model(score=900, reason="x" * 999, gaps=[{"gap": "g" * 500, "risk": "r", "mitigation": "m"}] * 9,
                            archetype="y" * 500, years="two"), "x", "full", CFG)
    assert v["score"] == 5.0 and len(v["reason"]) <= 240 and len(v["report"]["gaps"]) == reader.MAX_GAPS
    assert len(v["archetype"]) <= 80 and v["min_years"] == 2           # "two" is read as 2


def test_contact_lines_are_removed_from_the_cv_before_it_is_sent():
    cv = "Name Surname\nSuburb | 0400 000 000 | someone@example.com | linkedin.com/in/x\nAccounting graduate\nMYOB, Excel"
    out = reader.strip_contact(cv)
    assert "@" not in out and "0400" not in out and "linkedin" not in out and "MYOB, Excel" in out


def test_seek_page_parser_reads_the_ad_body():
    page = ('<html><script>window.SEEK_REDUX_DATA = {"jobdetails": {"result": {"job": '
            '{"content": "<p>Process <b>payroll</b>.</p><ul><li>Excel</li></ul>"}}}};\n</script></html>')
    text = adtext.parse_seek_page(page)
    assert "Process payroll" in text and "Excel" in text and "<" not in text
    assert adtext.parse_seek_page("<html>nothing</html>") == ""


# ------------------------------------------------------------------------------- model calls (fake)
class FakeGateway:
    """Stands in for OmniRoute: returns a reading chosen by the job title in the prompt."""

    def __init__(self, readings=None, fail=False, triage=None, bad_json_first=False):
        self.readings, self.fail, self.triage, self.calls = readings or {}, fail, triage or {}, []
        self.prompts, self.bad_json_first, self.failed_once = [], bad_json_first, set()

    def __call__(self, url, headers, body, timeout):
        text = "\n".join(m["content"] for m in body["messages"])
        self.calls.append(body["model"])
        self.prompts.append(text)
        if self.fail:
            return 500, {"error": {"message": "boom"}}
        if "Triage recall only" in text:
            ids = [int(line.split(" | ")[0]) for line in text.split("JOBS (id | title | company | place | start of ad):\n")[1].splitlines() if line.strip()]
            out = {"results": [{"id": i, "relevant": self.triage.get(i, True)} for i in ids]}
        else:
            title = text.split("Title: ", 1)[1].splitlines()[0]
            out = self.readings.get(title, model())
            if self.bad_json_first and title not in self.failed_once:
                self.failed_once.add(title)
                return 200, {"model": body["model"], "choices": [{"message": {"content": "sorry, no json"}}]}
        return 200, {"model": body["model"], "choices": [{"message": {"content": json.dumps(out)}}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 50}}


def make_llm(gw):
    return LLM(transport=gw, keys=["test-key"])


@pytest.fixture
def world(tmp_path, monkeypatch):
    pdir = tmp_path / "profile"
    pdir.mkdir()
    (pdir / "career_ops_profile.md").write_text("Target roles: accounts, customer service. Policy: part-time only.")
    (pdir / "cv.md").write_text("Jane Doe\nSomewhere | 0400 000 000 | jane@example.com\nAccounting graduate. MYOB.")
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(pdir))
    config = make_config(tmp_path=tmp_path, settings={"reader": {"seek_delay": 0, "workers": 2}})
    conn = dbm.connect(config.db_path)

    def add(title, source="ats_pageup", desc="x " * 500, raw=None, match=True, company="Acme", location="Melbourne VIC"):
        p = Posting(source=source, source_id=title.replace(" ", "-"), url=f"https://example.com/{title.replace(' ', '-')}",
                    title=title, company=company, location=location, description=desc, raw=raw or {})
        pid, _ = ingest(conn, p)
        if match:
            conn.execute("INSERT INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, matched_at) "
                         "VALUES(?,?,?,?,?,?,?)", (pid, "general_clerk", "core", "[]", "{}", "[]", dbm.ts()))
        conn.commit()
        return pid

    return config, conn, add


def test_review_pending_reads_stores_and_caches(world):
    config, conn, add = world
    good = add("Accounts Clerk")
    bad = add("Payroll Officer", desc="You must be an Australian citizen to apply. " * 30)
    gw = FakeGateway({"Payroll Officer": model(rights="citizen_or_pr", quote="must be an Australian citizen", score=4.5)})
    stats = reader.review_pending(conn, config, llm=make_llm(gw), limit=100)
    assert stats["reviewed"] == 2 and len(gw.calls) == 2
    rows = {r["posting_id"]: r for r in conn.execute("SELECT * FROM ad_reviews")}
    assert rows[good]["verdict"] == "show" and rows[good]["text_source"] == "full" and rows[good]["model_json"]
    # the quote is inside the ad text, so the citizenship claim is verified
    assert rows[bad]["verdict"] == "hide" and rows[bad]["hide_reason"] == "work_rights_incompatible"
    gw.calls.clear()
    again = reader.review_pending(conn, config, llm=make_llm(gw), limit=100)
    assert again["pending"] == 0 and gw.calls == []                 # the cache: no new model call


def test_confirmed_settings_change_cache_but_unconfirmed_files_do_not(world, tmp_path, confirmed_candidate):
    config, conn, add = world
    add("Accounts Clerk")
    gw = FakeGateway()
    reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    gw.calls.clear()
    same = reader.review_pending(conn, config, llm=make_llm(gw), limit=10, redo=True)
    assert same["skipped_same"] == 1 and gw.calls == []
    (tmp_path / "profile" / "interests_and_criteria.yaml").write_text("target_roles:\n  not_wanted: [shop_retail]\n")
    unconfirmed = reader.review_pending(conn, config, llm=make_llm(gw), limit=10, redo=True)
    assert unconfirmed["skipped_same"] == 1 and gw.calls == []
    confirmed_candidate["version"] = 2
    confirmed_candidate["facts"].append({"id": "x", "section": "exclusion", "basis": "evidence",
        "value": {"kind": "family", "value": "shop_retail"}})
    changed = reader.review_pending(conn, config, llm=make_llm(gw), limit=10, redo=True)
    assert changed["skipped_same"] == 0 and changed["reviewed"] == 1 and len(gw.calls) == 1


def _repost(conn, sid, desc, **over):
    """A second requisition inside the dedupe window: same words, new source id and URL, so its own postings row."""
    fields = {"location": "Melbourne VIC", **over}
    p = Posting(source="ats_pageup", source_id=sid, url=f"https://example.com/{sid}", title="Accounts Clerk",
                company="Acme", description=desc, raw={}, **fields)
    pid, _ = ingest(conn, p)
    conn.execute("INSERT INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, matched_at) "
                 "VALUES(?,?,?,?,?,?,?)", (pid, "general_clerk", "core", "[]", "{}", "[]", dbm.ts()))
    conn.commit()
    return pid

def test_identical_repost_reuses_a_stored_reading(world):
    config, conn, add = world
    desc = "Process invoices. MYOB and Excel needed. " * 20
    first = add("Accounts Clerk", desc=desc)
    gw = FakeGateway()
    reader.review_pending(conn, config, llm=make_llm(gw), limit=1)
    assert len(gw.calls) == 1
    second = _repost(conn, "Accounts-Clerk-2", desc)
    assert second != first
    gw.calls.clear()
    stats = reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    assert stats["reused"] == 1 and stats["reviewed"] == 0 and gw.calls == []
    a, b = conn.execute("SELECT posting_id, verdict, fit, score, content_hash FROM ad_reviews")
    assert a["content_hash"] == b["content_hash"]
    assert (a["verdict"], a["fit"], a["score"]) == (b["verdict"], b["fit"], b["score"])

def test_repost_with_a_different_prompt_visible_field_is_read_again(world):
    """Location and salary reach the prompt but not the content hash, so a different value needs its own reading."""
    config, conn, add = world
    desc = "Process invoices. MYOB and Excel needed. " * 20
    add("Accounts Clerk", desc=desc)
    gw = FakeGateway()
    reader.review_pending(conn, config, llm=make_llm(gw), limit=1)
    _repost(conn, "Accounts-Clerk-Sydney", desc, location="Sydney NSW")
    gw.calls.clear()
    stats = reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    assert stats["reused"] == 0 and stats["reviewed"] == 1 and len(gw.calls) == 1

def test_sponsored_ad_is_hidden_without_a_model_call(world):
    config, conn, add = world
    pid = add("Admin Assistant", source="seek", desc="short", raw={"displayType": "promoted", "isFeatured": True})
    gw = FakeGateway()
    reader.review_pending(conn, config, llm=make_llm(gw), limit=10, fetcher=lambda sid: "")
    row = conn.execute("SELECT * FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert (row["verdict"], row["hide_reason"]) == ("hide", "sponsored_ad") and gw.calls == []


def test_teaser_only_ad_is_held_and_retried_when_text_arrives(world):
    config, conn, add = world
    pid = add("Office Assistant", source="jora", desc="short teaser")
    reader.review_pending(conn, config, llm=make_llm(FakeGateway()), limit=10)
    row = conn.execute("SELECT * FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert row["verdict"] == "review" and row["text_source"] == "teaser"
    adtext.save_text(conn, pid, "Full ad. " * 200, "test")
    stats = reader.review_pending(conn, config, llm=make_llm(FakeGateway()), limit=10)
    row = conn.execute("SELECT * FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert stats["reviewed"] == 1 and row["verdict"] == "show" and row["text_source"] == "full"


def test_seek_page_is_fetched_once_and_saved(world):
    config, conn, add = world
    pid = add("Bookkeeper", source="seek", desc="teaser")
    calls = []

    def fetcher(source_id):
        calls.append(source_id)
        return "Real ad body. " * 100

    reader.review_pending(conn, config, llm=make_llm(FakeGateway()), limit=10, fetcher=fetcher)
    assert calls == ["Bookkeeper"] and adtext.get_text(conn, pid)[1] == "seek_detail"
    assert conn.execute("SELECT text_source FROM ad_reviews").fetchone()[0] == "full"


def test_blocked_host_stops_fetching_but_still_reads_the_teaser(world):
    config, conn, add = world
    add("Bookkeeper", source="seek", desc="teaser")
    add("Billing Clerk", source="seek", desc="teaser")
    seen = []

    def fetcher(source_id):
        seen.append(source_id)
        raise adtext.Blocked("seek HTTP 403")

    stats = reader.review_pending(conn, config, llm=make_llm(FakeGateway()), limit=10, fetcher=fetcher)
    assert len(seen) == 1 and stats["stopped"] == "seek HTTP 403" and stats["review"] == 2


def test_model_outage_leaves_ads_pending(world):
    config, conn, add = world
    add("Accounts Clerk")
    stats = reader.review_pending(conn, config, llm=make_llm(FakeGateway(fail=True)), limit=10)
    assert stats["model_failed"] == 1 and conn.execute("SELECT COUNT(*) FROM ad_reviews").fetchone()[0] == 0


def test_rederive_uses_confirmed_policy_not_unconfirmed_score_threshold(world, confirmed_candidate):
    config, conn, add = world
    pid = add("Accounts Clerk")
    gw = FakeGateway({"Accounts Clerk": model(score=3.7)})
    reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    assert conn.execute("SELECT verdict FROM ad_reviews").fetchone()[0] == "show"
    config.settings["reader"]["min_score_show"] = 3.9
    gw.calls.clear()
    out = reader.rederive(conn, config)
    row = conn.execute("SELECT verdict, hide_reason FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert out["changed"] == 0 and (row[0], row[1]) == ("show", None) and gw.calls == []
    confirmed_candidate["version"] = 2
    confirmed_candidate["facts"].append({"id": "x", "section": "exclusion", "basis": "evidence",
        "value": {"kind": "title_term", "value": "accounts"}})
    out = reader.rederive(conn, config)
    row = conn.execute("SELECT verdict, hide_reason FROM ad_reviews WHERE posting_id=?", (pid,)).fetchone()
    assert out["changed"] == 1 and tuple(row) == ("hide", "policy_excluded") and gw.calls == []


def test_after_collect_is_off_unless_enabled(world):
    config, conn, add = world
    assert reader.after_collect(conn, config) == {"enabled": False}


# ------------------------------------------------------------------------------------------ recall
def test_recall_adds_plausible_titles_and_remembers_the_rest(world):
    config, conn, add = world
    yes = add("Practice Support Coordinator", match=False, company="Clinic", desc="Front desk and billing")
    no = add("Forklift Driver", match=False)                            # off-target word: asked, judged by meaning
    nope = add("Wizard Apprentice", match=False)
    gw = FakeGateway(triage={no: False})
    stats = recall.triage_new(conn, config, llm=make_llm(gw))
    assert stats["added"] == 2 and gw.calls == [DEFAULT_MODEL]
    m = conn.execute("SELECT arm, arm_tier FROM matches WHERE posting_id=?", (yes,)).fetchone()
    assert (m["arm"], m["arm_tier"]) == ("ai_semantic", "ai")
    assert conn.execute("SELECT COUNT(*) FROM matches WHERE posting_id=?", (no,)).fetchone()[0] == 0
    gw.calls.clear()
    assert recall.triage_new(conn, config, llm=make_llm(gw))["candidates"] == 0 and gw.calls == []
    assert nope  # asked once, remembered


def test_recall_triage_parses_relevant_strictly():
    rows = [{"id": i, "title": "T", "company": "C", "location": "L", "description": ""} for i in range(1, 7)]
    vals = {1: True, 2: "false", 3: "no", 4: "yes", 5: None, 6: "True"}
    reply = {"model": "m", "choices": [{"message": {"content": json.dumps(
        {"results": [{"id": i, "relevant": v} for i, v in vals.items()]})}}]}
    out = recall.triage_batch(LLM(transport=lambda *a: (200, reply), keys=["k"]), "m", "profile", rows)
    assert out == {1: True, 2: False, 3: False, 4: True, 5: False, 6: True}


def test_recall_rejects_are_remembered_and_a_failed_batch_is_retried(world):
    config, conn, add = world
    pid = add("Wizard Apprentice", match=False)
    stats = recall.triage_new(conn, config, llm=make_llm(FakeGateway(triage={pid: False})))
    assert stats["rejected"] == 1 and conn.execute("SELECT relevant FROM ai_triage").fetchone()[0] == 0
    other = add("Gnome Keeper", match=False)
    bad = recall.triage_new(conn, config, llm=make_llm(FakeGateway(fail=True)))
    assert bad["failed_batches"] == 1 and conn.execute(
        "SELECT COUNT(*) FROM ai_triage WHERE posting_id=?", (other,)).fetchone()[0] == 0


def test_prompt_uses_confirmed_evidence_and_cache_follows_approved_profile(world, tmp_path, confirmed_candidate):
    config, conn, add = world
    add("Accounts Clerk")
    gw = FakeGateway()
    reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    prompt = gw.prompts[0]
    assert "Policy: part-time only." not in prompt and "Accounting graduate. MYOB." in prompt
    assert "jane@example.com" not in prompt and "0400 000 000" not in prompt
    stored = conn.execute("SELECT content_hash, score, archetype, legitimacy, report_json FROM ad_reviews").fetchone()
    assert stored["score"] == 4.1 and stored["archetype"] == "Accounts & Administration" and stored["legitimacy"] == "high"
    assert json.loads(stored["report_json"])["requirements"]
    # the owner edits the profile: the same ad is read again
    (tmp_path / "profile" / "career_ops_profile.md").write_text("Target roles: data analyst only.")
    gw.calls.clear()
    assert reader.review_pending(conn, config, llm=make_llm(gw), limit=10)["pending"] == 0     # pending is by prompt version...
    unconfirmed = reader.review_pending(conn, config, llm=make_llm(gw), limit=10, posting_ids=[1])
    assert unconfirmed["skipped_same"] == 1 and gw.calls == []
    confirmed_candidate["version"] = 2
    confirmed_candidate["facts"].append({"id": "f", "section": "career_focus", "basis": "evidence", "value": "data analyst"})
    again = reader.review_pending(conn, config, llm=make_llm(gw), limit=10, posting_ids=[1])
    assert again["reviewed"] == 1 and len(gw.calls) == 1


def test_an_invalid_json_reply_is_retried_once(world):
    config, conn, add = world
    add("Accounts Clerk")
    gw = FakeGateway(bad_json_first=True)
    stats = reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    assert stats["reviewed"] == 1 and stats["model_failed"] == 0 and len(gw.calls) == 2


def test_a_network_timeout_does_not_kill_the_run(world):
    config, conn, add = world
    add("Accounts Clerk")
    add("Payroll Officer")

    class Flaky(FakeGateway):
        def __call__(self, url, headers, body, timeout):
            if "Payroll Officer" in body["messages"][-1]["content"]:
                raise TimeoutError("read timed out")
            return super().__call__(url, headers, body, timeout)

    stats = reader.review_pending(conn, config, llm=make_llm(Flaky()), limit=10)
    assert stats["reviewed"] == 1 and stats["model_failed"] == 1       # the other ad is still read; the timeout one stays pending


def test_llm_string_error_payload_is_an_llm_error_not_an_attribute_error():
    from jobwatch.util.llm import LLMError
    llm = LLM(transport=lambda *a: (500, {"error": "upstream exploded"}), keys=["k"])
    with pytest.raises(LLMError, match="upstream exploded"):
        llm.chat("openai/sol", [{"role": "user", "content": "hi"}], json_mode=False)


def test_llm_null_usage_counts_do_not_break_cost():
    ok = {"model": "openai/sol", "choices": [{"message": {"content": "hi"}}],
          "usage": {"prompt_tokens": None, "completion_tokens": 10}}
    res = LLM(transport=lambda *a: (200, ok), keys=["k"]).chat(
        "openai/sol", [{"role": "user", "content": "hi"}], json_mode=False)
    assert res.text == "hi" and res.cost_usd == round(10 * 10.0 / 1e6, 5)





def test_sort_not_target_stops_at_the_run_deadline(world):
    import time
    config, conn, add = world
    for i in range(45):                                 # three batches of up to 20
        pid = add(f"Not Wanted Job {i}")
        conn.execute("INSERT INTO ad_reviews(posting_id, content_hash, prompt_version, model, verdict, reviewed_at, model_json, "
                     "report_json) VALUES(?, 'h', 1, 'm', 'hide', ?, '{}', '{\"wanted\": \"not_wanted\"}')", (pid, dbm.ts()))
    conn.commit()
    calls = []

    class Slow:
        def chat(self, model, messages, **kw):
            calls.append(kw)
            raise reader.LLMError("upstream slow")      # each batch burns its time and fails
    stats = reader.sort_not_target(conn, config, llm=Slow(), deadline=time.monotonic() - 1)
    assert calls == [] and stats.get("time_limit")      # already past the deadline: no paid call is started
    stats = reader.sort_not_target(conn, config, llm=Slow(), deadline=time.monotonic() + 60)
    assert calls and all(kw.get("deadline") is not None and kw["timeout"] <= 60 for kw in calls)


def test_reader_person_scope_and_rights_differ_between_confirmed_profiles(monkeypatch):
    from jobwatch.candidate.policy import build_policy
    def use(*facts):
        policy = build_policy({'version': 1, 'facts': [
            {'id': str(i), 'section': section, 'basis': 'evidence', 'value': value}
            for i, (section, value) in enumerate(facts)]})
        monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda *a, **k: policy)
    text = 'Senior engineer in Sydney NSW. Applicants must be Australian citizens only.'
    output = model(rights='citizen_only', quote='Applicants must be Australian citizens only.',
                   seniority='senior', years=10, score=2.1, loc='out_of_scope')
    use(('location', 'Sydney NSW'), ('work_rights', {'citizen': True}))
    first = reader.decide(output, text, 'full', CFG, title='Senior Engineer', location='Sydney NSW')
    assert (first['verdict'], first['score']) == ('show', 2.1)
    use(('location', 'Melbourne VIC'), ('work_rights', {'citizen': True}))
    second = reader.decide(output, text, 'full', CFG, title='Senior Engineer', location='Sydney NSW')
    assert (second['verdict'], second['hide_reason']) == ('hide', 'location_outside_scope')
    use(('location', 'Sydney NSW'), ('work_rights', {'citizen': False, 'permanent_resident': True}))
    third = reader.decide(output, text, 'full', CFG, title='Senior Engineer', location='Sydney NSW')
    assert (third['verdict'], third['hide_reason']) == ('hide', 'work_rights_incompatible')
    use(('location', 'Sydney NSW'))
    unknown = reader.decide(output, text, 'full', CFG, title='Senior Engineer', location='Sydney NSW')
    assert unknown['verdict'] == 'review' and unknown['hide_reason'] is None


def test_reader_confirmed_employer_exclusion_is_enforced_without_model_taste(confirmed_candidate):
    confirmed_candidate['facts'].append({'id': 'employer', 'section': 'exclusion', 'basis': 'evidence',
        'value': {'kind': 'employer', 'value': 'Acme'}})
    same = model(score=5)
    excluded = reader.decide(same, 'Engineering vacancy at Acme.', 'full', CFG, company='Acme')
    other = reader.decide(same, 'Engineering vacancy at Other.', 'full', CFG, company='Other')
    assert (excluded['verdict'], excluded['hide_reason']) == ('hide', 'policy_excluded')
    assert other['verdict'] == 'show'


@pytest.mark.parametrize('change', ['rights', 'title_exclusion'])
def test_automatic_reader_reconsiders_cached_show_after_confirmed_policy_change(world, confirmed_candidate, change):
    config, conn, add = world
    quote = 'Applicants must be Australian citizens only.'
    confirmed_candidate['facts'][0]['value'].update(citizen=True, unrestricted_work_rights=True)
    pid = add('Accounts Clerk', desc=(quote + ' Process supplier invoices. ') * 10)
    gw = FakeGateway({'Accounts Clerk': model(rights='citizen_only', quote=quote)})
    reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    initial = dict(conn.execute('SELECT * FROM ad_reviews WHERE posting_id=?', (pid,)).fetchone())
    assert initial['verdict'] == 'show', {k: v for k, v in initial.items() if k in ('flags_json', 'hide_reason', 'reason', 'text_source')}
    gw.calls.clear()
    confirmed_candidate['version'] = 2
    if change == 'rights':
        confirmed_candidate['facts'][0]['value']['citizen'] = False
        expected = 'work_rights_incompatible'
    else:
        confirmed_candidate['facts'].append({'id': 'exclude', 'section': 'exclusion', 'basis': 'evidence',
            'value': {'kind': 'title_term', 'value': 'accounts'}})
        expected = 'policy_excluded'
    # Normal automatic scheduling must not require an operator to choose redo.
    reader.review_pending(conn, config, llm=make_llm(gw), limit=10)
    row = conn.execute('SELECT verdict, hide_reason FROM ad_reviews WHERE posting_id=?', (pid,)).fetchone()
    assert tuple(row) == ('hide', expected)
    assert gw.calls == [DEFAULT_MODEL]  # A changed approved profile is re-evaluated automatically.


def test_reader_workers_keep_calling_person_identity_and_confirmed_policy(world, confirmed_candidate, monkeypatch):
    import copy
    from jobwatch import users
    from jobwatch.candidate.policy import build_policy
    config, conn, add = world
    profiles = {}
    for person, employer in ((users.DEFAULT_USER, 'OWNER_ONLY_EMPLOYER'),
                              ('synthetic-review', 'CALLER_ONLY_EMPLOYER')):
        profiles[person] = copy.deepcopy(confirmed_candidate)
        profiles[person]['facts'].append({'id': 'excluded-employer', 'section': 'exclusion', 'basis': 'evidence',
            'value': {'kind': 'employer', 'value': employer}})
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda person, **kw: build_policy(profiles[person]))
    monkeypatch.setattr('jobwatch.candidate.intake.current_version', lambda person: profiles[person])
    observed = []
    original = reader.ask
    def capture(*args, **kwargs):
        observed.append((users.current(), reader.settings_block()))
        return original(*args, **kwargs)
    monkeypatch.setattr(reader, 'ask', capture)
    with users.use('synthetic-review'):
        pid = add('Accounts Clerk')
        result = reader.review_pending(conn, config, llm=make_llm(FakeGateway()), limit=10)
    assert result['reviewed'] == 1
    assert conn.execute('SELECT verdict FROM ad_reviews WHERE posting_id=?', (pid,)).fetchone()[0] == 'show'
    assert len(observed) == 1 and observed[0][0] == 'synthetic-review'
    assert 'CALLER_ONLY_EMPLOYER' in observed[0][1]
    assert 'OWNER_ONLY_EMPLOYER' not in observed[0][1]


def test_fetch_only_fills_the_ad_text_and_calls_no_model(world):
    """A run without a confirmed scope still does useful work: the ad text is fetched, nothing is judged."""
    config, conn, add = world
    good = add("Accounts Clerk", desc="x " * 500)
    gw = FakeGateway()
    stats = reader.review_pending(conn, config, llm=make_llm(gw), limit=10, fetch_only=True)
    assert gw.calls == []                                    # no model call at all
    assert stats["text_ready"] >= 1 and stats["reviewed"] == 0
    assert conn.execute("SELECT COUNT(*) FROM ad_reviews").fetchone()[0] == 0   # no verdict was invented
