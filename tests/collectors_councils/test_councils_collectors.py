"""Council ATS collectors (offline fixtures only): Pulse, RecruitmentHub, jobs/search sites, ELMO, TechOne, Scout shared host."""
import json

import pytest

from conftest import FakeHttp, fixture_json, fixture_text, make_ctx
from jobwatch import collectors as registry
from jobwatch.collectors import (ats_elmo, ats_jobs_search, ats_pulse, ats_recruitmenthub, ats_scouttalent,
                                 ats_techone)
from jobwatch.config import DEFAULT_SETTINGS
from jobwatch.util.http import HttpError


def council(provider, **kw):
    return {"name": kw.pop("name", "Example Council"), "sector": "council", "provider": provider, "state": "VIC",
            "enabled": True, **kw}


# ------------------------------------------------------------------ registry / tiers
@pytest.mark.parametrize("name", ["ats_pulse", "ats_recruitmenthub", "ats_jobs_search", "ats_elmo", "ats_techone"])
def test_new_collectors_registered_and_in_fast_tier(name):
    assert name in registry.COLLECTORS
    assert registry.get(name).NAME == name
    assert name in DEFAULT_SETTINGS["tiers"]["fast"]


# ------------------------------------------------------------------ Pulse
def test_pulse_json_fields():
    http = FakeHttp({"banyule.pulsesoftware.com/WebServices/RCM/Jobs/Jobs": fixture_json("councils_pulse.json")})
    ctx = make_ctx(http, [council("pulse", name="Banyule City Council", tenant="banyule")])
    out = ats_pulse.collect(ctx)
    assert ctx.raw_count == 3 and len(out) == 3 and not ctx.errors
    p = out[0]
    assert p.source == "ats_pulse" and p.title == "Senior Procurement Coordinator"
    assert p.source_id == "banyule:xINhUW" and p.state == "VIC" and p.origin == "Banyule City Council"
    assert p.url.startswith("https://banyule.pulsesoftware.com/Pulse/apply/xINhUW/")
    assert "source=public" not in p.url                      # tracking param stripped by canonical_url
    assert p.posted_at.startswith("2026-10-05") and p.posted_at_source == "provider"
    assert p.salary_min == 147000 and p.salary_max == 150000 and p.salary_unit == "year"
    assert p.work_type == "FT" and "<" not in p.description
    assert out[2].salary_unit == "hour"
    url, params = http.calls[0][1], http.calls[0][2]
    assert "internalOnly=false" in url


def test_pulse_robots_and_bad_json_are_errors_not_crashes():
    http = FakeHttp({"pulsesoftware.com": "<html>not json</html>"})
    ctx = make_ctx(http, [council("pulse", tenant="x")])
    assert ats_pulse.collect(ctx) == [] and "did not return JSON" in ctx.errors[0]
    http = FakeHttp({"pulsesoftware.com": {"Jobs": []}}, disallow=("pulsesoftware.com",))
    ctx = make_ctx(http, [council("pulse", tenant="x")])
    assert ats_pulse.collect(ctx) == [] and "robots" in ctx.errors[0]


def test_pulse_skips_rows_without_title_or_link():
    out = ats_pulse.parse_jobs({"Jobs": [{"JobInfo": {"Title": ""}, "LinkId": "a"},
                                         {"JobInfo": {"Title": "Ok"}, "LinkId": ""}]}, council("pulse", tenant="x"))
    assert out == []


# ------------------------------------------------------------------ RecruitmentHub
def test_recruitmenthub_list_fields():
    http = FakeHttp({"maribyrnong.recruitmenthub.com.au/Vacancies/": fixture_text("councils_recruitmenthub.html")})
    emp = council("recruitmenthub", name="Maribyrnong City Council", tenant="maribyrnong",
                  careers_url="https://maribyrnong.recruitmenthub.com.au/Vacancies/")
    ctx = make_ctx(http, [emp])
    out = ats_recruitmenthub.collect(ctx)
    assert len(out) == 2 and ctx.raw_count == 2 and not ctx.errors
    p = out[0]
    assert p.title == "Executive Assistant Project Officer" and p.location == "Footscray" and p.state == "VIC"
    assert p.source_id == "maribyrnong:6937220"
    assert p.url == "https://maribyrnong.recruitmenthub.com.au/Vacancies/6937220/title/Executive-Assistant-Project-Officer"
    assert p.work_type == "FT" and p.salary_min == 99705 and p.salary_max == 108027
    assert p.raw["closing"] == "21 Oct 2026" and p.posted_at_source == "observed"
    assert "Apply Now" not in p.description


