import pandas as pd

from conftest import FakeHttp, fixture_json, fixture_text, make_ctx
from jobwatch.collectors import (ats_ashby, ats_employmenthero, ats_greenhouse, ats_lever, ats_pageup,
                                 ats_scouttalent, ats_smartrecruiters, ats_workable, ats_workday,
                                 jobspy_src, jsonld_pages, reddit, rss, seek)


def emp(provider, **kw):
    return {"name": kw.pop("name", "Example Co"), "provider": provider, "tenant": "exampleco",
            "state": "VIC", "enabled": True, **kw}


def test_greenhouse_au_gate_and_fields():
    http = FakeHttp({"boards-api.greenhouse.io": fixture_json("greenhouse.json")})
    ctx = make_ctx(http, [emp("greenhouse", name="Culture Amp")])
    out = ats_greenhouse.collect(ctx)
    assert ctx.raw_count == 2 and len(out) == 1                 # Chicago dropped
    p = out[0]
    assert p.location == "Melbourne" and p.state == "VIC" and p.posted_at_source == "provider"
    assert p.description and "<" not in p.description[:50]
    assert p.source_id.startswith("exampleco:") and p.url.startswith("https://job-boards.greenhouse.io/")
    assert http.calls[0][2] == {"content": "true"}


def test_greenhouse_error_recorded_not_raised():
    http = FakeHttp({"boards-api.greenhouse.io": 429})
    ctx = make_ctx(http, [emp("greenhouse")])
    assert ats_greenhouse.collect(ctx) == []
    assert ctx.errors and "429" in ctx.errors[0]


def test_lever():
    ctx = make_ctx(FakeHttp({"api.lever.co": fixture_json("lever.json")}), [emp("lever")])
    out = ats_lever.collect(ctx)
    assert [p.source_id for p in out] == ["exampleco:lev-1"]
    p = out[0]
    assert p.work_type == "PT" and p.salary_min == 65000 and p.salary_unit == "year"
    assert p.posted_at.startswith("2026-")


def test_ashby_strips_tracking_and_gates():
    ctx = make_ctx(FakeHttp({"api.ashbyhq.com": fixture_json("ashby.json")}), [emp("ashby")])
    out = ats_ashby.collect(ctx)
    assert len(out) == 1
    p = out[0]
    assert p.url == "https://jobs.ashbyhq.com/exampleco/aaaa-1111"
    assert p.salary_min == 70000 and p.salary_max == 80000 and p.work_type == "FT"


def test_workable():
    ctx = make_ctx(FakeHttp({"apply.workable.com": fixture_json("workable.json")}), [emp("workable")])
    out = ats_workable.collect(ctx)
    assert [p.source_id for p in out] == ["exampleco:ABC123"]
    assert out[0].work_type == "casual" and out[0].state == "VIC"


def test_smartrecruiters_detail_only_for_relevant_titles():
    http = FakeHttp({"exampleco/postings/744000000000001": fixture_json("smartrecruiters_detail.json"),
                     "/companies/exampleco/postings": fixture_json("smartrecruiters.json")})
    ctx = make_ctx(http, [emp("smartrecruiters")])
    out = ats_smartrecruiters.collect(ctx)
    assert len(out) == 2
    ar = next(p for p in out if "Receivable" in p.title)
    assert "3 years" in ar.description
    assert sum(1 for c in http.calls if "/postings/7440" in c[1]) == 1  # director not fetched
    assert next(p for p in out if "Director" in p.title).location == "Sydney, Australia"


def test_smartrecruiters_skips_detail_for_known():
    http = FakeHttp({"/companies/exampleco/postings": fixture_json("smartrecruiters.json")})
    ctx = make_ctx(http, [emp("smartrecruiters")], known={"exampleco:744000000000001"})
    ats_smartrecruiters.collect(ctx)
    assert not ctx.errors and all("/postings/7440" not in c[1] for c in http.calls)


