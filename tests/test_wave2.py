"""Wave-2 collectors and pipeline guards (offline fixtures only)."""
import fcntl

import pytest

from conftest import FakeHttp, FakeResponse, fixture_json, fixture_text, make_config, make_ctx
from jobwatch import cli
from jobwatch import db as dbm
from jobwatch import pipeline
from jobwatch.collectors import (ats_atlassian, ats_oracle, ats_phenom, ats_successfactors, careers_vic,
                                 jsonld_pages, rss)
from jobwatch.filters import Rules
from jobwatch.models import Posting


def emp(provider, **kw):
    return {"name": kw.pop("name", "Example Co"), "provider": provider, "state": "VIC", "enabled": True, **kw}


# ---------------------------------------------------------------- SuccessFactors
def test_sf_title_location_split():
    s = rss.split_title_location
    assert s("Graphic Designer (Chadstone, VIC, AU, 3148)") == ("Graphic Designer", "Chadstone, VIC, 3148", "AU")
    assert s("Team Member (AU)") == ("Team Member", "", "AU")
    assert s("Barista (Casual)") == ("Barista (Casual)", "", None)
    assert s("X (Auckland, AUK, NZ)")[2] == "NZ"


def test_successfactors_feed_gate_and_fields():
    http = FakeHttp({"jobs.target.com.au/googlefeed.xml": fixture_text("successfactors_feed.xml")})
    ctx = make_ctx(http, [emp("successfactors", name="Target Australia", host="jobs.target.com.au",
                              feed_url="https://jobs.target.com.au/googlefeed.xml", poll_tier="slow")])
    out = ats_successfactors.collect(ctx)
    titles = {p.title: p for p in out}
    assert ctx.raw_count == 7
    assert "Kmart Albany - Team Member" not in titles                        # NZ dropped
    assert titles["Graphic Designer - Girlswear"].state == "VIC"
    assert titles["Graphic Designer - Girlswear"].location.startswith("Chadstone, VIC")
    assert titles["Payroll Officer"].location == ""                           # "(AU)" only: unknown city
    assert titles["Customer Service Assistant"].location.startswith("Chadstone")  # from g:location
    p = titles["Target Mackay - Holiday Casual"]
    assert p.source == "ats_successfactors" and p.posted_at_source == "observed"
    assert p.url.startswith("https://jobs.target.com.au/job/") and p.source_id == "jobs.target.com.au:1364709166"
    assert "<" not in p.description and "casual team member" in p.description


def test_successfactors_conditional_get():
    class Http(FakeHttp):
        def request(self, method, url, headers=None, **kw):
            self.calls.append((method, url, headers))
            if headers and headers.get("If-None-Match") == '"v1"':
                return FakeResponse("", {}, status=304)
            return FakeResponse(fixture_text("successfactors_feed.xml"), {"ETag": '"v1"'})
    http = Http({})
    ctx = make_ctx(http, [emp("successfactors", host="h.example", feed_url="https://h.example/googlefeed.xml")])
    assert len(ats_successfactors.collect(ctx)) == 6
    assert ats_successfactors.collect(ctx) == [] and not ctx.errors        # 304 -> nothing to parse
    assert http.calls[1][2] == {"If-None-Match": '"v1"'}


# ---------------------------------------------------------------- Oracle HCM
def test_oracle_au_gate_preserves_provider_location_order_and_url():
    http = FakeHttp({"recruitingCEJobRequisitions": fixture_json("oracle_reqs.json")})
    e = emp("oracle-hcm", name="Suncorp Group", host="fa-x.oraclecloud.com", site="CX_1")
    ctx = make_ctx(http, [e])
    out = ats_oracle.collect(ctx)
    assert ctx.raw_count == 3 and len(out) == 2                              # Auckland dropped
    multi = next(p for p in out if "Underwriter" in p.title)
    assert 'Heatherton, VIC' in multi.location
    assert not multi.location.startswith('Heatherton, VIC')  # no inherited VIC priority
    assert multi.url == "https://fa-x.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1001766"
    assert multi.posted_at.startswith("2026-10-02") and multi.posted_at_source == "provider"
    assert multi.work_type == "FT"
    assert "offset=0" in http.calls[0][1] and "sortBy=POSTING_DATES_DESC" in http.calls[0][1]
    assert len(http.calls) == 1                                             # total 3 < page