def test_recruitmenthub_site_down_is_error():
    http = FakeHttp({"recruitmenthub.com.au": fixture_text("councils_recruitmenthub_down.html")})
    ctx = make_ctx(http, [council("recruitmenthub", tenant="moorabool",
                                  careers_url="https://moorabool.recruitmenthub.com.au/Vacancies/")])
    assert ats_recruitmenthub.collect(ctx) == [] and "not available" in ctx.errors[0]


# ------------------------------------------------------------------ jobs/search card sites
def test_jobs_search_cards():
    http = FakeHttp({"careers.kingston.vic.gov.au/jobs/search": fixture_text("councils_jobs_search.html")})
    emp = council("jobs-search", name="City of Kingston", careers_url="https://careers.kingston.vic.gov.au/jobs/search")
    ctx = make_ctx(http, [emp])
    out = ats_jobs_search.collect(ctx)
    assert len(out) == 2 and ctx.raw_count == 2
    p = out[0]
    assert p.source == "ats_jobs_search" and p.state == "VIC" and p.title
    assert p.url.startswith("https://careers.kingston.vic.gov.au/jobs/")
    assert p.source_id == "careers.kingston.vic.gov.au:" + p.url.rsplit("/", 1)[-1]
    assert p.location and "Cheltenham" in p.location or "Mentone" in p.location
    assert p.raw["category"] and p.description


def test_jobs_search_multiple_locations_and_short_list_error():
    http = FakeHttp({"careers.mitchellshire.vic.gov.au": fixture_text("councils_jobs_search_multiloc.html")})
    emp = council("jobs-search", name="Mitchell Shire Council",
                  careers_url="https://careers.mitchellshire.vic.gov.au/jobs/search")
    ctx = make_ctx(http, [emp])
    out = ats_jobs_search.collect(ctx)
    assert len(out) == 1 and out[0].location == "Melbourne, Mitchell Shire, Wallan"
    assert "8 entries but 1 parsed" in ctx.errors[0]          # footer total larger than cards parsed


def test_jobs_search_ignores_other_hosts():
    page = fixture_text("councils_jobs_search.html").replace("careers.kingston.vic.gov.au", "evil.example.com")
    out, _ = ats_jobs_search.parse_list(page, council("jobs-search",
                                                      careers_url="https://careers.kingston.vic.gov.au/jobs/search"))
    assert out == []


# ------------------------------------------------------------------ ELMO
def test_elmo_robots_wildcards():
    robots = fixture_text("councils_elmo_robots.txt")
    assert ats_elmo.robots_allows(robots, "/careers/cosjobs/jobs")
    assert ats_elmo.robots_allows(robots, "/careers/cosjobs/job/view/12")
    assert not ats_elmo.robots_allows(robots, "/careers/cosjobs/apply")
    assert not ats_elmo.robots_allows(robots, "/other")
    assert ats_elmo.robots_allows("User-agent: *\nDisallow:\n", "/anything")
    assert not ats_elmo.robots_allows("User-agent: jobwatch\nDisallow: /\nUser-agent: *\nAllow: /\n", "/x")
    assert ats_elmo.robots_allows("User-agent: other\nDisallow: /\n", "/x")


def test_elmo_list_fields_and_robots_fetch():
    http = FakeHttp({"/robots.txt": fixture_text("councils_elmo_robots.txt"),
                     "cos.elmotalent.com.au/careers/cosjobs/jobs": fixture_text("councils_elmo.html")})
    emp = council("elmo", name="City of Stonnington", careers_url="https://cos.elmotalent.com.au/careers/cosjobs/jobs")
    ctx = make_ctx(http, [emp])
    out = ats_elmo.collect(ctx)
    assert len(out) == 2 and ctx.raw_count == 2 and not ctx.errors
    p = out[0]
    assert p.source_id == "cosjobs:1516" and p.title == "Child and Youth Community Hub Worker"
    assert p.url == "https://cos.elmotalent.com.au/careers/cosjobs/job/view/1516"
    assert p.work_type == "casual" and p.state == "VIC" and "Prahran" in p.location
    assert p.raw["closing"].startswith("2026-10-13") and p.posted_at_source == "observed"
    assert http.calls[0][1].endswith("/robots.txt")            # robots read before the list page