def test_workday_ambiguous_locations_resolved_by_detail():
    http = FakeHttp({
        "/jobs": fixture_json("workday_jobs.json"),
        "Customer-Service-Consultant": fixture_json("workday_detail_cs.json"),
        "Analyst--Business-Analyst": fixture_json("workday_detail_vn.json"),
        "Data-Entry-Operator": fixture_json("workday_detail_de.json"),
    })
    ctx = make_ctx(http, [emp("workday", name="NAB", host="nab.wd3.myworkdayjobs.com", tenant="nab",
                              site="nab_careers")])
    out = ats_workday.collect(ctx)
    titles = sorted(p.title for p in out)
    assert titles == ["Customer Service Consultant", "Data Entry Operator"]   # VN dropped
    cs = next(p for p in out if p.title.startswith("Customer"))
    assert cs.url == "https://nab.wd3.myworkdayjobs.com/nab_careers/job/Melbourne-VIC/Customer-Service-Consultant_JR100001"
    assert cs.work_type == "PT" and cs.source_id == "nab:JR100001" and cs.posted_at.startswith("2026-10-05")
    post = [c for c in http.calls if c[0] == "POST"][0]
    assert post[1] == "https://nab.wd3.myworkdayjobs.com/wday/cxs/nab/nab_careers/jobs"
    assert post[2]["limit"] == 20 and "searchText" in post[2] and "appliedFacets" in post[2]


def test_pageup_feed():
    ctx = make_ctx(FakeHttp({"pageuppeople.com": fixture_text("pageup.xml")}),
                   [emp("pageup", name="Asahi Beverages", tenant="527")])
    out = ats_pageup.collect(ctx)
    assert len(out) == 2 and ctx.raw_count == 2
    p = out[0]
    assert p.company == "Asahi Beverages" and p.location == "Melbourne" and p.state == "VIC"
    assert p.posted_at_source == "provider" and p.raw["closingDate"]
    assert p.description and "&lt;" not in p.description


def test_employmenthero():
    ctx = make_ctx(FakeHttp({"services.employmenthero.com": fixture_json("employmenthero.json")}),
                   [emp("employmenthero")])
    out = ats_employmenthero.collect(ctx)
    assert len(out) == 1
    p = out[0]
    assert p.url == "https://employmenthero.com/jobs/position/example-bookkeeper-abc12"
    assert p.salary_unit == "hour" and p.salary_min == 38.0 and p.work_type == "PT" and p.state == "VIC"


def test_scouttalent_index_blocks():
    page = fixture_text("scouttalent_index.html")
    ctx = make_ctx(FakeHttp({"applynow.net.au": page}),
                   [emp("scouttalent", name="Portland District Health", tenant="portland-district-health-portal")])
    out = ats_scouttalent.collect(ctx)
    assert len(out) == 2
    assert all(p.url.startswith("https://portland-district-health-portal.applynow.net.au/jobs/") for p in out)
    assert all(p.state == "VIC" for p in out)


def test_scouttalent_ignores_other_tenants_and_robots():
    ctx = make_ctx(FakeHttp({"applynow.net.au": fixture_text("scouttalent_index.html")}),
                   [emp("scouttalent", tenant="someoneelse")])
    assert ats_scouttalent.collect(ctx) == []
    ctx2 = make_ctx(FakeHttp({"applynow.net.au": "x"}, disallow=("applynow",)), [emp("scouttalent")])
    assert ats_scouttalent.collect(ctx2) == [] and "robots" in ctx2.errors[0]


def test_jsonld_pages_follow_links_and_robots():
    http = FakeHttp({
        "careers.example.vic.gov.au/careers": fixture_text("jsonld_careers.html"),
        "/jobs/102-payroll-officer": fixture_text("jsonld_detail_payroll.html"),
        "/jobs/103-civil-engineer": fixture_text("jsonld_detail_engineer.html"),
    }, disallow=("103-civil",))
    e = emp("jsonld", name="Example Council", careers_url="https://careers.example.vic.gov.au/careers")
    ctx = make_ctx(http, [e])
    out = jsonld_pages.collect(ctx)
    titles = [p.title for p in out]
    assert titles == ["Customer Service Officer", "Payroll Officer"]
    cso = out[0]
    assert cso.state == "VIC" and cso.salary_unit == "hour" and cso.work_type == "PT"
    assert cso.description == "Serve customers at our front counter."
    assert any("robots" in e for e in ctx.errors)                    # engineer page disallowed
    assert not any("other.example.com" in c[1] for c in http.calls)   # off-site link not followed
    # the careers page's own JobPosting (101) is not refetched as a detail page
    assert not any("101-customer" in c[1] for c in http.calls)


