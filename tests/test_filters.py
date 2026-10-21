import pytest

from conftest import make_config
from jobwatch.filters import Rules
from jobwatch.models import Posting

EMPLOYERS = [{"name": "Example Council", "state": "VIC"}, {"name": "Sydney Co", "state": "NSW"}]


@pytest.fixture(scope="module")
def rules():
    return Rules(make_config().rules, EMPLOYERS)


def P(title, location="Melbourne VIC", description="", company="", work_type=None, remote=False):
    return Posting(source="t", source_id=title, url=f"https://x.com/{abs(hash(title))}", title=title,
                   location=location, description=description, company=company, work_type=work_type,
                   remote=remote)


@pytest.mark.parametrize("title,arm", [
    ("Accounts Payable Officer", "accounting_clerk"),
    ("Bookkeeper (Part Time)", "bookkeeper"),
    ("Payroll Officer", "payroll_clerk"),
    ("Administration Officer", "general_clerk"),
    ("Data Entry Operator", "data_entry"),
    ("Medical Receptionist", "receptionist"),
    ("Contact Centre Consultant", "call_centre"),
    ("Customer Service Officer", "information_officer"),
    ("Graduate Accountant - Tax", "graduate_accountant"),
    ("Audit Graduate 2027", "graduate_auditor"),
    ("Junior Data Analyst", "data_analyst"),
    ("Business Improvement Analyst", "management_analyst"),
    ("Business Analyst", "ict_business_analyst"),
    ("Summer Vacation Program - Tax", "programs"),
    ("Finance Internship (Part Time)", "programs"),
])
def test_every_arm_matches(rules, title, arm):
    d = rules.evaluate(P(title))
    assert d.matched and d.arm == arm and d.rules["location"] == "melbourne_vic"
    assert d.rules["title_keyword"]


@pytest.mark.parametrize("title", ["Casual Retail Assistant", "Checkout Operator", "Barista", "Café All Rounder",
                                   "Waiter / Waitress", "Crew Member"])
def test_switched_off_shop_and_hospitality_arms_do_not_match(rules, title):
    # owner 2026-10-05/07: shop-floor and hospitality jobs are not wanted, so their keyword arms are off
    assert not rules.evaluate(P(title)).matched


def test_an_arm_with_enabled_false_is_not_loaded():
    cfg = make_config().rules
    arms = [dict(a) for a in cfg["arms"]]
    on = {a.id for a in Rules({**cfg, "arms": arms}, EMPLOYERS).arms}
    assert "retail_sales" not in on and "programs" in on and "accounting_clerk" in on


@pytest.mark.parametrize("title,reason", [
    ("Senior Accountant", "seniority"),
    ("Payroll Manager", "seniority"),
    ("Head of Customer Service", "seniority"),
    ("Accounts Payable Team Lead", "seniority"),
    ("Principal Business Analyst", "seniority"),
    ("Systems Administrator", "title"),
    ("Civil Engineer", "title"),
    ("Payroll Systems Developer", "off_target"),
    ("Protective Services Officer", "title"),
    ("Disability Support Officer", "title"),
    ("Flight Crew", "title"),
    ("VPS 5 Business Analyst", "seniority"),
])
def test_excludes(rules, title, reason):
    d = rules.evaluate(P(title))
    assert not d.matched and d.reason == reason


def test_team_member_no_longer_matches_now_the_shop_arms_are_off(rules):
    # was a fallback-tier match; shop-floor arms are switched off (owner 2026-10-05/07)
    assert not rules.evaluate(P("Team Member - Casual", "Geelong VIC")).matched


def test_location_rules(rules):
    assert rules.evaluate(P("Bookkeeper", "Sydney NSW")).reason == "location"
    assert rules.evaluate(P("Bookkeeper", "Sydney NSW", remote=True)).rules["location"] == "remote_au"
    assert rules.evaluate(P("Bookkeeper", "Remote, Australia")).rules["location"] == "remote_au"
    d = rules.evaluate(P("Bookkeeper", "", company="Example Council"))
    assert d.rules["location"] == "unknown_location_vic_employer"
    assert rules.evaluate(P("Bookkeeper", "", company="Sydney Co")).reason == "location"
    assert rules.evaluate(P("Bookkeeper", "Dandenong 3175")).matched


