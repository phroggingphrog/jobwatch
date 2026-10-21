"""The board driven by the AI reader (ad_reviews): the default Good list, the AI views, hide reasons, the card, the
pane's "What the AI read" section, the Table and CSV columns, empty states and escaping. Scratch DBs only."""
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobwatch import db as dbm
from jobwatch.config import DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, Config, _merge
from jobwatch.web import queries as q
from jobwatch.web.app import create_app

OK = {"host": "localhost", "origin": "http://localhost"}
TEMPLATES = Path(__file__).resolve().parents[2] / "jobwatch" / "web" / "templates"
EVIL = '<script>alert(1)</script>'
EVIL_IMG = '<img src=x onerror=alert(2)>'


def seed(conn, n, title, company="Telstra", arm="call_centre", tier="core", minutes_ago=60, match=True,
         desc="Answer calls.\nHelp customers."):
    when = dbm.ts(datetime.now(UTC) - timedelta(minutes=minutes_ago))
    cur = conn.execute(
        """INSERT INTO postings(source, source_id, url, url_hash, dedupe_key, title, company, location, state,
               description, flags_json, first_seen_at, last_seen_at, posted_at)
           VALUES('seek', ?, ?, ?, ?, ?, ?, 'Melbourne VIC', 'VIC', ?, '[]', ?, ?, ?)""",
        (str(n), f"https://example.org/job/{n}", f"h{n}", f"k{n}", title, company, desc, when, when, when))
    if match:
        conn.execute("INSERT INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, matched_at) "
                     "VALUES(?,?,?,?,?,?,?)", (cur.lastrowid, arm, tier, '["%s"]' % arm, "{}", "[]", when))
    conn.commit()
    return cur.lastrowid


def review(conn, pid, **kw):
    d = dict(content_hash=f"c{pid}", prompt_version=2, model="claude/sonnet", text_source="full", text_len=2000,
             verdict="show", hide_reason=None, fit=70, real_job=1, ad_kind="employer", rights="none_stated",
             rights_quote="", seniority="entry", min_years=0, role_match="", reason="A clear office job.",
             pros_json="[]", cons_json="[]", flags_json="[]", cost_usd=0.0, reviewed_at=dbm.ts())
    for k in ("pros", "cons", "flags"):
        if k in kw:
            kw[k + "_json"] = json.dumps(kw.pop(k))
    d.update(kw, posting_id=pid)
    conn.execute(f"INSERT OR REPLACE INTO ad_reviews({','.join(d)}) VALUES({','.join('?' * len(d))})", list(d.values()))
    conn.commit()


def make_config(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(data))
    monkeypatch.delenv("JOBWATCH_DB", raising=False)
    settings = _merge(DEFAULT_SETTINGS, {"db_path": str(data / "jobwatch.db")})
    return Config(config_dir=DEFAULT_CONFIG_DIR, settings=settings, rules={}, searches={}, feeds={}, employers=[])


class BoardClient(TestClient):
    """The server-rendered board is gone: GET "/?filters" is answered by the app's /api/board."""
    def get(self, url, *a, **kw):
        if url == "/" or url.startswith("/?"):
            url = "/api/board" + url[1:]
        return super().get(url, *a, **kw)


def make_client(config, tmp_path):
    c = BoardClient(create_app(config), base_url="http://localhost", headers=OK, raise_server_exceptions=True)
    c.tmp, c.db = tmp_path, config.db_path
    return c