def test_oracle_stops_paging_at_known():
    page = fixture_json("oracle_reqs.json")
    page["items"][0]["TotalJobsCount"] = 500
    page["items"][0]["requisitionList"] = page["items"][0]["requisitionList"] * 9   # 27 >= PAGE rows
    http = FakeHttp({"recruitingCEJobRequisitions": page})
    e = emp("oracle-hcm", host="h", site="CX_1")
    ctx = make_ctx(http, [e], known={"h:CX_1:1001770"})
    ats_oracle.collect(ctx)
    assert len(http.calls) == 1
    ctx2 = make_ctx(FakeHttp({"recruitingCEJobRequisitions": page}), [e])
    ctx2.tier = "slow"
    ats_oracle.collect(ctx2)
    assert len(ctx2.http.calls) == 4                                       # deep: 4 pages max


# ---------------------------------------------------------------- Careers.Vic
def test_careers_vic_parse_and_grades():
    out = careers_vic.parse_page(fixture_text("careers_vic_page.html"))
    by = {p.title: p for p in out}
    po = by["Project Officer"]
    assert po.source_id == "89400" and po.url == "https://www.careers.vic.gov.au/job/project-officer-89400"
    assert po.company == "Department of Education" and po.state == "VIC" and po.classification == "VPS 3"
    assert po.work_type == "FT" and po.salary_min == 81496 and po.raw["applications close"]
    assert by["Executive Director Building Policy and Reform"].classification == "VPS SES2"
    admin = by["Administration Officer"]
    assert admin.classification == "VPS 2" and admin.state is None          # "Interstate" location


def test_careers_vic_rules_use_grade():
    rules = Rules(make_config().rules)
    out = {p.title: p for p in careers_vic.parse_page(fixture_text("careers_vic_page.html"))}
    po = rules.evaluate(out["Project Officer"])                           # VPS 3, no arm keyword
    assert po.reason == "title"
    hr = Posting(source="careers_vic", source_id="1", url="https://x/1", title="HR Administrator",
                 location="Melbourne - CBD, VIC", state="VIC", classification="VPS 5")
    assert rules.evaluate(hr).reason == "seniority"
    hr.classification = "VPS 3"
    d = rules.evaluate(hr)
    assert d.matched and "entry_level" in d.flags and d.rules["classification"] == "VPS 3"
    hr.classification = "VPS 4"
    d = rules.evaluate(hr)
    assert d.matched and "entry_level" not in d.flags
    assert rules.classification_hit(out["Executive Director Building Policy and Reform"].classification)


def test_careers_vic_pages_fast_vs_deep_and_stop_at_known():
    page = fixture_text("careers_vic_page.html")

    class Http(FakeHttp):
        def get_text(self, url, params=None, robots=False, **kw):
            self.calls.append(("GET", url, params))
            n = params["page"]
            blocks = page.split('<rpl-content class="job-searchResult">')[1:]
            # 15 unique jobs per page: renumber ids by page
            body = "".join('<rpl-content class="job-searchResult">' +
                           b.replace("-8", f"-{n}{i}8", 1) for i, b in enumerate(blocks * 3))
            return body
    reg = [emp("careers_vic", name="Victorian Government (Careers.Vic)")]
    fast = make_ctx(Http({}), reg)
    assert len(careers_vic.collect(fast)) == 30 and len(fast.http.calls) == 2
    deep = make_ctx(Http({}), reg)
    deep.tier = "slow"
    careers_vic.collect(deep)
    assert len(deep.http.calls) == 10
    first_id = careers_vic.parse_page(Http({}).get_text("u", {"page": 0}))[0].source_id
    known = make_ctx(Http({}), reg, known={first_id})
    known.tier = "slow"
    careers_vic.collect(known)
    assert len(known.http.calls) == 1                                      # stops at a seen id
    assert careers_vic.collect(make_ctx(Http({}), [])) == []                # no registry entry: off


