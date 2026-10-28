from datetime import datetime, timezone
from pathlib import Path

from jobwatch.collectors import jora

FIX = Path(__file__).parent / "fixtures" / "jora_search.html"


def test_parse_cards():
    rows = jora.parse(FIX.read_text(), "")
    assert len(rows) >= 10
    p = rows[0]
    assert p.title and p.company and p.url.startswith("https://au.jora.com/job/")
    assert "?" not in p.url and len(p.source_id) == 32
    assert len({r.source_id for r in rows}) == len(rows)


def test_posted_from():
    now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    assert jora.posted_from("Posted 4h ago", now).startswith("2026-10-06T08")
    assert jora.posted_from("Posted 2d ago", now).startswith("2026-10-04")
    assert jora.posted_from("", now) is None