def test_elmo_robots_disallow_and_missing_robots():
    emp = council("elmo", careers_url="https://x.elmotalent.com.au/careers/x/jobs")
    http = FakeHttp({"/robots.txt": "User-agent: *\nDisallow: /\n", "elmotalent.com.au/careers": fixture_text("councils_elmo.html")})
    ctx = make_ctx(http, [emp])
    assert ats_elmo.collect(ctx) == [] and "robots.txt disallows" in ctx.errors[0]
    assert not any("/careers/" in c[1] for c in http.calls)     # list page never fetched
    http = FakeHttp({"/robots.txt": 404, "elmotalent.com.au/careers": fixture_text("councils_elmo.html")})
    assert len(ats_elmo.collect(make_ctx(http, [emp]))) == 2    # 404 robots = allowed


# ------------------------------------------------------------------ TechOne RaaS JSON
def test_techone_dataset():
    emp = council("techone", name="Greater Bendigo City Council", careers_url="https://www.bendigo.vic.gov.au/x",
                  api_url="https://mingle-ionapi.example/api/Recruitment_Advertisement_List?page=1", location="Bendigo, VIC")
    http = FakeHttp({"mingle-ionapi.example": fixture_json("councils_techone.json")})
    ctx = make_ctx(http, [emp])
    out = ats_techone.collect(ctx)
    assert len(out) == 2 and ctx.raw_count == 2
    p = out[0]
    assert p.source_id == "Greater Bendigo City Council:JR0036" and p.title == "Senior Local Laws Officer"
    assert p.posted_at.startswith("2026-09-28") and p.posted_at_source == "provider"
    assert p.work_type == "PT" and p.location == "Bendigo, VIC" and "t1cloud" in p.url
    assert p.raw["EXPIRYDATE"].startswith("2026-10-12")


def test_techone_http_error_recorded():
    emp = council("techone", api_url="https://mingle-ionapi.example/x")
    ctx = make_ctx(FakeHttp({"mingle-ionapi.example": 403}), [emp])
    assert ats_techone.collect(ctx) == [] and "403" in ctx.errors[0]


# ------------------------------------------------------------------ Scout Talent shared-host tenant (Baw Baw)
def test_scouttalent_shared_host_needs_ref_prefix():
    page = fixture_text("councils_scout_shared_host.html")
    http = FakeHttp({"bbsc-external.applynow.net.au": page})
    with_prefix = council("scouttalent", name="Baw Baw Shire Council", tenant="bbsc-external", ref_prefix="BAW")
    ctx = make_ctx(http, [with_prefix])
    out = ats_scouttalent.collect(ctx)
    refs = sorted(p.source_id for p in out)
    assert refs == ["bbsc-external:BAW601", "bbsc-external:BAW632", "bbsc-external:BAW634"]   # foreign ROS row dropped
    assert all(p.state == "VIC" for p in out)
    without = council("scouttalent", tenant="bbsc-external")
    only_own_host = ats_scouttalent.collect(make_ctx(http, [without]))
    assert [p.source_id for p in only_own_host] == ["bbsc-external:BAW632"]   # old behaviour unchanged


# ------------------------------------------------------------------ merged council registry
def test_merged_council_registry_is_wellformed():
    """The council wave is merged into config/employers.yaml. This used to read an untracked
    employers.councils.pending.yaml and skipped in every checkout, so it never ran at all."""
    import yaml
    from jobwatch.config import DEFAULT_CONFIG_DIR
    catalog = yaml.safe_load((DEFAULT_CONFIG_DIR / "employers.yaml").read_text())
    entries = [e for e in catalog["employers"] if e.get("sector") == "council"]
    names = [e["name"] for e in entries]
    assert len(names) == len(set(names)) >= 35
    keys = {"name", "sector", "arms", "state", "au_scope", "provider", "enabled", "verified_at", "notes"}
    known = {"pageup", "scouttalent", "smartrecruiters", "oracle-hcm", "pulse", "recruitmenthub", "jobs-search", "elmo",
             "techone", "other"}
    provider_collector = {"pageup": "ats_pageup", "scouttalent": "ats_scouttalent", "smartrecruiters": "ats_smartrecruiters",
                          "oracle-hcm": "ats_oracle", "pulse": "ats_pulse", "recruitmenthub": "ats_recruitmenthub",
                          "jobs-search": "ats_jobs_search", "elmo": "ats_elmo", "techone": "ats_techone"}
    for e in entries:
        assert keys <= set(e), e["name"]
        assert e["state"] == "VIC" and e["au_scope"] in ("melbourne", "victoria")
        assert e["provider"] in known and isinstance(e["enabled"], bool) and e["notes"]
        if e["enabled"]:
            assert e["provider"] != "other" and e["verified_counts"]["total"] >= 0
            assert provider_collector[e["provider"]] in registry.COLLECTORS