def test_careers_vic_robots():
    ctx = make_ctx(FakeHttp({"careers.vic.gov.au": "x"}, disallow=("careers.vic",)),
                   [emp("careers_vic")])
    assert careers_vic.collect(ctx) == [] and "robots" in ctx.errors[0]


# ---------------------------------------------------------------- Phenom
def test_phenom_embedded_state_and_widget_paging():
    http = FakeHttp({"colescareers.com.au/au/en/search-results": fixture_text("phenom_search.html"),
                     "colescareers.com.au/widgets": fixture_json("phenom_widgets.json")})
    ctx = make_ctx(http, [emp("phenom", name="Coles Group",
                              careers_url="https://colescareers.com.au/au/en/search-results")])
    out = ats_phenom.collect(ctx)
    assert ctx.raw_count == 4 and len(out) == 3                              # NZ row dropped
    p = out[0]
    assert p.url.startswith("https://colescareers.com.au/au/en/job/191364/") and p.state == "VIC"
    assert p.posted_at_source == "provider" and p.source_id == "Coles Group:191364"
    post = [c for c in http.calls if c[0] == "POST"][0]
    assert post[2]["refNum"] == "COGRAU" and post[2]["from"] == 2 and post[2]["size"] == 100
    assert post[2]["lang"] == "en_au" and post[2]["pageId"] == "page20"


def test_phenom_robots_and_not_phenom():
    ctx = make_ctx(FakeHttp({"x.example": "<html>no state</html>"}),
                   [emp("phenom", careers_url="https://x.example/au/en/search-results")])
    assert ats_phenom.collect(ctx) == [] and "phApp.ddo" in ctx.errors[0]
    ctx2 = make_ctx(FakeHttp({"x.example": "y"}, disallow=("x.example",)),
                    [emp("phenom", careers_url="https://x.example/au/en/search-results")])
    assert ats_phenom.collect(ctx2) == [] and "robots" in ctx2.errors[0]


# ---------------------------------------------------------------- Atlassian
def test_atlassian_au_only():
    ctx = make_ctx(FakeHttp({"atlassian.com/endpoint/careers/listings": fixture_json("atlassian_listings.json")}),
                   [emp("atlassian", name="Atlassian", state="NSW")])
    out = ats_atlassian.collect(ctx)
    assert ctx.raw_count == 2 and len(out) == 1
    p = out[0]
    assert "Melbourne, Australia" in p.location and p.url.startswith("https://") and "icims.com" in p.url
    assert p.posted_at_source == "observed"


# ---------------------------------------------------------------- JSON-LD (TAFE portal)
def test_jsonld_capital_title_no_follow_and_url_pairing():
    http = FakeHttp({"jobs.tafe.vic.gov.au": fixture_text("jsonld_tafe_listing.html")})
    e = emp("jsonld", name="Victorian TAFEs (Jobs at TAFE portal)", follow_links=False,
            careers_url="https://jobs.tafe.vic.gov.au/jobs-in-any-industry/page-size-50?state=VIC",
            url_pattern=r"https://jobs\.tafe\.vic\.gov\.au/[a-z0-9/-]*?/job/\d+/[a-z0-9-]+")
    ctx = make_ctx(http, [e])
    out = jsonld_pages.collect(ctx)
    assert [p.title for p in out] == ["Equity And Inclusion Lead", "Teacher - Senior Secondary",
                                      "Casual Teacher Accounting & Bookkeeping"]
    assert len(http.calls) == 1                                              # follow_links: false honoured
    assert len({p.url for p in out}) == 3
    assert out[2].url.endswith("/job/217097/casual-teacher-accounting-bookkeeping")
    assert out[0].company == "Gordon Institute of TAFE" and out[0].state == "VIC"


