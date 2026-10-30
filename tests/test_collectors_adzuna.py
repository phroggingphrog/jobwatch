"""Adzuna: a keyed aggregator. A missing key must be visible, and the parser must not invent fields."""
import pytest

from jobwatch.collectors import adzuna
from conftest import make_config
from jobwatch.collectors.base import CollectorContext

PAYLOAD = {"results": [
    {"id": "40123456", "title": "Accounts Officer", "company": {"display_name": "Acme Pty Ltd"},
     "location": {"display_name": "Melbourne, Victoria"}, "created": "2026-10-30T01:02:03Z",
     "redirect_url": "https://www.adzuna.com.au/details/40123456",
     "description": "Reconcile ledgers. ", "salary_min": 70000, "salary_max": 75000,
     "contract_time": "full_time", "contract_type": "permanent"},
    {"id": "", "title": "No id"},
]}


def _ctx(tmp_path, monkeypatch, settings, http):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    conf = make_config(tmp_path=tmp_path)
    conf.searches.clear()
    conf.searches.update(settings)
    return CollectorContext(config=conf, http=http, limit=50, tier="slow")


class _Http:
    def __init__(self, payload, status=None):
        self.payload, self.status, self.calls = payload, status, []

    def get_json(self, url, params=None, **kw):
        self.calls.append((url, params))
        if self.status:
            from jobwatch.util.http import HttpError
            raise HttpError(url, self.status)
        return self.payload


def test_missing_key_is_reported_and_nothing_is_fetched(tmp_path, monkeypatch):
    http = _Http(PAYLOAD)
    ctx = _ctx(tmp_path, monkeypatch, {"adzuna": {"enabled": True, "searches": ["accounts"]}}, http)
    assert adzuna.collect(ctx) == []
    assert http.calls == []                       # no request without a key
    assert any("not_configured" in e for e in ctx.errors)


def test_parses_real_shape_and_skips_the_invalid_row(tmp_path, monkeypatch):
    (tmp_path / "key").write_text("k\n")
    http = _Http(PAYLOAD)
    ctx = _ctx(tmp_path, monkeypatch, {"adzuna": {"enabled": True, "app_id": "id1",
                                                  "app_key_file": str(tmp_path / "key"),
                                                  "searches": ["accounts"], "results_per_page": 25}}, http)
    out = adzuna.collect(ctx)
    assert len(out) == 1                          # the row with no id is dropped
    posting = out[0]
    assert posting.source == "adzuna" and posting.source_id == "40123456"
    assert posting.company == "Acme Pty Ltd" and posting.location == "Melbourne, Victoria"
    assert posting.salary_min == 70000 and posting.salary_max == 75000
    assert posting.posted_at_source == "provider"
    url, params = http.calls[0]
    assert url.endswith("/au/search/1") and params["what"] == "accounts" and params["app_id"] == "id1"


def test_disabled_source_makes_no_request(tmp_path, monkeypatch):
    http = _Http(PAYLOAD)
    ctx = _ctx(tmp_path, monkeypatch, {"adzuna": {"enabled": False}}, http)
    assert adzuna.collect(ctx) == [] and http.calls == []


@pytest.mark.parametrize("status", [401, 429, 503])
def test_a_key_or_quota_failure_stops_the_run_without_raising(tmp_path, monkeypatch, status):
    (tmp_path / "key").write_text("k\n")
    http = _Http(PAYLOAD, status=status)
    ctx = _ctx(tmp_path, monkeypatch, {"adzuna": {"enabled": True, "app_id": "id1",
                                                  "app_key_file": str(tmp_path / "key"),
                                                  "searches": ["a", "b"]}}, http)
    assert adzuna.collect(ctx) == []
    assert len(http.calls) == 1                   # it stopped instead of hammering
    assert ctx.errors