@pytest.mark.parametrize("title", ["Credit Administrator", "Audit Administrator", "Benefit Administrator"])
def test_it_administrator_exclude_needs_a_word_boundary(rules, title):
    assert rules.evaluate(P(title)).matched


@pytest.mark.parametrize("title", ["IT Administrator", "Network Administrator", "Contracts Administrator"])
def test_it_administrators_still_excluded(rules, title):
    assert not rules.evaluate(P(title)).matched


def test_national_in_a_title_is_not_remote(rules):
    assert rules.evaluate(P("National Payroll Officer", "Sydney NSW")).reason == "location"
    assert rules.evaluate(P("Payroll Officer - National Accounts", "Sydney NSW")).reason == "location"
    assert rules.evaluate(P("Payroll Officer", "National")).rules["location"] == "remote_au"


@pytest.mark.parametrize("location", ["Victoria Park WA", "Victoria Point QLD", "Hamilton 3200, New Zealand",
                                      "Sydney NSW 3000"])
def test_vic_patterns_ignore_other_places(rules, location):
    assert rules.evaluate(P("Bookkeeper", location)).reason == "location"


@pytest.mark.parametrize("location", ["Victoria, Australia", "Victoria", "Dandenong 3175", "3000"])
def test_vic_patterns_still_match_victoria(rules, location):
    assert rules.evaluate(P("Bookkeeper", location)).rules["location"] == "melbourne_vic"


def test_experience_exclude_and_flag(rules):
    assert rules.evaluate(P("Payroll Officer", description="Minimum 5+ years experience in payroll.")).reason == "experience"
    d = rules.evaluate(P("Payroll Officer", description="You have 2-3 years of experience."))
    assert d.matched and "experience_years>=2" in d.flags and d.rules["experience_years"] == 2


def test_flags(rules):
    d = rules.evaluate(P("Graduate Accountant", description="Applicants must be Australian citizens or permanent residents.",
                         work_type="FT"))
    assert {"work_rights_required", "full_time_only", "entry_level"} <= set(d.flags)
    assert d.matched                                    # work rights is a flag, not a filter
    eeo = rules.evaluate(P("Receptionist", description="We hire without regard to citizenship status. Casual role."))
    assert "work_rights_required" not in eeo.flags and "full_time_only" not in eeo.flags
    ft = rules.evaluate(P("Receptionist", description="This is a full-time role."))
    assert "full_time_only" in ft.flags
    pt = rules.evaluate(P("Receptionist", description="Full-time or part-time considered."))
    assert "full_time_only" not in pt.flags


def test_multiple_arms_recorded(rules):
    d = rules.evaluate(P("Accounts and Payroll Officer"))
    assert d.arm == "accounting_clerk" and "payroll_clerk" in d.arms


def test_title_relevant(rules):
    assert rules.title_relevant("Payroll Officer") and not rules.title_relevant("Senior Payroll Officer")
    assert not rules.title_relevant("Software Engineer")


@pytest.mark.parametrize("title", [
    "Arbor Team Member",                                   # T9: tree crew, not retail
    "Arbor Tree Planting Team Member",
    "Experienced Analyst | External Audit - Global & Private Market",   # T9: not a graduate hire
    "Modern Workplace Operations Analyst",                 # T9: IT operations
    "Technology Operations Analyst",
])
def test_t9_false_positives_not_matched(rules, title):
    assert not rules.evaluate(P(title)).matched


@pytest.mark.parametrize("title,arm", [
    ("Operations Analyst (AML/CTF)", "management_analyst"),
    ("Experienced Medical Receptionist", "receptionist"),   # T9 keeps "experienced" for non-graduate arms
])
def test_t9_true_positives_still_match(rules, title, arm):
    d = rules.evaluate(P(title))
    assert d.matched and d.arm == arm


@pytest.mark.parametrize("location", ["Australia - National", "Sydney / National", "National"])
def test_national_as_a_location_is_remote(rules, location):
    assert rules.evaluate(P("Payroll Officer", location)).rules["location"] == "remote_au"