def test_jsonld_listing_without_urls_gets_distinct_ids():
    http = FakeHttp({"jobs.tafe.vic.gov.au": fixture_text("jsonld_tafe_listing.html")})
    e = emp("jsonld", follow_links=False, careers_url="https://jobs.tafe.vic.gov.au/list")
    out = jsonld_pages.collect(make_ctx(http, [e]))
    assert len({p.source_id for p in out}) == 3 and all(p.url == "" for p in out)


# ---------------------------------------------------------------- arm map
def test_registry_arm_map():
    rules = Rules(make_config().rules)
    assert rules.rule_arms_for(["business_analyst", "reception"]) == \
        ["management_analyst", "ict_business_analyst", "receptionist"]
    assert rules.rule_arms_for(["payroll_clerk", "nonsense"]) == ["payroll_clerk"]
    ids = {a.id for a in rules.arms}
    assert all(i in ids for v in rules.registry_arm_map.values() for i in v)


# ---------------------------------------------------------------- pipeline guards
def test_tier_all_runs_shared_collector_once():
    names = pipeline.tier_collectors(make_config(), "all", None)
    assert names.count("careers_vic") == 1


def test_cli_exit_code_all_failed():
    assert cli.all_failed({"collectors": [{"status": "error"}, {"status": "error"}]})
    assert not cli.all_failed({"collectors": [{"status": "error"}, {"status": "partial"}]})
    assert not cli.all_failed({"collectors": []})


def test_cli_run_exits_1_when_every_collector_errors(tmp_path, monkeypatch):
    summary = {"run_id": 1, "requests": 0, "pruned": 0,
               "alerts": {"board": 0},
               "collectors": [{"collector": "a", "status": "error", "fetched": 0, "au_kept": 0, "vic": 0,
                               "new": 0, "matched": 0, "queued": 0, "latency_ms": 5, "errors": ["x"]}]}
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: summary)
    monkeypatch.setenv("JOBWATCH_DB", str(tmp_path / "t.db"))
    from conftest import confirm_discovery
    confirm_discovery(make_config())
    assert cli.main(["run", "--tier", "fast", "--dry-run"]) == 1
    summary["collectors"].append({**summary["collectors"][0], "status": "ok", "errors": []})
    assert cli.main(["run", "--tier", "fast", "--dry-run"]) == 0


def test_unknown_location_vic_employer_but_title_names_other_state():
    rules = Rules(make_config().rules, [{"name": "bp Australia", "state": "VIC"}])
    p = Posting(source="x", source_id="1", url="https://x/1", company="bp Australia", location="",
                title="Customer Service Representative (Casual) - bp Andergrove (Oak St), QLD")
    assert rules.evaluate(p).reason == "location"
    p.title = "Customer Service Representative (Casual) - bp Eltham, VIC"
    assert rules.evaluate(p).matched


def test_wave2_precision_excludes():
    rules = Rules(make_config().rules)
    def ev(t):
        return rules.evaluate(Posting(source="x", source_id=t, url=f"https://x/{t}", title=t,
                                      location="Melbourne VIC"))
    assert not ev("Warehouse Team Member").matched
    assert not ev("Service Desk Analyst and Administrator").matched
    assert not ev("Medical Administration Registrar").matched
    assert not ev("Contracts Administrator").matched
    assert not ev("Research Fellow – Data Scientist / Biostatistician").matched
    # shop-floor arms are switched off (owner 2026-10-05/07); office roles still match
    assert not ev("Retail Team Member").matched and ev("Administration Officer").matched