@pytest.fixture
def client(tmp_path, monkeypatch):
    """One posting in every AI state and every hide reason."""
    config = make_config(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    ids = {}

    def add(key, n, title, minutes_ago=60, read=True, **rev):
        ids[key] = seed(conn, n, title, minutes_ago=minutes_ago)
        if read:
            review(conn, ids[key], **rev)

    add("good1", 1, "Good Clerk One", minutes_ago=300, fit=80, reason="Friendly front desk job with training.",
        pros=["Training provided", "Hours stated", "Near the station", "Fourth pro"], cons=["Some weekends"],
        ad_kind="agency")
    add("good2", 2, "Good Clerk Two", minutes_ago=30, fit=80, reason="Entry-level admin at a hospital group.")
    add("good3", 3, "Good Receptionist", minutes_ago=90, fit=60, reason="Reception role with bookings.",
        rights="valid_work_rights", rights_quote="You must have full working rights in Australia.",
        seniority="junior", min_years=2)
    add("held", 4, "Held Teaser Clerk", verdict="review", text_source="teaser", fit=None, reason="Only a teaser was read.")
    add("citizen", 5, "Hidden Citizen Clerk", verdict="hide", hide_reason="needs_citizen_or_pr", fit=65,
        rights="citizen_or_pr", rights_quote="Only Australian citizens or permanent residents may apply.",
        reason="The ad says only citizens or PR can apply.")
    add("sponsored", 6, "Hidden Sponsored Clerk", verdict="hide", hide_reason="sponsored_ad", fit=None, reason="Paid placement.")
    add("notreal", 7, "Hidden NotReal Clerk", verdict="hide", hide_reason="not_a_real_job", fit=40, real_job=0,
        ad_kind="talent_pool", reason="A talent pool, no real vacancy.")
    add("senior", 8, "Hidden Senior Clerk", verdict="hide", hide_reason="too_senior", fit=55, seniority="senior",
        min_years=7, reason="Wants 7+ years.")
    add("lowfit", 9, "Hidden LowFit Clerk", verdict="hide", hide_reason="low_fit", fit=12, reason="Warehouse labour.")
    add("pending", 10, "Pending Clerk", read=False)          # no ad_reviews row: waiting for the AI
    conn.close()
    c = make_client(config, tmp_path)
    c.ids = ids
    return c


def titles(text):
    if text.lstrip().startswith("{"):
        import json
        return [r["title"] for r in json.loads(text)["rows"]]
    return re.findall(r'<h3 class="card-title"><a [^>]*>([^<]*)</a>', text)


def body(client, path, **kw):
    r = client.get(path, **kw)
    assert r.status_code == 200, (path, r.text[:300])
    return r.text


def cards_of(html):
    """Only the list on the left (the board also renders the selected job's pane)."""
    return html.split('<aside id="pane"')[0]


# -- data ------------------------------------------------------------------------------------------------------
def test_load_rows_attaches_ai_and_state_in_one_query(client):
    conn = dbm.connect(client.db)
    statements = []
    conn.set_trace_callback(statements.append)
    rows = {r["title"]: r for r in q.load_rows(conn, "all")}
    assert len(statements) == 1                                    # one query, no per-row lookups
    assert {t: r["ai_state"] for t, r in rows.items()} == {
        "Good Clerk One": "show", "Good Clerk Two": "show", "Good Receptionist": "show", "Held Teaser Clerk": "review",
        "Hidden Citizen Clerk": "hide", "Hidden Sponsored Clerk": "hide", "Hidden NotReal Clerk": "hide",
        "Hidden Senior Clerk": "hide", "Hidden LowFit Clerk": "hide", "Pending Clerk": "pending"}
    one = rows["Good Clerk One"]
    assert one["ai"]["pros"] == ["Training provided", "Hours stated", "Near the station", "Fourth pro"]
    assert one["ai"]["cons"] == ["Some weekends"] and one["ai"]["ad_kind"] == "agency"
    assert rows["Pending Clerk"]["ai"] is None
    assert not any(k.startswith("ai_") and k != "ai_state" for k in one)      # the raw columns are gone


def test_score_is_the_ai_fit_when_read_else_the_keyword_score(client):
    conn = dbm.connect(client.db)
    rows = {r["title"]: r for r in q.load_rows(conn, "all")}
    good = rows["Good Clerk One"]
    assert good["score"] == 80 and good["score_src"] == "ai" and good["score_why"] == [good["ai"]["reason"]]
    assert good["rule_why"] and isinstance(good["rule_score"], int)          # the old score is kept alongside
    held = rows["Held Teaser Clerk"]                                         # reviewed, but no AI fit: keyword score
    assert held["score_src"] == "rules" and held["score"] == held["rule_score"]
    pending = rows["Pending Clerk"]
    assert pending["score_src"] == "rules" and pending["score"] == pending["rule_score"] and pending["score_why"]


def test_unknown_verdict_is_held_back_never_shown(client):
    conn = dbm.connect(client.db)
    conn.execute("UPDATE ad_reviews SET verdict='weird' WHERE posting_id=?", (client.ids["good1"],))
    conn.commit()
    rows = {r["id"]: r for r in q.load_rows(conn, "all")}
    assert rows[client.ids["good1"]]["ai_state"] == "review"


def test_bad_json_in_a_review_does_not_break_the_board(client):
    conn = dbm.connect(client.db)
    conn.execute("UPDATE ad_reviews SET pros_json='not json', cons_json='{\"a\":1}', flags_json=NULL WHERE posting_id=?",
                 (client.ids["good1"],))
    conn.commit()
    assert "Good Clerk One" in body(client, "/")
    assert client.get(f"/job/{client.ids['good1']}/pane").status_code == 200


# -- the lists ---------------------------------------------------------------------------------------------------
def test_default_list_is_good_only(client):
    got = titles(body(client, "/"))
    assert sorted(got) == ["Good Clerk One", "Good Clerk Two", "Good Receptionist"]
    for bad in ("Held Teaser", "Hidden", "Pending Clerk"):
        assert bad not in " ".join(got)
    assert titles(body(client, "/?ai=show")) == got


def test_best_fit_sort_uses_ai_fit_with_newest_first_on_ties(client):
    assert titles(body(client, "/")) == ["Good Clerk Two", "Good Clerk One", "Good Receptionist"]   # 80 (new), 80, 60
    assert titles(body(client, "/?sort=new")) == ["Good Clerk Two", "Good Receptionist", "Good Clerk One"]


@pytest.mark.parametrize("view,expect", [
    ("review", ["Held Teaser Clerk"]),
    ("pending", ["Pending Clerk"]),
    ("hide", ["Hidden Citizen Clerk", "Hidden LowFit Clerk", "Hidden NotReal Clerk", "Hidden Senior Clerk",
              "Hidden Sponsored Clerk"]),
])
def test_each_ai_view_lists_only_its_own(client, view, expect):
    assert sorted(titles(body(client, f"/?ai={view}"))) == expect


@pytest.mark.parametrize("why,expect", [
    ("needs_citizen_or_pr", "Hidden Citizen Clerk"), ("sponsored_ad", "Hidden Sponsored Clerk"),
    ("not_a_real_job", "Hidden NotReal Clerk"), ("too_senior", "Hidden Senior Clerk"), ("low_fit", "Hidden LowFit Clerk")])
def test_hide_reason_filter(client, why, expect):
    assert titles(body(client, f"/?ai=hide&why={why}")) == [expect]
    assert titles(body(client, f"/?ai=hide:{why}")) == [expect]                  # the form's radio value


def test_bad_ai_params_fall_back_safely(client):
    good = titles(body(client, "/"))
    assert titles(body(client, "/?ai=nonsense")) == good
    assert titles(body(client, "/?why=needs_citizen_or_pr")) == good               # a reason without ai=hide is ignored
    assert titles(body(client, "/?ai=review&why=low_fit")) == ["Held Teaser Clerk"]
    assert len(titles(body(client, "/?ai=hide&why=../../etc"))) == 5                 # junk reason is dropped: all hidden
    assert client.get("/?ai=hide&why=" + "x" * 500).status_code == 200




def test_unmatched_jobs_are_waiting_with_scope_all(client):
    conn = dbm.connect(client.db)
    seed(conn, 50, "Unmatched Clerk", match=False)
    conn.close()
    assert "Unmatched Clerk" not in body(client, "/?ai=pending")
    assert "Unmatched Clerk" in titles(body(client, "/?ai=pending&scope=all"))








# -- filters ---------------------------------------------------------------------------------------------------
def test_filters_roundtrip_and_urls():
    f = q.Filters.from_params({"ai": "hide:too_senior"})
    assert (f.ai, f.why) == ("hide", "too_senior")
    assert f.as_dict() == {"ai": "hide", "why": "too_senior"}
    assert f.query() == "ai=hide&why=too_senior"
    assert q.Filters.from_params({"ai": ["hide"], "why": ["low_fit"]}).why == "low_fit"
    assert q.Filters().query() == "" and q.Filters().as_dict() == {}
    assert f.query(ai="show") == ""                                                  # the default never goes in a URL
    assert f.query(ai="review") == "ai=review"                                       # why dropped with another view
    assert f.query(why="") == "ai=hide"
    assert "Hidden by AI: Too senior" in f.summary() and q.Filters().summary() == "Good matches"
    assert q.Filters.from_params({"ai": "HIDE", "why": "Low_Fit"}).why == "low_fit"
    assert q.Filters.from_params({"ai": "show", "why": "low_fit"}).why == ""
    assert q.Filters.from_params({"ai": "hide", "why": "a b"}).why == ""
    assert not q.Filters.from_params({"ai": "hide"}).active_count()                  # a view is not a filter




# -- the card ---------------------------------------------------------------------------------------------------








# -- the pane and the job page -------------------------------------------------------------------------------------










# -- table and csv ------------------------------------------------------------------------------------------------------


def test_csv_has_ai_columns_and_is_formula_safe(client):
    conn = dbm.connect(client.db)
    conn.execute("UPDATE ad_reviews SET reason=? WHERE posting_id=?", ('=HYPERLINK("http://evil","x")', client.ids["citizen"]))
    conn.commit()
    csv_text = body(client, "/table.csv?ai=hide")
    header = csv_text.splitlines()[0]
    assert "score,archetype,recommendation,ai view,ai reason,url" in header
    assert "Hidden: needs citizenship or PR" in csv_text and "'=HYPERLINK" in csv_text and ',=HYPERLINK' not in csv_text
    good = body(client, "/table.csv")
    assert "Hidden Citizen Clerk" not in good and "Good Clerk One" in good and ",4.0,,,Good," in good
    pending = body(client, "/table.csv?ai=pending")
    assert "Pending Clerk" in pending and "Waiting for AI" in pending


# -- empty states ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def backfill(tmp_path, monkeypatch):
    """Three matches, one read (and hidden): the Good view is empty while the AI works through the rest."""
    config = make_config(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    ids = [seed(conn, 1, "Alpha Clerk"), seed(conn, 2, "Beta Clerk"), seed(conn, 3, "Gamma Clerk")]
    review(conn, ids[0], verdict="hide", hide_reason="low_fit", fit=10)
    conn.close()
    c = make_client(config, tmp_path)
    c.ids = ids
    return c












# -- security -------------------------------------------------------------------------------------------------------------------




def test_javascript_url_never_becomes_a_link_on_an_ai_row(client):
    conn = dbm.connect(client.db)
    conn.execute("UPDATE postings SET url='javascript:alert(1)' WHERE id=?", (client.ids["good1"],))
    conn.commit()
    assert "javascript:" not in body(client, f"/job/{client.ids['good1']}/pane")


# ======================================================================================================================
# The career-ops evaluation (reader prompt v3): score 1-5, archetype, legitimacy and the report in report_json
# ======================================================================================================================
def req(requirement="Process invoices", importance="critical", tier="stated", jd_signal="Process invoices daily",
        match="strong", evidence="Processed 200 invoices a week"):
    return dict(requirement=requirement, importance=importance, tier=tier, jd_signal=jd_signal, match=match,
                evidence=evidence)


def report(**over):
    rep = dict(archetype="Accounts & Administration", tldr="Accounts role at a hospital; payroll is the gap.",
               role=dict(seniority="junior", work_mode="hybrid", hours="part_time_ok", location_fit="mid", min_years=2),
               requirements=[req(), req("Bank reconciliations", "high", "stated", "Perform bank reconciliations", "partial",
                                        "Coursework only"),
                             req("Payroll", "meaningful", "structural", "", "missing", "No payroll on the CV"),
                             req("Own transport", "preferred", "inferred", "", "na", "")],
               gaps=[dict(gap="No payroll experience", risk="They may probe payroll", mitigation="Offer the coursework"),
                     dict(gap="Short finance history", risk="Only 8 months", mitigation="Lead with the invoice volume")],
               dimensions=dict(cv_match=4.2, north_star=4.6, comp=3.0, culture=3.8, red_flags=4.9), recommendation="apply",
               legitimacy=dict(tier="high", signals=["Posted 2 days ago"]),
               comp=dict(company_type="Public hospital group", reliability="Medium"),
               authorization=dict(requirement="none_stated", quote=""), score=4.6)
    rep.update(over)
    return rep


def review3(conn, pid, score=4.2, rep=None, **kw):
    rep = report() if rep is None else rep
    base = dict(prompt_version=3, score=score, fit=None if score is None else int(round(score * 20)),
                archetype=rep.get("archetype") if rep else None, legitimacy=(rep or {}).get("legitimacy", {}).get("tier"),
                report_json=json.dumps(rep) if rep is not None else None, reason="The AI's one-line reason.")
    base.update(kw)
    review(conn, pid, **base)


@pytest.fixture
def v3(tmp_path, monkeypatch):
    config = make_config(tmp_path, monkeypatch)
    conn = dbm.connect(config.db_path)
    ids = {}

    def add(key, n, title, minutes_ago=60, **kw):
        ids[key] = seed(conn, n, title, minutes_ago=minutes_ago)
        return ids[key]

    review3(conn, add("alpha", 1, "Alpha Accounts", 100), 4.6)
    review3(conn, add("beta", 2, "Beta Customer", 90), 3.6,
            report(archetype="Customer Service (client-facing)", recommendation="consider",
                   role=dict(seniority="entry", work_mode="onsite", hours="casual", location_fit="outer", min_years=None),
                   legitimacy=dict(tier="caution", signals=["Agency wording: our client", "Generic requirements"])))
    review3(conn, add("gamma", 3, "Gamma Data", 80), 4.1,
            report(archetype="Data Analyst (early career)", legitimacy=dict(tier="suspicious", signals=["Posted 90 days ago"]),
                   role=dict(seniority="junior", work_mode="remote", hours="unstated", location_fit="remote", min_years=None)))
    review(conn, add("legacy", 4, "Delta Legacy", 70), fit=70, score=None, report_json=None, archetype=None,
           reason="Older reading, no score.", pros=["Near the station"], cons=["Some weekends"])        # prompt v2: NULL score
    review3(conn, add("ft", 5, "Hidden FullTime", 60), 2.5, report(role=dict(seniority="junior", work_mode="onsite",
                                                                      hours="full_time_only", location_fit="mid", min_years=None)),
            verdict="hide", hide_reason="full_time_only", reason="Full-time only.")
    review3(conn, add("unres", 6, "Hidden Unrestricted", 50), 1.5,
            report(authorization=dict(requirement="unrestricted_work_rights", quote="You must have unrestricted work rights.")),
            verdict="hide", hide_reason="needs_unrestricted_rights", rights="unrestricted_work_rights",
            rights_quote="You must have unrestricted work rights.", reason="Needs unrestricted rights.")
    review3(conn, add("area", 7, "Hidden Interstate", 40), 2.0,
            report(role=dict(seniority="junior", work_mode="onsite", hours="unstated", location_fit="out_of_scope", min_years=None)),
            verdict="hide", hide_reason="out_of_area", reason="Sydney, not remote.")
    review3(conn, add("citizen", 8, "Hidden Citizen", 30), 1.4, report(), verdict="hide", hide_reason="needs_citizen_or_pr",
            rights="citizen_or_pr", rights_quote="Australian citizens only.", reason="Citizens only.")
    review3(conn, add("held", 9, "Held Teaser", 20), None, report(), verdict="review", text_source="teaser", fit=None,
            reason="Only a teaser.")
    add("pending", 10, "Pending Role", 10)
    conn.close()
    c = make_client(config, tmp_path)
    c.ids = ids
    return c


# -- data: score, archetype, report ---------------------------------------------------------------------------------
def test_score_display_helper():
    assert q.score_display(4.14) == "4.1" and q.score_display(4.0) == "4.0" and q.score_display(5) == "5.0"
    assert q.score_display(None, 70) == "3.5" and q.score_display(None, 65) == "3.3"      # NULL score: fit / 20
    assert q.score_display(None, None) == "" and q.score_display(None) == ""
    assert q.score_display(9) == "5.0" and q.score_display(-1) == "0.0"
    assert q.score_label(4.5) == "Strong match" and q.score_label(4.0) == "Good match"
    assert q.score_label(3.5) == "Decent match" and q.score_label(3.4) == "Recommend against" and q.score_label(None) == ""


def test_rows_carry_score5_archetype_and_a_clean_report(v3):
    rows = {r["title"]: r for r in q.load_rows(dbm.connect(v3.db), "all")}
    a = rows["Alpha Accounts"]
    assert (a["score5"], a["score_text"], a["score"], a["score_src"]) == (4.6, "4.6", 92, "ai")
    assert a["archetype"] == "Accounts & Administration" and a["ai"]["legitimacy"] == "high"
    rep = a["ai"]["report"]
    assert rep["recommendation"] == "apply" and len(rep["requirements"]) == 4 and len(rep["gaps"]) == 2
    assert rep["dimensions"]["red_flags"] == 4.9 and rep["role"]["hours"] == "part_time_ok"
    assert rep["requirements"][2]["jd_signal"] == ""                                        # only 'stated' rows keep a quote
    legacy = rows["Delta Legacy"]
    assert legacy["ai"]["score"] is None and legacy["ai"]["report"] is None and legacy["archetype"] == ""
    assert (legacy["score5"], legacy["score_text"], legacy["score"]) == (3.5, "3.5", 70)  # NULL score -> fit / 20
    assert rows["Pending Role"]["score5"] is None and rows["Pending Role"]["score_text"] == ""
    held = rows["Held Teaser"]
    assert held["ai_state"] == "review" and held["score5"] is None and held["score_src"] == "rules"


def test_bad_report_json_never_breaks_a_page(v3):
    conn = dbm.connect(v3.db)
    for raw in ("not json", "[1, 2]", '"text"', "null", "{}", '{"requirements": "x", "gaps": 5, "dimensions": []}',
                json.dumps({"requirements": [{"requirement": "R", "importance": "bogus", "tier": "bogus", "match": "bogus",
                                              "jd_signal": "q"}, 7, None], "gaps": [{"gap": "G"}, "x"],
                            "dimensions": {"cv_match": "high", "north_star": 99, "comp": True, "culture": None},
                            "role": {"hours": "weekly", "location_fit": "mars", "min_years": "many", "work_mode": 3},
                            "legitimacy": {"tier": "weird", "signals": "one"}, "comp": 5, "recommendation": "maybe"})):
        conn.execute("UPDATE ad_reviews SET report_json=? WHERE posting_id=?", (raw, v3.ids["alpha"]))
        conn.commit()
        for path in ("/", f"/job/{v3.ids['alpha']}", f"/job/{v3.ids['alpha']}/pane", "/table", "/table.csv"):
            assert v3.get(path).status_code == 200, (raw[:30], path)
    r = q._report(json.dumps({"requirements": [{"requirement": "R", "importance": "bogus", "tier": "stated", "match": "x",
                                                "jd_signal": "q"}], "dimensions": {"north_star": 99, "comp": True}}))
    row = r["requirements"][0]
    assert (row["importance"], row["tier"], row["match"], row["jd_signal"]) == ("meaningful", "stated", "na", "q")
    assert r["dimensions"]["north_star"] == 5.0 and r["dimensions"]["comp"] is None and r["recommendation"] == ""


# -- the new hide reasons -------------------------------------------------------------------------------------------------


def test_hide_reason_labels_keep_the_old_ones_and_add_the_new():
    labels = dict(q.HIDE_REASONS)
    assert labels["needs_unrestricted_rights"] == "Needs unrestricted work rights"
    assert labels["full_time_only"] == "Full-time only: not possible while studying"
    assert labels["out_of_area"] == "Outside Melbourne, not remote"
    for old, text in (("sponsored_ad", "Sponsored ad"), ("not_a_real_job", "Not a real vacancy"),
                      ("needs_citizen_or_pr", "Needs citizenship or PR"), ("too_senior", "Too senior"), ("low_fit", "Not a fit")):
        assert labels[old] == text
    assert [k for k, _ in q.HIDE_REASONS].index("full_time_only") < [k for k, _ in q.HIDE_REASONS].index("low_fit")
    assert q.RIGHTS_TEXT["unrestricted_work_rights"] == "Needs unrestricted work rights"




# -- the card ---------------------------------------------------------------------------------------------------------------








def test_best_fit_sort_uses_score_with_null_scores_as_fit_over_20(v3):
    assert titles(body(v3, "/")) == ["Alpha Accounts", "Gamma Data", "Beta Customer", "Delta Legacy"]   # 4.6 4.1 3.6 3.5
    assert titles(body(v3, "/?sort=new")) == ["Delta Legacy", "Gamma Data", "Beta Customer", "Alpha Accounts"]


# -- the pane / job page ------------------------------------------------------------------------------------------------------












# -- filters: score floor and archetype ---------------------------------------------------------------------------------------------
def test_minscore_filter(v3):
    assert titles(body(v3, "/?minscore=4.5")) == ["Alpha Accounts"]
    assert titles(body(v3, "/?minscore=4.0")) == ["Alpha Accounts", "Gamma Data"]
    assert titles(body(v3, "/?minscore=3.5")) == ["Alpha Accounts", "Gamma Data", "Beta Customer", "Delta Legacy"]   # legacy 3.5 via fit/20
    assert titles(body(v3, "/?minscore=4")) == ["Alpha Accounts", "Gamma Data"]
    assert len(titles(body(v3, "/?minscore=3.7"))) == 4 and len(titles(body(v3, "/?minscore=abc"))) == 4   # not an offered floor: ignored
    assert titles(body(v3, "/?ai=pending&minscore=3.5")) == []                                     # unread jobs have no score
    assert len(titles(body(v3, "/?ai=hide&minscore=2.0"))) == 4                                    # 2.0 is not an offered floor: ignored
    assert titles(body(v3, "/?ai=hide&minscore=3.5")) == []                                        # every hidden job scores lower
    assert sorted(titles(body(v3, "/?ai=hide&why=full_time_only&minscore=3.5"))) == []
    rows = q.load_rows(dbm.connect(v3.db), "matches")
    _, counts = q.apply_filters(rows, q.Filters.from_params({}))
    assert dict(counts["minscore"]) == {3.5: 4, 4.0: 2, 4.5: 1}
    _, counts = q.apply_filters(rows, q.Filters.from_params({"minscore": "4.5"}))
    assert dict(counts["minscore"]) == {3.5: 4, 4.0: 2, 4.5: 1}                                    # its own facet is not narrowed




def test_archetype_filter_is_multi_valued_and_never_comma_split(v3):
    assert titles(body(v3, "/?arch=Customer+Service+(client-facing)")) == ["Beta Customer"]
    assert sorted(titles(body(v3, "/?arch=Customer+Service+(client-facing)&arch=Data+Analyst+(early+career)"))) == ["Beta Customer", "Gamma Data"]
    assert titles(body(v3, "/?arch=Accounts+%26+Administration")) == ["Alpha Accounts"]
    assert titles(body(v3, "/?arch=Nothing+like+this")) == []
    f = q.Filters.from_params({"arch": ["A, B", "C & D"]})
    assert f.arch == ["A, B", "C & D"] and q.Filters.from_params(f.as_dict()).arch == f.arch
    assert q.Filters.from_params({"arch": "x" * 100}).arch == []
    conn = dbm.connect(v3.db)
    conn.execute("UPDATE ad_reviews SET archetype='Odd, role (A + B)' WHERE posting_id=?", (v3.ids["beta"],))
    conn.commit()
    assert titles(body(v3, "/?arch=Odd%2C+role+(A+%2B+B)")) == ["Beta Customer"]






def test_filters_parse_minscore():
    for raw, want in (("3.5", 3.5), ("4", 4.0), ("4.0", 4.0), ("4.5", 4.5), ("4.50", 4.5), ("", None), ("3", None),
                      ("4.4", None), ("x", None), ("nan", None), ("-4", None)):
        assert q.Filters.from_params({"minscore": raw}).minscore == want, raw
    assert q.Filters.from_params({"minscore": "4"}).query() == "minscore=4.0"
    assert q.Filters().as_dict() == {}


# -- table and csv ---------------------------------------------------------------------------------------------------------------


def titles_of_table(html):
    return re.findall(r'class="rowlink"[^>]*>([^<]*)<', html)


def test_csv_score_archetype_recommendation_and_filters(v3):
    csv_text = body(v3, "/table.csv")
    assert "status,score,archetype,recommendation,ai view,ai reason,url" in csv_text.splitlines()[0]
    assert re.search(r"Alpha Accounts.*,4\.6,Accounts & Administration,Apply,Good,", csv_text)
    assert re.search(r"Delta Legacy.*,3\.5,,,Good,", csv_text)                                     # NULL score -> fit / 20, no archetype
    assert "Pending Role" not in csv_text
    only = body(v3, "/table.csv?minscore=4.5")
    assert "Alpha Accounts" in only and "Gamma Data" not in only
    assert "Customer Service" in body(v3, "/table.csv?arch=Customer+Service+(client-facing)")
    assert "Hidden: full-time only, not possible while studying" in body(v3, "/table.csv?ai=hide&why=full_time_only")


# -- security: every report field is escaped ---------------------------------------------------------------------------------------------
XSS = ["<script>alert('%s')</script>" % k for k in "abcdefghijklmnop"]




# -- text_source 'partial' (cut at the collector's cap) reads like a teaser, in its own words -------------------------
def _set_source(client, key, source, verdict=None):
    conn = dbm.connect(client.db)
    conn.execute("UPDATE ad_reviews SET text_source=? WHERE posting_id=?", (source, client.ids[key]))
    if verdict:
        conn.execute("UPDATE ad_reviews SET verdict=? WHERE posting_id=?", (verdict, client.ids[key]))
    conn.commit()
    conn.close()






def test_a_show_verdict_from_a_cut_ad_is_listed_as_not_fully_read(client):
    _set_source(client, "good2", "partial")                    # an old row: shown, but read from a cut copy
    show = titles(body(client, "/?ai=show"))
    assert "Good Clerk Two" not in show
    review = titles(body(client, "/?ai=review"))
    assert "Good Clerk Two" in review and "Held Teaser Clerk" in review
    conn = dbm.connect(client.db)
    counts = {r["title"]: r["ai_state"] for r in q.load_rows(conn, "all")}
    assert counts["Good Clerk Two"] == "review"
    conn.close()


# ======================================================================================================================
# round 3: only text_source 'full' is a read ad; a held-back job never says 'Apply'
# ======================================================================================================================
ODD_SOURCES = [None, "", "weird", " partial", "PARTIAL", "Partial ", "Full", " full", "full ", "teaser", "partial", "text"]




def test_ai_state_is_good_only_for_a_show_read_from_the_full_ad():
    assert q.ai_state({"verdict": "show", "text_source": "full"}) == "show"
    for source in ODD_SOURCES:
        assert q.ai_state({"verdict": "show", "text_source": source}) == "review", repr(source)
    assert q.ai_state({"verdict": "show"}) == "review"                         # no text_source key at all
    assert q.ai_state({"verdict": "hide", "text_source": None}) == "hide"       # a hide is not softened
    assert q.ai_state({"verdict": "review", "text_source": "full"}) == "review"
    assert q.ai_state(None) == "pending"


def test_a_row_with_no_text_source_is_not_good_in_the_database_either(client):
    conn = dbm.connect(client.db)
    try:
        conn.execute("UPDATE ad_reviews SET text_source=NULL WHERE posting_id=?", (client.ids["good1"],))
        conn.commit()
    finally:
        conn.close()
    assert "Good Clerk One" not in titles(body(client, "/?ai=show")) and "Good Clerk One" in titles(body(client, "/?ai=review"))


def _years_asked(html):
    m = re.search(r"<dt>Years asked</dt><dd>(.*?)</dd>", html, re.S)
    assert m, "no Years asked line"
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()






def test_hold_replaces_apply_and_consider_only_and_never_for_a_good_row(v3):
    assert q.rec_key({"ai_state": "show", "ai": {"report": {"recommendation": "apply"}}}) == "apply"
    assert q.rec_key({"ai_state": "review", "ai": {"report": {"recommendation": "apply"}}}) == "hold"
    assert q.rec_key({"ai_state": "review", "ai": {"report": {"recommendation": "consider"}}}) == "hold"
    assert q.rec_key({"ai_state": "review", "ai": {"report": {"recommendation": "skip"}}}) == "skip"
    assert q.rec_key({"ai_state": "review", "ai": {"report": {"recommendation": "bogus"}}}) == ""
    assert q.rec_key({"ai_state": "pending", "ai": None}) == "" and q.rec_key({}) == ""
    import csv
    import io
    rows = {}
    for view in ("show", "review"):
        rows.update({r["title"]: r["recommendation"] for r in csv.DictReader(io.StringIO(body(v3, f"/table.csv?ai={view}")))})
    assert rows["Held Teaser"] == "Hold" and rows["Beta Customer"] == "Consider" and rows["Alpha Accounts"] == "Apply"


# -- a script's Accept header: the FIRST, highest-ranked type decides, not a substring ------------------------------


# -- the deterministic pipeline's verdicts (BUI-98) --------------------------------------------------------------
def staged(conn, pid, stage, reason=None, overall=4.2, **extra):
    from pipeline import store
    store.ensure(conn)
    mark = lambda s: {"score": s, "evidence": "Ad asks for Excel; CV shows Excel."}     # noqa: E731
    data = {"extract": {"role_family": "Accounts administration", "seniority": "entry", "min_years": None,
                        "work_rights": {"requirement": "valid_work_rights", "quote": "must have work rights"}},
            "evaluate": {"technical_skills": mark(4), "experience": mark(4), "domain": mark(5), "wanted": "core",
                         "justification": "Entry accounts role that matches the CV.", "overall": overall}, **extra}
    conn.execute("INSERT OR REPLACE INTO pipeline_state(posting_id, stage, content_hash, data_json, reason, updated_at) "
                 "VALUES(?,?,?,?,?,?)", (pid, stage, "0" * 64, json.dumps(data), reason, dbm.ts()))
    conn.commit()




def test_pipeline_bad_json_never_breaks_the_board(tmp_path, monkeypatch):
    config = make_config(tmp_path, monkeypatch)
    c = make_client(config, tmp_path)
    conn = dbm.connect(config.db_path)
    pid = seed(conn, 1, "Broken Pipeline Row")
    conn.execute("INSERT INTO pipeline_state VALUES(?,?,?,?,?,?)", (pid, "ready", "0" * 64, "[1,", None, dbm.ts()))
    conn.commit()
    r = q.load_rows(conn, "matches")[0]
    assert r["ai_state"] == "show" and r["score5"] is None
    assert c.get("/").status_code == 200 and c.get(f"/job/{pid}").status_code == 200


def test_pipeline_not_target_shows_the_sorted_kind(tmp_path, monkeypatch):
    """BUI-96: a not_target job the pipeline archived shows its named kind, not '(not sorted yet)'."""
    config = make_config(tmp_path, monkeypatch)
    c = make_client(config, tmp_path)
    conn = dbm.connect(config.db_path)
    named = seed(conn, 1, "Pipeline Barista")
    staged(conn, named, "archived", reason="not_target", sort={"not_target_kind": "hospitality", "source": "model"})
    plain = seed(conn, 2, "Pipeline Unsorted")
    staged(conn, plain, "archived", reason="not_target")
    odd = seed(conn, 3, "Pipeline Odd Kind")
    staged(conn, odd, "archived", reason="not_target", sort={"not_target_kind": "<script>", "source": "model"})
    senior = seed(conn, 4, "Pipeline Senior")
    staged(conn, senior, "archived", reason="low_score", sort={"not_target_kind": "hospitality"})
    rows = {r["id"]: r for r in q.load_rows(conn, "matches")}
    assert rows[named]["ai"]["hide_reason"] == "hospitality"
    assert rows[plain]["ai"]["hide_reason"] == "not_target"
    assert rows[odd]["ai"]["hide_reason"] == "not_target"                  # unknown kinds are never shown
    assert rows[senior]["ai"]["hide_reason"] == "low_fit"                  # only a not_target job takes a kind
    html = body(c, "/?ai=hide:hospitality")
    assert "Pipeline Barista" in html and "Pipeline Unsorted" not in html
