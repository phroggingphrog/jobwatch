from datetime import datetime, timezone

from jobwatch.models import (Posting, canonical_url, html_to_text, is_australian, relative_posted,
                             salary_from_text, state_of, work_type_of)


def test_canonical_url_strips_tracking():
    u = "HTTPS://Www.Example.com/jobs/1/?utm_source=x&b=2&a=1&gclid=z&refId=9#frag"
    assert canonical_url(u) == "https://www.example.com/jobs/1?a=1&b=2"
    assert canonical_url("https://au.indeed.com/viewjob?jk=abc&from=serp") == "https://au.indeed.com/viewjob?jk=abc"


def test_au_gate():
    assert is_australian("AU") and is_australian({"alpha2Code": "AU"}) and not is_australian("NZ")
    assert is_australian(None, "Melbourne") and is_australian(None, "Clayton, VIC 3168")
    assert is_australian(None, "Remote - Australia")
    assert not is_australian(None, "Melbourne, FL") and not is_australian(None, "Victoria, BC")
    assert not is_australian(None, "Chicago") and not is_australian(None, "")


def test_state_of():
    assert state_of("Craigieburn, Melbourne VIC") == "VIC"
    assert state_of("Sunshine Coast QLD") == "QLD"
    assert state_of("Portland, Victoria") == "VIC"
    assert state_of("Sydney NSW") == "NSW" and state_of("Paris") is None


def test_foreign_places_sharing_au_names_are_not_australian():
    for loc in ("Victoria Island, Lagos, Nigeria", "Victoria, Seychelles", "Sydney, Nova Scotia",
                "Newcastle upon Tyne, UK", "Perth, Scotland"):
        assert not is_australian(None, loc) and state_of(loc) is None, loc
    assert is_australian(None, "Sydney, Australia") and is_australian(None, "Perth WA")
    assert is_australian(None, "Wales Street, Newcastle NSW") and is_australian(None, "Sydney, New South Wales")


def test_state_of_prefers_explicit_state_and_needs_postcode_context():
    assert state_of("Victoria Park WA") == "WA" and state_of("Victoria Point QLD") == "QLD"
    assert state_of("Mumbai, MH 3000") is None and state_of("Hamilton 3200, New Zealand") is None
    assert state_of("Dandenong 3175") == "VIC" and state_of("Melbourne CBD 3000") == "VIC"


def test_work_type_and_salary():
    assert work_type_of("Part time") == "PT" and work_type_of("FULL_TIME") == "FT"
    assert work_type_of("Casual") == "casual" and work_type_of("12M fixed term contract") == "contract"
    assert salary_from_text("$70,000 - $80,000 + super") == (70000, 80000, "year")
    assert salary_from_text("$32 - $35 per hour") == (32, 35, "hour")
    assert salary_from_text("$70K – $80K") == (70000, 80000, "year")


def test_work_type_needs_word_boundaries():
    for text in ("Internal Auditor", "Template Designer", "Attempt", "Contracts Administrator", "Casualty Clerk"):
        assert work_type_of(text) is None, text
    assert work_type_of("Intern") == "intern" and work_type_of("Summer Internship") == "intern"
    assert work_type_of("Contract role") == "contract" and work_type_of("Contractor") == "contract"
    assert work_type_of("Temp") == "temp" and work_type_of("Temporary") == "temp"
    assert work_type_of("Permanent") == "FT" and work_type_of("fulltime") == "FT"


def test_salary_unit_boundaries_and_month():
    assert salary_from_text("$70,000 Joseph") == (70000, 70000, "year")      # "ph" only as its own token
    assert salary_from_text("$70,000 graph") == (70000, 70000, "year")
    assert salary_from_text("$38 ph") == (38, 38, "hour") and salary_from_text("$38 p.h.") == (38, 38, "hour")
    assert salary_from_text("$6,000 per month") == (6000, 6000, "month")
    assert salary_from_text("$6,000 a month + super") == (6000, 6000, "month")


def test_relative_posted():
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    assert relative_posted("Posted 3 Days Ago", now).day == 3
    assert relative_posted("Posted Today", now) == now
    assert relative_posted("18h ago", now).hour == 6


def test_posting_defaults_and_truncation():
    p = Posting(source="s", source_id=1, url="https://x.com/a/?utm_medium=y", title=" A  &amp; B ",
                location="Melbourne VIC", description="x" * 5000)
    assert p.url == "https://x.com/a" and p.title == "A & B" and p.state == "VIC"
    assert len(p.description) == 2000 and p.posted_at_source == "observed" and p.posted_at


def test_html_to_text_double_escaped():
    assert html_to_text("&lt;p&gt;Hello&lt;/p&gt;&lt;p&gt;World &amp;amp; co&lt;/p&gt;") == "Hello\nWorld & co"