def test_jsonld_cap():
    http = FakeHttp({"careers.example.vic.gov.au/careers": fixture_text("jsonld_careers.html"),
                     "/jobs/": fixture_text("jsonld_detail_payroll.html")})
    e = emp("jsonld", careers_url="https://careers.example.vic.gov.au/careers", detail_cap=1)
    ctx = make_ctx(http, [e])
    jsonld_pages.collect(ctx)
    assert sum(1 for c in http.calls if "/jobs/" in c[1]) == 1


def test_rss_generic_and_pageup_format():
    feeds = {"feeds": [
        {"name": "Example", "url": "https://jobs.example.org.au/rss", "company": "Example Org"},
        {"name": "LT", "url": "https://jobs.latrobe.example/latest_jobs.rss", "format": "pageup",
         "company": "La Trobe", "au": True},
        {"name": "Off", "url": "https://off.example/rss", "enabled": False}]}
    http = FakeHttp({"jobs.example.org.au": fixture_text("rss_generic.xml"),
                     "latest_jobs.rss": fixture_text("pageup.xml")})
    ctx = make_ctx(http, feeds=feeds)
    out = rss.collect(ctx)
    assert {p.origin for p in out} == {"Example", "LT"}
    ex = [p for p in out if p.origin == "Example"]
    assert len(ex) == 2                    # both AU (Melbourne + Brisbane), filter decides later
    assert ex[0].url == "https://jobs.example.org.au/job/1"
    assert not any("off.example" in c[1] for c in http.calls)


def test_reddit_streams_and_privacy():
    conf = {"reddit": {"feeds": [{"sub": "melbourne", "stream": "auto", "location": "Melbourne VIC"}], "requests_per_run": 4,
                       "hiring_keywords": [r"\[hiring\]", r"\bhiring\b"],
                       "hiring_location": ["melbourne", r"\bvic\b", r"\bremote\b"],
                       "not_hiring": ["anyone hiring", r"\?\s*$"],
                       "chatter_themes": {"callbacks_ghosting": ["callback"], "interviews": ["interview"],
                                          "job_search": ["job market"]}}}
    http = FakeHttp({"reddit.com/r/melbourne/new/.rss": fixture_text("reddit_new.xml")},
                    headers={"x-ratelimit-remaining": "5"})
    ctx = make_ctx(http, feeds=conf)
    slept = []
    out = reddit.collect(ctx, sleep=slept.append)
    assert [p.title for p in out] == ["Casual Barista - Fitzroy"]
    assert out[0].location == "Melbourne VIC" and out[0].flags == ["reddit"]
    streams = {r["id"]: r["stream"] for r in ctx.reddit_posts}
    assert streams == {"t3_aaa111": "hiring", "t3_bbb222": "chatter"}
    chatter = next(r for r in ctx.reddit_posts if r["stream"] == "chatter")
    assert set(chatter["themes"]) == {"callbacks_ghosting", "interviews", "job_search"}
    assert all("example_user" not in (r["summary"] or "") for r in ctx.reddit_posts)
    assert http.calls[0][1] == "https://www.reddit.com/r/melbourne/new/.rss"


