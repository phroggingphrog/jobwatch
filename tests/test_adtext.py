"""Full-ad fetchers (adtext.py): parsers on trimmed real pages, the safety checks, and ensure_text.

The network is never touched: `adtext._do_get` is replaced by a router (`Net`) that answers from the fixtures in
tests/fixtures/adtext/ and fails the test on any URL it was not told about.
"""
import gzip
import http.server
import json
import socketserver
import threading
import time
from pathlib import Path

import pytest

from jobwatch.util import adtext as adtext
from jobwatch import db as dbm
from jobwatch.dedupe import ingest
from jobwatch.models import Posting, html_to_text

FIX = Path(__file__).parent / "fixtures" / "adtext"


def fx(name: str) -> str:
    return (FIX / name).read_text()


# ---------------------------------------------------------------------------------------------- test doubles
class Net:
    """Stands in for adtext._do_get. routes: url -> (status, body) or (status, body, location)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, browser, timeout):
        self.calls.append((url, browser))
        if url not in self.routes:
            raise AssertionError(f"unexpected fetch of {url}")
        status, body, *loc = self.routes[url]
        return adtext._Resp(status, url, body, loc[0] if loc else "")


@pytest.fixture
def net(monkeypatch):
    def install(routes):
        n = Net(routes)
        monkeypatch.setattr(adtext, "_do_get", n)
        return n
    return install


@pytest.fixture
def no_net(monkeypatch):
    def boom(url, browser, timeout):
        raise AssertionError(f"no request expected, got {url}")
    monkeypatch.setattr(adtext, "_do_get", boom)


# One valid posting per fetchable source: how the collectors store it, and the exact URL we expect to be requested.
CASES = {
    "ats_smartrecruiters": dict(
        source_id="ALDIStores:744000145456148", url="https://jobs.smartrecruiters.com/ALDIStores/744000145456148",
        title="Junior Store Assistant - Mooroopna", raw={"id": "744000145456148"}, body="smartrecruiters_aldi.json",
        fetch="https://api.smartrecruiters.com/v1/companies/ALDIStores/postings/744000145456148", browser=False,
        label="smartrecruiters_api", marker="kick start your retail career"),
    "jobspy_src": dict(
        source_id="linkedin:li-4421792532", url="https://www.linkedin.com/jobs/view/4421792532",
        title="Sales Associate - Chadstone", raw={"id": "li-4421792532", "site": "linkedin"},
        body="linkedin_job.html", fetch="https://www.linkedin.com/jobs/view/4421792532", browser=True,
        label="linkedin_detail", marker="Montblanc"),
    "jora": dict(
        source_id="0b7a444acabdb2fd21631046932b38a3",
        url="https://au.jora.com/job/Ward-Clerk-0b7a444acabdb2fd21631046932b38a3", title="Ward Clerk",
        raw={"href": "/job/Ward-Clerk-0b7a444acabdb2fd21631046932b38a3?abstract_type=extended&sp=serp"},
        body="jora_job.html", fetch="https://au.jora.com/job/Ward-Clerk-0b7a444acabdb2fd21631046932b38a3",
        browser=True, label="jora_detail", marker="Intensive Care Unit"),
    "careers_vic": dict(
        source_id="89385", url="https://www.careers.vic.gov.au/job/fleet-support-officer-89385",
        title="Fleet Support Officer", raw={"id": "89385"}, body="careers_vic_job.html",
        fetch="https://www.careers.vic.gov.au/job/fleet-support-officer-89385", browser=True,
        label="careers_vic_detail", marker="fleet tasks"),
    "ats_oracle": dict(
        source_id="egvc.fa.ap1.oraclecloud.com:CX:5463",
        url="https://egvc.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/5463",
        title="Accountant", raw={"Id": "5463"}, body="oracle_details.json",
        fetch=("https://egvc.fa.ap1.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
               "?expand=all&onlyData=true&finder=ById%3BId%3D%225463%22%2CsiteNumber%3DCX"),
        browser=False, label="oracle_api", marker="Business Advisory team"),
    "ats_phenom": dict(
        source_id="Coles Group:194957",
        url="https://colescareers.com.au/au/en/job/194957/Team-Member-Coles-Rosebud-Dairy",
        title="Team Member - Coles Rosebud - Dairy", raw={"jobId": "194957"}, body="phenom_job.html",
        fetch="https://colescareers.com.au/au/en/job/194957/Team-Member-Coles-Rosebud-Dairy", browser=True,
        label="phenom_jsonld", marker="teamwork"),
    "ats_workday": dict(
        source_id="hungryjacks:JR103567",
        url="https://hungryjacks.wd105.myworkdayjobs.com/HungryJacksCareers/job/Ocean-Grove-Ocean-Grove-VIC/Casual-Crew-Member_JR103567",
        title="Casual Crew Member", raw={}, body="workday_job.html",
        fetch="https://hungryjacks.wd105.myworkdayjobs.com/HungryJacksCareers/job/Ocean-Grove-Ocean-Grove-VIC/Casual-Crew-Member_JR103567",
        browser=True, label="workday_jsonld", marker="Hungry Jack"),
    "ats_jobs_search": dict(
        source_id="careers.kingston.vic.gov.au:client-services-officer-mentone-vic-australia-6c55936d-4e27-439f-89c6-025e6554f2c0",
        url="https://careers.kingston.vic.gov.au/jobs/client-services-officer-mentone-vic-australia-6c55936d-4e27-439f-89c6-025e6554f2c0",
        title="Client Services Officer", raw={"slug": "x"}, body="jobs_search_job.html",
        fetch="https://careers.kingston.vic.gov.au/jobs/client-services-officer-mentone-vic-australia-6c55936d-4e27-439f-89c6-025e6554f2c0",
        browser=True, label="jobs_search_jsonld", marker="Roster home support"),
    "ats_successfactors": dict(
        source_id="careers.example.com:1365442866",
        url="https://careers.example.com/job/Bentleigh-Banking-Consultant%2C-Bentleigh-VIC/1368164566",
        title="Banking Consultant", raw={}, body="successfactors_job.html",
        fetch="https://careers.example.com/job/Bentleigh-Banking-Consultant%2C-Bentleigh-VIC/1368164566",
        browser=True, label="successfactors_detail", marker="Australian citizenship or permanent residency"),
    "ats_pageup": dict(
        source_id="541:719275",
        url="https://careers.pageuppeople.com/541/cw/en/job/719275/event-workforce-check-in-team-roles",
        title="Event Workforce, Check In Team Roles", raw={"refNo": "719275"}, body="pageup_job.html",
        fetch="https://careers.pageuppeople.com/541/cw/en/job/719275/event-workforce-check-in-team-roles",
        browser=True, label="pageup_detail", marker="check-in areas"),
    "ats_pulse": dict(
        source_id="banyule:xINhUW", url="https://banyule.pulsesoftware.com/Pulse/apply/xINhUW/Senior-Procurement-Coordinator?source=public",
        title="Senior Procurement Coordinator", raw={"Title": "Senior Procurement Coordinator"},
        body="../councils_pulse.json", fetch=adtext.PULSE_API.format(tenant="banyule"), browser=False,
        label="pulse_api", marker="Banyule City Council is seeking"),
}
SOURCES = list(CASES)


def ref_for(source: str, **over) -> adtext.Ref:
    c = {**CASES[source], **over}
    return adtext.Ref(source, c["source_id"], c["url"], c["title"], c["raw"])


def routes_for(source: str, **over) -> dict:
    c = {**CASES[source], **over}
    return {c["fetch"]: (200, fx(c["body"]))}


# ---------------------------------------------------------------------------------------------- the database
@pytest.fixture
def world(tmp_path):
    conn = dbm.connect(tmp_path / "t.db")

    def add(source, source_id, url, title, desc="", raw=None):
        pid, _ = ingest(conn, Posting(source=source, source_id=source_id, url=url, title=title, company="Acme",
                                      location="Melbourne VIC", description=desc, raw=raw or {}))
        conn.commit()
        return pid

    def row(pid):
        # the columns reader.py's _BASE_SQL selects today: no p.url
        return conn.execute("SELECT p.id, p.source, p.source_id, p.title, p.company, p.location, p.work_type, "
                            "p.salary_text, p.description, p.raw_json FROM postings p WHERE p.id=?", (pid,)).fetchone()

    def add_case(source, desc="", **over):
        c = {**CASES[source], **over}
        return add(source, c["source_id"], c["url"], c["title"], desc, c["raw"])

    return conn, add, row, add_case


# ---------------------------------------------------------------------------------------------- parsers
def test_inner_html_balances_nested_divs_and_skips_scripts():
    page = ("<script>var t = '<div class=\"x\">decoy</div>';</script>"
            '<div class="a x b"><div>one</div><p>two</p><div><div>three</div></div></div><div>after</div>')
    import re
    inner = adtext._inner_html(page, re.compile(r'<div[^>]*class="[^"]*\bx\b[^"]*"[^>]*>'))
    assert inner == "<div>one</div><p>two</p><div><div>three</div></div>"
    assert adtext._inner_html("<div>none</div>", re.compile(r'<div id="zzz">')) == ""
    cut_off = adtext._inner_html('<div class="x"><p>half a page', re.compile(r'<div class="x">'))
    assert cut_off == "<p>half a page"


def test_smartrecruiters_sections_job_description_first_company_last():
    html, api_id, name = adtext.parse_smartrecruiters(fx("smartrecruiters_aldi.json"))
    text = html_to_text(html, limit=adtext.MAX_TEXT)
    assert api_id == "744000145456148" and name.startswith("Junior Store Assistant")
    assert text.index("Job Description") < text.index("Qualifications") < text.index("Additional Information")
    assert "weekends, after school hours" in text and "<" not in text
    assert adtext.parse_smartrecruiters("not json") == ("", "", "")
    assert adtext.parse_smartrecruiters('{"jobAd": {"sections": {}}}')[0] == ""


def test_linkedin_parser_reads_the_markup_div_only():
    page = fx("linkedin_job.html")
    text = html_to_text(adtext.parse_linkedin_page(page), limit=adtext.MAX_TEXT)
    assert text.startswith("About The Role") and "Montblanc" in text
    assert "decoy" not in text and "Similar jobs" not in text and "Show more" not in text
    assert "Achieving sales targets" in text.split("\n")                 # bullets stay one per line
    assert adtext.parse_linkedin_page(fx("linkedin_authwall.html")) == ""


def test_jora_parser_reads_the_description_container():
    text = html_to_text(adtext.parse_jora_page(fx("jora_job.html")), limit=adtext.MAX_TEXT)
    assert text.startswith("Job no: 79739") and "Intensive Care Unit" in text
    assert "decoy" not in text and "Apply" not in text and "Jora" not in text
    assert adtext.parse_jora_page(fx("jora_challenge.html")) == ""


def test_careers_vic_parser_reads_the_description_field():
    text = html_to_text(adtext.parse_careers_vic_page(fx("careers_vic_job.html")), limit=adtext.MAX_TEXT)
    assert text.startswith("The Fleet Support Officer is responsible") and "WHO WE ARE:" in text
    assert "Menu" not in text and "Careers Vic" not in text and "Apply now" not in text


def test_oracle_parser_joins_fields_and_handles_empty_answers():
    html, rid, title = adtext.parse_oracle(fx("oracle_details.json"))
    text = html_to_text(html, limit=adtext.MAX_TEXT)
    assert (rid, title) == ("5463", "Accountant") and "Business Advisory team" in text
    assert adtext.parse_oracle(fx("oracle_empty.json")) == ("", "", "")
    assert adtext.parse_oracle("<html>") == ("", "", "")
    synthetic = json.dumps({"items": [{"Id": "9", "Title": "T", "ExternalDescriptionStr": "<p>About the role</p>",
                                       "ExternalQualificationsStr": "<ul><li>Australian citizens only</li></ul>",
                                       "ShortDescriptionStr": "teaser"}]})
    text = html_to_text(adtext.parse_oracle(synthetic)[0], limit=adtext.MAX_TEXT)
    assert text.index("About the role") < text.index("Qualifications") < text.index("Australian citizens only")
    assert "teaser" not in text                                          # the short blurb only when nothing else
    only_short = json.dumps({"items": [{"Id": "9", "ShortDescriptionStr": "just the teaser"}]})
    assert adtext.parse_oracle(only_short)[0] == "just the teaser"


def test_jsonld_parser_handles_escaped_html_plain_text_and_graphs():
    title, desc = adtext.parse_jsonld_job(fx("phenom_job.html"))          # Phenom: HTML escaped once, 3 ld blocks
    text = html_to_text(desc, limit=adtext.MAX_TEXT)
    assert title == "Team Member - Coles Rosebud - Dairy" and "teamwork" in text
    assert "&lt;" not in text and "<p>" not in text and "\n" in text
    title, desc = adtext.parse_jsonld_job(fx("workday_job.html"))         # Workday: plain text
    assert title == "Casual Crew Member" and "Hungry Jack" in html_to_text(desc, limit=adtext.MAX_TEXT)
    title, desc = adtext.parse_jsonld_job(fx("jobs_search_job.html"))     # HTML, one bullet per <li>
    assert "Roster home support services for clients" in html_to_text(desc, limit=adtext.MAX_TEXT).split("\n")

    def page(payload):
        return f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    graph = {"@graph": [{"@type": "WebPage"}, {"@type": ["Thing", "JobPosting"], "title": "T", "description": "d"}]}
    assert adtext.parse_jsonld_job(page(graph)) == ("T", "d")
    assert adtext.parse_jsonld_job(page([{"@type": "JobPosting", "title": "L", "description": "in a list"}])) == ("L", "in a list")
    assert adtext.parse_jsonld_job(page({"@type": "JobPosting", "title": "T"})) == ("", "")      # no description
    assert adtext.parse_jsonld_job(page({"@type": "Organization", "description": "x"})) == ("", "")
    assert adtext.parse_jsonld_job('<script type="application/ld+json">{broken</script>') == ("", "")
    assert adtext.parse_jsonld_job("<html>nothing</html>") == ("", "")


# ---------------------------------------------------------------------------------------------- URL safety
@pytest.mark.parametrize("url,ok", [
    ("https://api.smartrecruiters.com/v1/x", True),
    ("https://smartrecruiters.com/x", True),
    ("http://api.smartrecruiters.com/v1/x", False),                       # not https
    ("https://evilsmartrecruiters.com/x", False),                         # look-alike suffix
    ("https://smartrecruiters.com.evil.io/x", False),
    ("https://user:pw@api.smartrecruiters.com/x", False),                 # credentials
    ("https://api.smartrecruiters.com:8443/x", False),                    # odd port
    ("https://api.smartrecruiters.com:443/x", True),
    ("https://127.0.0.1/x", False),
    ("ftp://api.smartrecruiters.com/x", False),
    ("", False),
    ("https:///nohost", False),
])
def test_host_ok(url, ok):
    assert adtext._host_ok(url, ("smartrecruiters.com",)) is ok


def test_host_ok_refuses_ip_and_local_names_even_when_allowed():
    for host in ("127.0.0.1", "10.0.0.5", "localhost", "intranet", "printer.local"):
        assert not adtext._host_ok(f"https://{host}/x", (host,))


def test_redirect_is_followed_by_hand_and_stays_on_site(net):
    n = net({"https://au.jora.com/job/a-1": (301, "", "/job/a-2"),
             "https://au.jora.com/job/a-2": (200, "ok body")})
    assert adtext._http_get("https://au.jora.com/job/a-1", ("jora.com",), name="jora") == ("https://au.jora.com/job/a-2", "ok body")
    assert [u for u, _ in n.calls] == ["https://au.jora.com/job/a-1", "https://au.jora.com/job/a-2"]


def test_redirect_to_another_site_is_never_requested(net):
    n = net({"https://au.jora.com/job/a-1": (302, "", "https://evil.example.org/steal")})
    assert adtext._http_get("https://au.jora.com/job/a-1", ("jora.com",), name="jora") is None
    assert [u for u, _ in n.calls] == ["https://au.jora.com/job/a-1"]
    n = net({"https://au.jora.com/job/a-1": (302, "", "http://au.jora.com/job/a-1")})      # downgrade to http
    assert adtext._http_get("https://au.jora.com/job/a-1", ("jora.com",), name="jora") is None


def test_redirect_loop_gives_up(net):
    n = net({"https://au.jora.com/job/a": (302, "", "/job/b"), "https://au.jora.com/job/b": (302, "", "/job/a")})
    assert adtext._http_get("https://au.jora.com/job/a", ("jora.com",), name="jora") is None
    assert len(n.calls) == adtext.MAX_HOPS + 1


# ---------------------------------------------------------------------------------------------- fetch per source
@pytest.mark.parametrize("source", SOURCES)
def test_each_source_fetches_one_url_and_returns_the_ad(source, net):
    n = net(routes_for(source))
    text = adtext._FETCHERS[source].run(ref_for(source))
    assert CASES[source]["marker"] in text and len(text) >= adtext.MIN_BODY
    assert n.calls == [(CASES[source]["fetch"], CASES[source]["browser"])]
    assert "<" not in text and "&lt;" not in text and "<script" not in text


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_blocked_statuses_raise_blocked(source, status, net):
    net({CASES[source]["fetch"]: (status, "denied")})
    with pytest.raises(adtext.Blocked, match=str(status)):
        adtext._FETCHERS[source].run(ref_for(source))


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("status", [404, 410])
def test_gone_ad_returns_empty(source, status, net):
    net({CASES[source]["fetch"]: (status, "<html>not found</html>")})
    assert adtext._FETCHERS[source].run(ref_for(source)) == ""


@pytest.mark.parametrize("source,body", [
    ("jobspy_src", "linkedin_authwall.html"),
    ("jora", "jora_challenge.html"),
    ("careers_vic", "jora_challenge.html"),
    ("ats_phenom", "jora_challenge.html"),
    ("ats_workday", "linkedin_authwall.html"),
    ("ats_smartrecruiters", "jora_challenge.html"),                      # HTML where JSON was expected
    ("ats_successfactors", "jora_challenge.html"),
    ("ats_successfactors", "successfactors_filled.html"),                # "this position has been filled", 200
    ("ats_pageup", "jora_challenge.html"),
    ("ats_pulse", "oracle_empty.json"),                                  # JSON without this job
    ("ats_oracle", "oracle_empty.json"),                                 # requisition gone: empty items
])
def test_challenge_login_and_empty_pages_return_empty(source, body, net):
    net({CASES[source]["fetch"]: (200, fx(body))})
    assert adtext._FETCHERS[source].run(ref_for(source)) == ""


def test_redirect_off_site_returns_empty_for_every_source(net):
    for source in SOURCES:
        n = net({CASES[source]["fetch"]: (302, "", "https://evil.example.org/x")})
        assert adtext._FETCHERS[source].run(ref_for(source)) == ""
        assert len(n.calls) == 1


# --- wrong destination: nothing is requested -------------------------------------------------------------------
@pytest.mark.parametrize("source,url", [
    ("jora", "https://example.com/job/Ward-Clerk-0b7a444acabdb2fd21631046932b38a3"),
    ("jora", "http://au.jora.com/job/Ward-Clerk-0b7a444acabdb2fd21631046932b38a3"),
    ("jora", "https://au.jora.com.evil.io/job/Ward-Clerk-0b7a444acabdb2fd21631046932b38a3"),
    ("jora", "https://au.jora.com/search?q=clerk"),                      # not a /job/<slug> path
    ("careers_vic", "https://careers.vic.gov.au.evil.io/job/fleet-support-officer-89385"),
    ("careers_vic", "https://www.careers.vic.gov.au/jobs?page=2"),
    ("jobspy_src", "https://www.indeed.com/viewjob?jk=030a8e26460146a4"),
    ("ats_phenom", "http://colescareers.com.au/au/en/job/194957/x"),     # http, not https
    ("ats_phenom", "https://127.0.0.1/job/194957"),
    ("ats_workday", "https://localhost/job/JR103567"),
    ("ats_workday", ""),
    ("ats_successfactors", "https://evil.example.org/job/x/1368164566"),     # not the registry host in source_id
    ("ats_successfactors", "https://careers.example.com/search?q=clerk"),    # not a /job/<slug>/<id> path
    ("ats_pageup", "https://careers.pageuppeople.com.evil.io/541/cw/en/job/719275"),
    ("ats_pageup", "https://careers.pageuppeople.com/541/cw/en/listing/"),
    ("ats_jobs_search", "https://careers.kingston.vic.gov.au\\@evil.example.org/jobs/x"),   # backslash
])
def test_wrong_host_or_shape_is_refused_without_a_request(source, url, no_net):
    over = {"url": url}
    if source == "jobspy_src":                                           # no raw site either: only the url could say
        over["raw"] = {}
        over["source_id"] = "x:y"
    assert adtext._FETCHERS[source].run(ref_for(source, **over)) == ""


@pytest.mark.parametrize("source_id", ["", "nocolon", "evil.example.com:CX:5463", "egvc.fa.ap1.oraclecloud.com:CX:abc",
                                       "egvc.fa.ap1.oraclecloud.com.evil.io:CX:5463", "egvc.fa.ap1.oraclecloud.com:C/X:5463"])
def test_oracle_source_id_must_name_an_oraclecloud_host(source_id, no_net):
    assert adtext.fetch_oracle(ref_for("ats_oracle", source_id=source_id)) == ""


@pytest.mark.parametrize("source_id", ["", "../..:1", "a b:1", "ALDI:1/../x", "ALDI:"])
def test_smartrecruiters_source_id_is_validated(source_id, no_net):
    assert adtext.fetch_smartrecruiters(ref_for("ats_smartrecruiters", source_id=source_id)) == ""


# --- LinkedIn vs Indeed: raw_json decides, not the source name ------------------------------------------------
def test_indeed_rows_are_never_fetched(no_net):
    raw = {"id": "in-030a8e26460146a4", "site": "indeed", "job_url": "https://au.indeed.com/viewjob?jk=030a8e26460146a4"}
    ref = adtext.Ref("jobspy_src", "indeed:in-030a8e26460146a4", "https://au.indeed.com/viewjob?jk=030a8e26460146a4",
                     "Accounts Payable Officer", raw)
    assert adtext.linkedin_id(ref) is None and adtext.fetch_linkedin(ref) == ""


def test_linkedin_id_comes_from_raw_then_source_id_then_url():
    assert adtext.linkedin_id(ref_for("jobspy_src")) == "4421792532"
    only_sid = adtext.Ref("jobspy_src", "linkedin:li-4421792532", "", "t", {})
    assert adtext.linkedin_id(only_sid) == "4421792532"
    only_url = adtext.Ref("jobspy_src", "x", "https://www.linkedin.com/jobs/view/sales-associate-at-acme-4421792532", "t", {})
    assert adtext.linkedin_id(only_url) == "4421792532"
    assert adtext.linkedin_id(adtext.Ref("jobspy_src", "x", "https://example.com/jobs/view/4421792532", "t", {})) is None
    assert adtext.linkedin_id(adtext.Ref("jobspy_src", "zip:1", "", "t", {"site": "zip_recruiter", "id": "li-4421792532"})) is None


def test_linkedin_requests_the_clean_url_not_the_stored_one(net):
    n = net({"https://www.linkedin.com/jobs/view/4421792532": (200, fx("linkedin_job.html"))})
    ref = ref_for("jobspy_src", url="https://www.linkedin.com/jobs/view/4421792532?trackingId=abc&refId=def")
    assert "Montblanc" in adtext.fetch_linkedin(ref)
    assert n.calls == [("https://www.linkedin.com/jobs/view/4421792532", True)]


def test_jora_requests_the_path_without_the_search_tracking_query(net):
    n = net({CASES["jora"]["fetch"]: (200, fx("jora_job.html"))})
    ref = ref_for("jora", url=CASES["jora"]["url"] + "?abstract_type=extended&sol_key=abc&sp=serp")
    assert "Intensive Care Unit" in adtext.fetch_jora(ref)
    assert n.calls == [(CASES["jora"]["fetch"], True)]


# --- the page must be THIS ad -------------------------------------------------------------------------------
def test_identity_id_in_final_url_or_a_title_word():
    body = "A real advertisement for a role. " * 20
    ok = adtext._is_this_ad
    assert ok("Totally Different", body, ref_id="12345", id_in="https://x.org/job/12345")
    assert ok("Totally Different", body, ref_id="12345", id_in="https://x.org/job/x_12345?src=1")
    assert not ok("Totally Different", body, ref_id="12345", id_in="https://x.org/job/123456")          # not a whole token
    assert not ok("Totally Different", body, ref_id="12345", id_in="https://x.org/job/a12345")
    assert not ok("Totally Different", body, ref_id="", id_in="")
    assert ok("Senior Advertisement Officer", body, ref_id="999", id_in="https://x.org/other")       # title word in text
    assert ok("Quantum Physicist", body, ref_id="999", id_in="https://x.org/other", page_title="Quantum Physicist | Acme")
    assert not ok("HR", body, ref_id="999", id_in="https://x.org/other")          # no significant word and no id
    assert not ok("Quantum Physicist", "Short ad. " * 5, ref_id="12345", id_in="https://x.org/job/12345")  # < MIN_BODY


def test_page_for_another_job_is_rejected(net):
    # the page exists, has a long ad, but it is not this posting: the url carries no id and the title words differ
    case = CASES["ats_workday"]
    url = "https://hungryjacks.wd105.myworkdayjobs.com/HungryJacksCareers/job/x/Other-Role"
    n = net({url: (200, fx("workday_job.html"))})
    assert adtext.fetch_jsonld(ref_for("ats_workday", url=url, source_id="hungryjacks:JR999999", title="Quantum Physicist")) == ""
    assert adtext.fetch_jsonld(ref_for("ats_workday", url=url, source_id="hungryjacks:JR999999", title="Casual Crew Member"))
    assert len(n.calls) == 2 and case["browser"]


def test_short_body_is_rejected(net):
    short = ('<script type="application/ld+json">{"@type": "JobPosting", "title": "Casual Crew Member", '
             '"description": "Apply now for this casual crew member role."}</script>')
    net({CASES["ats_workday"]["fetch"]: (200, short)})
    assert adtext.fetch_jsonld(ref_for("ats_workday")) == ""


def test_text_is_capped(net):
    big = '<script type="application/ld+json">' + json.dumps(
        {"@type": "JobPosting", "title": "Casual Crew Member", "description": "<p>crew member duties</p>" * 5000}) + "</script>"
    net({CASES["ats_workday"]["fetch"]: (200, big)})
    assert len(adtext.fetch_jsonld(ref_for("ats_workday"))) == adtext.MAX_TEXT


# ---------------------------------------------------------------------------------------------- ensure_text
@pytest.mark.parametrize("source", SOURCES)
def test_ensure_text_fetches_saves_and_returns_full(source, world, net):
    conn, add, row, add_case = world
    pid = add_case(source, desc="a short teaser")
    n = net(routes_for(source))
    text, kind = adtext.ensure_text(conn, row(pid))                        # the row has no p.url: read from the db
    assert kind == "full" and CASES[source]["marker"] in text
    assert adtext.get_text(conn, pid) == (text, CASES[source]["label"])
    assert len(n.calls) == 1
    again = adtext.ensure_text(conn, row(pid))                             # second time: ad_text first, no request
    assert again == (text, "full") and len(n.calls) == 1


def test_ensure_text_order_ad_text_then_long_description_then_fetch(world, no_net):
    conn, add, row, add_case = world
    saved = add_case("jora", desc="teaser")
    adtext.save_text(conn, saved, "Already fetched ad. " * 30, "jora_detail")
    assert adtext.ensure_text(conn, row(saved)) == ("Already fetched ad. " * 30, "full")
    long_desc = "The whole ad is in the feed. " * 40
    feed = add("ats_smartrecruiters", "T:1", "https://jobs.smartrecruiters.com/T/1", "Accounts Clerk", long_desc)
    assert adtext.ensure_text(conn, row(feed)) == (long_desc.strip(), "full")
    assert adtext.get_text(conn, feed) is None                             # nothing saved for a feed description


def test_teaser_only_source_stays_teaser(world, no_net):
    conn, add, row, add_case = world
    for source in ("ats_techone", "ats_elmo", "rss", "ats_scouttalent", "reddit", "ats_lever"):
        pid = add(source, f"{source}-1", "https://careers.example.com/job/1", "Accounts Clerk", "just a teaser")
        assert adtext.fetch_host(source) is None
        assert adtext.ensure_text(conn, row(pid)) == ("just a teaser", "teaser")
        assert adtext.get_text(conn, pid) is None


def test_allow_fetch_false_never_requests(world, no_net):
    conn, add, row, add_case = world
    pid = add_case("ats_smartrecruiters", desc="teaser")
    assert adtext.ensure_text(conn, row(pid), allow_fetch=False) == ("teaser", "teaser")


def test_ensure_text_wrong_host_url_gives_teaser_and_no_request(world, no_net):
    conn, add, row, add_case = world
    pid = add("jora", "abc", "https://example.com/job/Ward-Clerk-abc", "Ward Clerk", "teaser")
    assert adtext.ensure_text(conn, row(pid)) == ("teaser", "teaser")
    assert adtext.get_text(conn, pid) is None


@pytest.mark.parametrize("status", [404, 410])
def test_ensure_text_gone_ad_is_not_saved(status, world, net):
    conn, add, row, add_case = world
    pid = add_case("careers_vic", desc="teaser")
    net({CASES["careers_vic"]["fetch"]: (status, "not found")})
    assert adtext.ensure_text(conn, row(pid)) == ("teaser", "teaser")
    assert adtext.get_text(conn, pid) is None


@pytest.mark.parametrize("status", [403, 429, 502])
def test_ensure_text_raises_blocked_and_saves_nothing(status, world, net):
    conn, add, row, add_case = world
    pid = add_case("jobspy_src", desc="teaser")
    net({CASES["jobspy_src"]["fetch"]: (status, "no")})
    with pytest.raises(adtext.Blocked):
        adtext.ensure_text(conn, row(pid))
    assert adtext.get_text(conn, pid) is None


def test_a_blocked_ad_falls_back_to_tinyfish_at_the_stored_url(world, net, monkeypatch):
    """reader._BASE_SQL does not select p.url: the fallback must take the address from the database, not the row."""
    conn, add, row, add_case = world
    pid = add_case("jobspy_src", desc="teaser")
    net({CASES["jobspy_src"]["fetch"]: (403, "no")})
    long_text, asked = "Warehouse clerk duties and shift times. " * 60, []
    monkeypatch.setattr(adtext, "_tinyfish_key", lambda: "synthetic-key")
    monkeypatch.setattr(adtext, "tinyfish_text", lambda url, **kw: asked.append(url) or long_text)
    assert adtext.ensure_text(conn, row(pid)) == (long_text[:adtext.MAX_TEXT], "full")
    assert asked == [CASES["jobspy_src"]["url"]]
    assert adtext.get_text(conn, pid)[0] == long_text[:adtext.MAX_TEXT]

def test_ensure_text_challenge_page_is_not_saved(world, net):
    conn, add, row, add_case = world
    pid = add_case("jora", desc="teaser")
    net({CASES["jora"]["fetch"]: (200, fx("jora_challenge.html"))})
    assert adtext.ensure_text(conn, row(pid)) == ("teaser", "teaser")
    assert adtext.get_text(conn, pid) is None


def test_fetcher_double_is_called_with_source_id_for_every_fetchable_source(world, no_net):
    conn, add, row, add_case = world
    seen = []

    def double(source_id):
        seen.append(source_id)
        return "Test double ad body. " * 20

    for source in SOURCES:
        pid = add_case(source, desc="teaser")
        assert adtext.ensure_text(conn, row(pid), double) == ("Test double ad body. " * 20, "full")
        assert adtext.get_text(conn, pid)[1] == CASES[source]["label"]
    assert seen == [CASES[s]["source_id"] for s in SOURCES]
    pid = add("ats_techone", "p-1", "https://careers.example.com/1", "Accounts Clerk", "teaser")
    assert adtext.ensure_text(conn, row(pid), double) == ("teaser", "teaser") and len(seen) == len(SOURCES)


def test_seek_keeps_its_label_and_double_convention(world):
    conn, add, row, add_case = world
    pid = add("seek", "95082933", "https://www.seek.com.au/job/95082933", "Bookkeeper", "teaser")
    assert adtext.ensure_text(conn, row(pid), lambda sid: "Seek ad body. " * 30) == ("Seek ad body. " * 30, "full")
    assert adtext.get_text(conn, pid)[1] == "seek_detail"


def test_double_returning_nothing_or_less_than_the_teaser_is_not_saved(world):
    conn, add, row, add_case = world
    pid = add_case("ats_smartrecruiters", desc="a teaser that is a little longer")
    assert adtext.ensure_text(conn, row(pid), lambda sid: "") == ("a teaser that is a little longer", "teaser")
    assert adtext.ensure_text(conn, row(pid), lambda sid: "tiny") == ("a teaser that is a little longer", "teaser")
    assert adtext.get_text(conn, pid) is None


def test_ensure_text_accepts_rows_that_already_carry_url_and_raw_json(world, net):
    conn, add, row, add_case = world
    pid = add_case("jobspy_src", desc="teaser")
    n = net(routes_for("jobspy_src"))
    full = conn.execute("SELECT * FROM postings WHERE id=?", (pid,)).fetchone()
    assert "url" in full.keys() and "raw_json" in full.keys()
    assert adtext.ensure_text(conn, full)[1] == "full" and len(n.calls) == 1
    sr = add_case("ats_smartrecruiters", desc="teaser")                    # a plain dict works too, db is not asked
    as_dict = {"id": sr, "source": "ats_smartrecruiters", "source_id": CASES["ats_smartrecruiters"]["source_id"],
               "title": CASES["ats_smartrecruiters"]["title"], "description": "", "url": CASES["ats_smartrecruiters"]["url"],
               "raw_json": "{}"}
    n = net(routes_for("ats_smartrecruiters"))
    assert adtext.ensure_text(conn, as_dict)[1] == "full" and len(n.calls) == 1


def test_fetch_host_keys():
    keys = {s: adtext.fetch_host(s) for s in SOURCES + ["seek", "jsonld_pages"]}
    assert all(keys.values())
    assert adtext.fetch_host("seek") == "seek.com.au"
    assert keys["ats_smartrecruiters"] != keys["jora"] != keys["jobspy_src"]
    assert adtext.fetch_host("ats_techone") is None and adtext.fetch_host("nope") is None


# ---------------------------------------------------------------------------------------------- URL parser differential
@pytest.mark.parametrize("url", [
    "https://evil.com\\.smartrecruiters.com/x",                           # urlsplit and urllib3 read different hosts
    "https://api.smartrecruiters.com\\@evil.com/x",
    "https://api.smartrecruiters.com/x\\y",
    "https://api.smartrecruiters.com/x y",
    "https://api.smartrecruiters.com/x\ty",
    "https://api.smartrecruiters.com/x\n",
    "https://api.smartrecruiters.com/\x00",
    "https://api.smartrecruiters.com%2f.evil.com/x",
    "https://api%2esmartrecruiters.com/x",
    "https://api.smartrecruiters.com@evil.com/x",
    "https://@api.smartrecruiters.com/x",
    "https://api.smartrecruiters.com:@evil.com/",
    " https://api.smartrecruiters.com/x",
])
def test_host_ok_refuses_backslash_control_whitespace_and_userinfo(url):
    assert adtext._host_ok(url, ("smartrecruiters.com",)) is False


def test_redirect_with_a_backslash_host_is_never_requested(net):
    n = net({"https://api.smartrecruiters.com/v1/a": (302, "", "https://probe.invalid\\.smartrecruiters.com/v1/x")})
    assert adtext._http_get("https://api.smartrecruiters.com/v1/a", ("smartrecruiters.com",), name="sr",
                            browser=False) is None
    assert [u for u, _ in n.calls] == ["https://api.smartrecruiters.com/v1/a"]


def test_fetch_jsonld_requests_only_the_stored_url_and_only_on_the_employers_hosts(net, no_net):
    # a jsonld_pages row whose url is off the employer's recorded hosts is not requested at all
    ref = adtext.Ref("jsonld_pages", "Emp:1", "https://127.0.0.1.nip.io/hook?x=1", "Payroll Officer",
                     {"_site_hosts": ["careers.example.com"]})
    assert adtext.fetch_jsonld(ref) == ""
    assert adtext.last_status() == "refused"
    ref = adtext.Ref("jsonld_pages", "Emp:1", "https://careers.example.com/jobs/1", "Payroll Officer",
                     {"_site_hosts": ["careers.example.com", "www.other.example.com"]})
    assert adtext._host_ok(ref.url, ("careers.example.com",))


def test_fetch_jsonld_on_the_recorded_host_never_follows_a_page_supplied_url(net):
    url = "https://careers.example.com/jobs/payroll-1"
    page = ('<script type="application/ld+json">' + json.dumps(
        {"@type": "JobPosting", "title": "Payroll Officer", "url": "https://evil.example.org/x",
         "description": "<p>Payroll officer duties. </p>" * 30}) + "</script>")
    n = net({url: (200, page)})
    ref = adtext.Ref("jsonld_pages", "Emp:1", url, "Payroll Officer", {"_site_hosts": ["careers.example.com"]})
    assert "Payroll officer duties" in adtext.fetch_jsonld(ref)
    assert [u for u, _ in n.calls] == [url]


# ---------------------------------------------------------------------------------------------- _do_get: size, time
_BOMB = gzip.compress(b"0" * (60 * 1024 * 1024))                             # ~60 KB on the wire, 60 MB decompressed


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _head(self, status=200, **headers):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.end_headers()

    def do_GET(self):
        try:
            path = self.path
            if path == "/ok":
                body = "<html>café ok</html>".encode()
                self._head(Content_Type="text/html; charset=utf-8", Content_Length=str(len(body)))
                self.wfile.write(body)
            elif path == "/gz":
                body = gzip.compress(b"<html>small gzip page</html>")
                self._head(Content_Encoding="gzip", Content_Type="text/html", Content_Length=str(len(body)))
                self.wfile.write(body)
            elif path == "/redir":
                self._head(302, Location="/ok", Content_Length="0")
            elif path == "/bomb":
                self._head(Content_Encoding="gzip", Content_Type="text/html", Content_Length=str(len(_BOMB)))
                self.wfile.write(_BOMB)
            elif path == "/big":
                self._head(Content_Type="text/html", Content_Length=str(8 * 1024 * 1024))
                for _ in range(8):
                    self.wfile.write(b"y" * 1024 * 1024)
            elif path == "/bigchunked":                                    # no Content-Length: counted while reading
                self._head(Content_Type="text/html")
                for _ in range(8):
                    self.wfile.write(b"y" * 1024 * 1024)
            elif path == "/image":
                self._head(Content_Type="image/png", Content_Length="3")
                self.wfile.write(b"abc")
            elif path == "/hdrdrip":                                       # status line, then header bytes one by one
                self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                for _ in range(40):
                    self.wfile.write(b"X")
                    self.wfile.flush()
                    time.sleep(0.2)
            elif path == "/drip":
                self._head(Content_Type="text/html")
                for _ in range(100):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def local():
    srv = _Server(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.parametrize("browser", [False, True])
def test_do_get_reads_a_normal_page_and_redirects_without_a_body(local, browser):
    r = adtext._do_get(local + "/ok", browser, 5)
    assert (r.status, r.text) == (200, "<html>café ok</html>")
    assert adtext._do_get(local + "/gz", browser, 5).text == "<html>small gzip page</html>"
    r = adtext._do_get(local + "/redir", browser, 5)
    assert r.status == 302 and r.location.endswith("/ok") and r.text == ""


@pytest.mark.parametrize("browser", [False, True])
@pytest.mark.parametrize("path", ["/bomb", "/big", "/bigchunked"])
def test_do_get_refuses_an_oversize_or_decompression_bomb_response(local, browser, path, monkeypatch):
    monkeypatch.setattr(adtext, "MAX_BODY", 1024 * 1024)
    t = time.monotonic()
    with pytest.raises(adtext.FetchError, match="too large"):
        adtext._do_get(local + path, browser, 10)
    assert time.monotonic() - t < 5


@pytest.mark.parametrize("browser", [False, True])
def test_do_get_gives_up_on_a_slow_drip_at_the_total_deadline(local, browser, monkeypatch):
    monkeypatch.setattr(adtext, "TOTAL_DEADLINE", 1.5)
    t = time.monotonic()
    with pytest.raises(Exception):                                         # FetchError, or curl's own total timeout
        adtext._do_get(local + "/drip", browser, 25)                       # the per-read timeout alone would wait
    assert time.monotonic() - t < 6


def test_do_get_bounds_a_header_phase_drip_on_the_requests_path(local, monkeypatch):
    monkeypatch.setattr(adtext, "TOTAL_DEADLINE", 1.5)
    t = time.monotonic()
    with pytest.raises(adtext.FetchError, match="too slow"):
        adtext._do_get(local + "/hdrdrip", False, 25)                      # each byte beats the per-read timeout
    assert time.monotonic() - t < 6


def test_requests_path_uses_a_connect_and_read_timeout_pair(local, monkeypatch):
    import requests
    seen = []
    real = requests.Session.get
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: seen.append(kw["timeout"]) or real(self, url, **kw))
    adtext._do_get(local + "/ok", False, 25)
    adtext._do_get(local + "/ok", False, 3)
    assert seen == [(5.0, 10.0), (3, 3)]


@pytest.mark.parametrize("browser", [False, True])
def test_do_get_refuses_a_non_text_body(local, browser):
    with pytest.raises(adtext.FetchError, match="not a text page"):
        adtext._do_get(local + "/image", browser, 5)


def test_default_caps_are_3mb_and_30s():
    assert adtext.MAX_BODY == 3 * 1024 * 1024 and adtext.TOTAL_DEADLINE == 30.0


# ---------------------------------------------------------------------------------------------- cut text (the 2000 cap)
def cut(n=2000, tail=""):
    """What a collector stores for a long ad: the first n characters."""
    return ("Process invoices and answer supplier queries. " * 60)[:n - len(tail)] + tail


def test_classify_full_partial_teaser():
    cls = adtext.classify
    assert cls("A fetched ad. " * 20, "teaser", "jora") == ("A fetched ad. " * 20, "full")
    assert cls(None, "short teaser", "jora") == ("short teaser", "teaser")
    assert cls(None, "", "jora") == ("", "teaser")
    assert cls(None, cut(800), "jora")[1] == "full"
    assert cls(None, cut(adtext.COLLECTOR_CAP - 1), "jora")[1] == "full"
    assert cls(None, cut(adtext.COLLECTOR_CAP), "jora")[1] == "partial"
    assert cls(None, cut(2000), "jora") == (cut(2000).strip(), "partial")
    assert cls(None, cut(2000) + "   \n", "jora")[1] == "partial"           # stripped, still a cut
    assert adtext.COLLECTOR_CAP == 1990 and adtext.MIN_FULL == 700


def test_classify_takes_the_whole_ad_from_raw_json_when_the_collector_kept_it():
    tail = "Applicants must be Australian citizens or permanent residents."
    whole = "<p>" + "Process invoices and answer supplier queries. " * 60 + "</p><p>" + tail + "</p>"
    raws = {
        "ats_greenhouse": {"content": whole.replace("<", "&lt;").replace(">", "&gt;")},   # Greenhouse escapes its HTML
        "ats_ashby": {"descriptionPlain": html_to_text(whole, limit=20000)},
        "ats_workable": {"description": whole},
        "ats_workday": {"row": {}, "detail": {"jobDescription": whole}},
    }
    for source, raw in raws.items():
        text, kind = adtext.classify(None, cut(2000), source, json.dumps(raw))
        assert kind == "full" and text.endswith(tail) and len(text) > 2000, source
        assert adtext.classify(None, cut(2000), source, raw)[1] == "full"          # a dict works as well
    for bad in (None, "", "not json", "[]", json.dumps({"content": 5}), json.dumps({"detail": None})):
        assert adtext.classify(None, cut(2000), "ats_greenhouse", bad)[1] == "partial"
        assert adtext.classify(None, cut(2000), "ats_workday", bad)[1] == "partial"
    assert adtext.classify(None, cut(2000), "ats_pageup", json.dumps({"content": whole}))[1] == "partial"


def test_ensure_text_does_not_call_a_cut_description_the_full_ad(world, no_net):
    conn, add, row, add_case = world
    pid = add("ats_techone", "t-1", "https://careers.example.com/job/1", "Accounts Clerk", cut(2000))   # no fetcher
    text, kind = adtext.ensure_text(conn, row(pid))
    assert kind == "partial" and text == cut(2000).strip()
    assert adtext.get_text(conn, pid) is None


def test_ensure_text_fetches_the_page_for_a_cut_description_and_replaces_it(world, net):
    conn, add, row, add_case = world
    pid = add_case("ats_successfactors", desc=cut(2000))
    long_page = fx("successfactors_job.html").replace(
        "<div><H2><b>Eligibility", "<div><p>Process invoices and answer supplier queries.</p></div>" * 60 + "<div><H2><b>Eligibility")
    n = net({CASES["ats_successfactors"]["fetch"]: (200, long_page)})
    text, kind = adtext.ensure_text(conn, row(pid))
    assert kind == "full" and len(text) > 2000 and "Australian citizenship or permanent residency" in text
    assert adtext.get_text(conn, pid) == (text, "successfactors_detail") and len(n.calls) == 1
    assert adtext.ensure_text(conn, row(pid)) == (text, "full") and len(n.calls) == 1        # now an ad_text row


def test_a_gone_page_leaves_a_cut_description_partial(world, net):
    conn, add, row, add_case = world
    pid = add_case("ats_pageup", desc=cut(2000))
    net({CASES["ats_pageup"]["fetch"]: (404, "gone")})
    assert adtext.ensure_text(conn, row(pid)) == (cut(2000).strip(), "partial")
    assert adtext.last_status() == "gone"


def test_cut_description_uses_raw_before_any_request(world, no_net):
    conn, add, row, add_case = world
    whole = "<p>" + "Process invoices and answer supplier queries. " * 80 + "</p>"
    pid = add("ats_greenhouse", "t:1", "https://boards.example.com/1", "Accounts Clerk", cut(2000),
              raw={"content": whole})
    text, kind = adtext.ensure_text(conn, row(pid))
    assert kind == "full" and len(text) > 3000
    assert adtext.wants_fetch(conn, row(pid)) is False                      # nothing to ask a site for


def test_each_new_fetcher_reads_what_comes_after_the_cut(net):
    page_tail = {"ats_successfactors": "Australian citizenship or permanent residency", "ats_pageup": "right to work",
                 "ats_pulse": "Banyule City Council is seeking"}
    for source, tail in page_tail.items():
        net(routes_for(source))
        text = adtext._FETCHERS[source].run(ref_for(source))
        assert tail in text


def test_successfactors_url_may_start_with_a_site_code(net):
    url = "https://careers.example.com/PYMHWS/job/Clinician-VIC-3052/1211563066"
    n = net({url: (200, fx("successfactors_job.html"))})
    ref = ref_for("ats_successfactors", url=url, title="Banking Consultant")
    assert "Australian citizenship" in adtext.fetch_successfactors(ref) and n.calls == [(url, True)]
    assert adtext.fetch_successfactors(ref_for("ats_successfactors", url="https://careers.example.com/a/b/job/x/1")) == ""


def test_pulse_matches_the_link_id_and_ignores_other_jobs(net):
    net({CASES["ats_pulse"]["fetch"]: (200, fx("../councils_pulse.json"))})
    assert adtext.fetch_pulse(ref_for("ats_pulse", source_id="banyule:nonesuch")) == ""
    assert adtext.last_status() == "gone"
    assert "Emergency" in adtext.fetch_pulse(ref_for("ats_pulse", source_id="banyule:Fyn1nv",
                                                     title="Emergency Management Officer"))


@pytest.mark.parametrize("source_id", ["", "nocolon", "Banyule:x", "ba nyule:x", "banyule.evil.io/x:y", "banyule:x/../y"])
def test_pulse_source_id_is_validated(source_id, no_net):
    assert adtext.fetch_pulse(ref_for("ats_pulse", source_id=source_id)) == ""


def test_successfactors_filled_page_is_reported_as_gone(net):
    net({CASES["ats_successfactors"]["fetch"]: (200, fx("successfactors_filled.html"))})
    assert adtext._FETCHERS["ats_successfactors"].run(ref_for("ats_successfactors")) == ""
    assert adtext.last_status() == "gone"


def test_challenge_page_is_reported_as_a_wall(net):
    net({CASES["jora"]["fetch"]: (200, fx("jora_challenge.html"))})
    assert adtext.fetch_jora(ref_for("jora")) == ""
    assert adtext.last_status() == "wall"
    net({CASES["jobspy_src"]["fetch"]: (200, fx("linkedin_authwall.html"))})
    assert adtext.fetch_linkedin(ref_for("jobspy_src")) == "" and adtext.last_status() == "wall"
    net({CASES["jora"]["fetch"]: (200, "<html><body>" + "nothing to see " * 50 + "</body></html>")})
    assert adtext.fetch_jora(ref_for("jora")) == "" and adtext.last_status() == "empty"


def test_a_real_ad_page_that_mentions_sign_in_is_not_a_wall(net):
    page = fx("linkedin_job.html").replace("</body>", '<a href="/uas/login">Sign in</a></body>')
    net({CASES["jobspy_src"]["fetch"]: (200, page)})
    assert "Montblanc" in adtext.fetch_linkedin(ref_for("jobspy_src"))


def test_seek_id_is_validated_before_any_request():
    assert adtext.fetch_seek("../../etc/passwd") == "" and adtext.last_status() == "refused"
    assert adtext.fetch_seek("") == ""


# ---------------------------------------------------------------------------------------------- round 2
def _seek_page(body: str) -> str:
    return "<html><script>window.SEEK_REDUX_DATA = " + json.dumps(
        {"jobdetails": {"result": {"job": {"content": body}}}}) + ";\n</script></html>"


SEEK_URL = "https://www.seek.com.au/job/81234567"


def test_fetch_seek_goes_through_the_capped_reader(net):
    n = net({SEEK_URL: (200, _seek_page("<p>Process invoices all day.</p>"))})
    assert adtext.fetch_seek("81234567") == "Process invoices all day."
    assert n.calls == [(SEEK_URL, True)]                                   # _do_get: the 3 MB / 30 s streaming reader
    assert adtext.fetch_seek("81234567", session=object()) == "Process invoices all day."      # old argument is ignored


@pytest.mark.parametrize("status", [403, 429, 500, 503, 401])
def test_fetch_seek_still_stops_the_run_on_block_statuses(status, net):
    net({SEEK_URL: (status, "no")})
    with pytest.raises(adtext.Blocked, match=f"seek HTTP {status}"):
        adtext.fetch_seek("81234567")


def test_fetch_seek_gone_empty_wall_and_redirects(net):
    net({SEEK_URL: (404, "gone")})
    assert adtext.fetch_seek("81234567") == "" and adtext.last_status() == "gone"
    net({SEEK_URL: (200, "<html>" + "nothing here " * 30 + "</html>")})
    assert adtext.fetch_seek("81234567") == "" and adtext.last_status() == "empty"
    net({SEEK_URL: (200, "<html><title>Just a moment</title></html>")})
    assert adtext.fetch_seek("81234567") == "" and adtext.last_status() == "wall"
    n = net({SEEK_URL: (302, "", "https://evil.example.org/x")})
    assert adtext.fetch_seek("81234567") == "" and adtext.last_status() == "refused" and len(n.calls) == 1
    n = net({SEEK_URL: (301, "", "/job/81234567?type=standard"),
             SEEK_URL + "?type=standard": (200, _seek_page("<p>Followed by hand.</p>"))})
    assert adtext.fetch_seek("81234567") == "Followed by hand." and len(n.calls) == 2


def test_lever_ads_are_full_when_raw_json_holds_the_whole_ad():
    opening = cut(2000)
    raw = {"descriptionPlain": opening + " The opening goes on. " * 20,
           "lists": [{"text": "Requirements", "content": "<li>Australian citizenship</li><li>Excel</li>"}],
           "additionalPlain": "Closing note."}
    text, kind = adtext.classify(None, opening, "ats_lever", json.dumps(raw))
    assert kind == "full" and "Australian citizenship" in text and text.endswith("Closing note.") and len(text) > 2000
    assert adtext.classify(None, opening, "ats_lever", raw)[1] == "full"
    for bad in (None, "", "not json", json.dumps({"descriptionPlain": 5}), json.dumps({"lists": "x"})):
        assert adtext.classify(None, opening, "ats_lever", bad)[1] == "partial"
    assert adtext.classify(None, opening, "ats_atlassian", json.dumps(raw))[1] == "partial"   # its raw_json has no ad


def test_a_lever_ad_with_a_mid_length_description_is_read_from_the_whole_raw_text():
    # 1000 characters is "the whole ad" by the description window, but the requirements list with the citizenship line is
    # only in raw_json: the longer raw text wins (same for the other sources that keep the whole ad in raw_json)
    opening = cut(1000)
    raw = {"descriptionPlain": opening,
           "lists": [{"text": "Requirements", "content": "<li>Must hold Australian citizenship</li><li>Excel</li>"}],
           "additionalPlain": "We are an equal opportunity employer. " * 20}
    text, kind = adtext.classify(None, opening, "ats_lever", json.dumps(raw))
    assert kind == "full" and "Australian citizenship" in text and len(text) > 1000
    from jobwatch import reader
    assert reader.rights_backstop(text)                                   # so the rule finds what the description hid
    # a description that already is the whole ad stays as it is; a raw text that is not longer does not replace it
    assert adtext.classify(None, opening, "ats_lever", json.dumps({"descriptionPlain": opening})) == (opening.strip(), "full")
    assert adtext.classify(None, opening, "ats_lever", None) == (opening.strip(), "full")
    # Ashby: a description cut a character short of the cap, whole ad in raw_json
    short_cut = cut(1989)
    whole = {"descriptionPlain": short_cut + " The rest of the ad. " * 100}
    text, kind = adtext.classify(None, short_cut, "ats_ashby", json.dumps(whole))
    assert kind == "full" and len(text) > 1989
    # Atlassian keeps only id, title, type ... in raw_json: there is no raw ad text to read, so nothing changes for it
    assert adtext.classify(None, opening, "ats_atlassian", json.dumps(raw)) == (opening.strip(), "full")


def test_local_text_reads_raw_json_for_a_mid_length_lever_description(world):
    conn, add, row, add_case = world
    opening = cut(1000)
    raw = {"descriptionPlain": opening, "lists": [{"text": "Requirements", "content": "<li>Australian citizenship</li>"}],
           "additionalPlain": "Closing note. " * 60}
    pid = add("ats_lever", "t:1", "https://jobs.lever.co/t/1", "Clerk", opening, raw=raw)
    text, kind = adtext.local_text(conn, row(pid))
    assert kind == "full" and "Australian citizenship" in text


def test_would_request_knows_a_refused_row_without_asking_anyone(no_net):
    indeed = adtext.Ref("jobspy_src", "indeed:in-abc123def", "https://au.indeed.com/viewjob?jk=abc123def", "Clerk",
                        {"site": "indeed"})
    assert adtext.would_request(adtext.fetch_linkedin, indeed) is False
    assert adtext.would_request(adtext.fetch_linkedin, ref_for("jobspy_src")) is True
    assert adtext.would_request(adtext.fetch_jora, ref_for("jora", url="https://example.com/job/x")) is False
    assert adtext.would_request(adtext._seek, adtext.Ref("seek", "../x", "", "", {})) is False
    assert adtext.would_request(adtext._seek, adtext.Ref("seek", "81234567", "", "", {})) is True
    adtext._note("ok")
    adtext.would_request(adtext.fetch_linkedin, indeed)
    assert adtext.last_status() == "ok"                                    # a dry run leaves the last status alone


def test_wants_fetch_is_false_for_a_refused_row_and_force_skips_the_log(world, no_net):
    conn, add, row, add_case = world
    indeed = add("jobspy_src", "indeed:in-abc123def", "https://au.indeed.com/viewjob?jk=abc123def", "Clerk", cut(2000),
                 raw={"site": "indeed", "id": "in-abc123def"})
    assert adtext.wants_fetch(conn, row(indeed)) is False and adtext.wants_fetch(conn, row(indeed), force=True) is False
    assert adtext.ensure_text(conn, row(indeed)) == (cut(2000).strip(), "partial")
    assert conn.execute("SELECT COUNT(*) FROM ad_fetch").fetchone()[0] == 0
    ok = add_case("jora", desc="teaser")
    for _ in range(adtext.FETCH_MAX_TRIES):
        adtext._record_fetch(conn, ok, "wall")
    assert adtext.wants_fetch(conn, row(ok)) is False and adtext.wants_fetch(conn, row(ok), force=True) is True


def test_a_legacy_jsonld_row_needs_a_registry_host(net, monkeypatch):
    url = "https://careers.example.vic.gov.au/jobs/payroll-officer-1"
    legacy = adtext.Ref("jsonld_pages", "Example Council:abc", url, "Payroll Officer", {})
    other = adtext.Ref("ats_workday", "x:JR1", url, "Payroll Officer", {})
    net({})
    monkeypatch.setattr(adtext, "_LEGACY_HOSTS", None)
    assert adtext.fetch_jsonld(legacy) == "" and adtext.last_status() == "refused"
    adtext.set_legacy_hosts(["www.other.example.org"])
    assert adtext.fetch_jsonld(legacy) == "" and adtext.last_status() == "refused"
    n = net({url: (404, "gone")})
    adtext.set_legacy_hosts(["www.careers.example.vic.gov.au"])                    # www. does not matter
    assert adtext.fetch_jsonld(legacy) == "" and adtext.last_status() == "gone" and len(n.calls) == 1
    n = net({url: (404, "gone")})
    monkeypatch.setattr(adtext, "_LEGACY_HOSTS", None)
    adtext.fetch_jsonld(other)                                                     # other sources never used the list
    assert len(n.calls) == 1