def test_reddit_stops_when_rate_window_spent():
    conf = {"reddit": {"feeds": [{"sub": "a"}, {"sub": "b"}], "max_wait_seconds": 10,
                       "hiring_keywords": [], "chatter_themes": {}}}
    http = FakeHttp({"reddit.com": fixture_text("reddit_new.xml")},
                    headers={"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "300"})
    ctx = make_ctx(http, feeds=conf)
    reddit.collect(ctx, sleep=lambda s: None)
    assert len(http.calls) == 1


def test_reddit_search_url():
    assert reddit.feed_url({"sub": "auscorp", "q": "graduate OR interview"}) == \
        "https://www.reddit.com/r/auscorp/search.rss?q=graduate+OR+interview&restrict_sr=1&sort=new"


def test_seek_parse_pages_and_backoff():
    page = fixture_json("seek_search.json")
    searches = {"seek": {"keywords": ["receptionist", "data entry"], "page_size": 22, "max_pages": 2}}
    http = FakeHttp({"seek.com.au/api/jobsearch": page})
    ctx = make_ctx(http, searches=searches)
    out = seek.collect(ctx)
    assert len(out) == 2                                 # NZ row gated, dupes across keywords removed
    p = out[0]
    assert p.url.startswith("https://www.seek.com.au/job/") and p.state == "VIC" and p.work_type == "PT"
    params = http.calls[0][2]
    assert params["where"] == "Brunswick, VIC" and params["dateRange"] == 1 and params["siteKey"] == "AU-Main"
    assert len(http.calls) == 2                          # 3 rows < page size: 1 page per keyword
    blocked = FakeHttp({"seek.com.au": 429})
    ctx2 = make_ctx(blocked, searches=searches)
    assert seek.collect(ctx2) == [] and len(blocked.calls) == 1 and "429" in ctx2.errors[0]


def test_seek_respects_robots_when_asked():
    http = FakeHttp({"seek.com.au": fixture_json("seek_search.json")}, disallow=("/api/jobsearch",))
    ctx = make_ctx(http, searches={"seek": {"keywords": ["x"], "respect_robots": True}})
    assert seek.collect(ctx) == [] and "robots" in ctx.errors[0]


def test_jobspy_rows_and_args():
    captured = {}

    def fake_scrape(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame([
            {"id": "li-1", "site": "linkedin", "job_url": "https://www.linkedin.com/jobs/view/1?refId=abc&trackingId=x",
             "title": "Receptionist", "company": "Clinic", "location": "Melbourne, Victoria, Australia",
             "date_posted": pd.Timestamp("2026-10-05"), "job_type": "parttime", "is_remote": False,
             "min_amount": float("nan"), "max_amount": float("nan"), "interval": None, "description": "Front desk."},
            {"id": "in-2", "site": "indeed", "job_url": "https://au.indeed.com/viewjob?jk=abc", "title": "Bookkeeper",
             "company": "Firm", "location": "Carlton, VIC", "date_posted": None, "job_type": None,
             "is_remote": True, "min_amount": 35.0, "max_amount": 40.0, "interval": "hourly", "currency": "AUD",
             "description": None},
            {"id": "go-3", "site": "google", "job_url": "https://example.com/j/3", "title": "Barista",
             "company": "Cafe", "location": "Seattle, WA, USA", "date_posted": None},
        ])

    ctx = make_ctx(FakeHttp({}), searches={"jobspy": {"searches": [{"term": "receptionist"}], "hours_old": 6,
                                                      "results_wanted": 50}})
    out = jobspy_src.collect(ctx, scrape=fake_scrape)
    assert [p.source_id for p in out] == ["linkedin:li-1", "indeed:in-2"]
    assert out[0].url == "https://www.linkedin.com/jobs/view/1" and out[0].work_type == "PT"
    assert out[1].salary_unit == "hour" and out[1].remote
    assert captured["country_indeed"] == "Australia" and captured["location"] == "Melbourne, VIC"
    assert captured["results_wanted"] == 25 and captured["hours_old"] == 6
    assert set(captured["site_name"]) == {"linkedin", "indeed", "google"}
    assert "proxies" not in captured


def test_jobspy_error_recorded():
    def boom(**kw):
        raise RuntimeError("blocked")
    ctx = make_ctx(FakeHttp({}), searches={"jobspy": {"searches": ["x"]}})
    assert jobspy_src.collect(ctx, scrape=boom) == [] and "blocked" in ctx.errors[0]


def test_limit_and_rotation():
    http = FakeHttp({"seek.com.au": fixture_json("seek_search.json")})
    ctx = make_ctx(http, searches={"seek": {"keywords": ["a", "b", "c"], "searches_per_run": 1}}, limit=1)
    assert len(seek.collect(ctx)) == 1
    seek.collect(ctx)
    kws = [c[2]["keywords"] for c in http.calls]
    assert kws == ["a", "b"]


def test_workday_remembers_non_au_details():
    http = FakeHttp({"/jobs": fixture_json("workday_jobs.json"),
                     "Customer-Service-Consultant": fixture_json("workday_detail_cs.json"),
                     "Analyst--Business-Analyst": fixture_json("workday_detail_vn.json"),
                     "Data-Entry-Operator": fixture_json("workday_detail_de.json")})
    ctx = make_ctx(http, [emp("workday", host="h.wd3.myworkdayjobs.com", tenant="t", site="s")])
    ats_workday.collect(ctx)
    ats_workday.collect(ctx)
    assert sum(1 for c in http.calls if "Analyst--Business" in c[1] and c[0] == "GET") == 1


def test_jobspy_site_errors_captured():
    import logging

    def fake(**kw):
        logging.getLogger("JobSpy:Google").error("Google response status code 429")
        return pd.DataFrame([])

    ctx = make_ctx(FakeHttp({}), searches={"jobspy": {"searches": ["x"]}})
    assert jobspy_src.collect(ctx, scrape=fake) == []
    assert ctx.errors and "429" in ctx.errors[0] and "Google" in ctx.errors[0]


def test_techone_jobs_without_an_apply_url_get_distinct_urls():
    from jobwatch.collectors import ats_techone
    data = {"DataSet": [{"JOBID": "11", "TITLE": "Rates Officer"}, {"JOBID": "12", "TITLE": "Payroll Officer"},
                        {"JOBID": "13", "TITLE": "Records Officer", "RESOLVEDAPPLYURL": "https://t1.example/apply?t=x"}]}
    out = ats_techone.parse_dataset(data, {"name": "Council", "careers_url": "https://council.example/careers"})
    assert len({p.url for p in out}) == 3 and out[2].url == "https://t1.example/apply?t=x"
    assert all(p.url.startswith("https://council.example/careers") for p in out[:2])


def test_malformed_xml_employer_does_not_kill_the_others():
    http = FakeHttp({"/527/": "<rss><channel><item>", "/528/": fixture_text("pageup.xml")})
    ctx = make_ctx(http, [emp("pageup", name="Broken", tenant="527"), emp("pageup", name="Fine", tenant="528")])
    out = ats_pageup.collect(ctx)
    assert len(out) == 2 and {p.origin for p in out} == {"Fine"}
    assert ctx.errors and "Broken" in ctx.errors[0] and "pageup:Broken" not in ctx.origins


def test_rss_malformed_pageup_feed_does_not_kill_the_collector():
    feeds = {"feeds": [{"name": "Bad", "url": "https://bad.example/rss", "format": "pageup", "company": "B"},
                       {"name": "Example", "url": "https://jobs.example.org.au/rss", "company": "Example Org"}]}
    ctx = make_ctx(FakeHttp({"bad.example": "<rss><item>", "jobs.example.org.au": fixture_text("rss_generic.xml")}),
                   feeds=feeds)
    out = rss.collect(ctx)
    assert len(out) == 2 and {p.origin for p in out} == {"Example"} and "Bad" in ctx.errors[0]


def test_successfactors_parse_failure_does_not_keep_validators(monkeypatch):
    from jobwatch.collectors import ats_successfactors as sf
    key = "http_cache:https://c.example.com/googlefeed.xml"
    ctx = make_ctx(FakeHttp({"/googlefeed.xml": "<rss>"}, headers={"ETag": "abc"}),
                   [emp("successfactors", host="c.example.com")])
    monkeypatch.setattr(sf, "parse_successfactors", lambda *a, **k: (_ for _ in ()).throw(AttributeError("bad")))
    assert sf.collect(ctx) == [] and ctx.errors
    assert not ctx.state_get(key, None)
