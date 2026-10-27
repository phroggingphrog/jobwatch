from types import SimpleNamespace

import pipeline.nodes.ingest as ingest


def test_seek_ad_text_comes_from_the_browser_when_download_fails(monkeypatch):
    saved = {}
    monkeypatch.setattr("jobwatch.interview_browser.browser_ad",
                        lambda url, deadline=None: SimpleNamespace(text="Graduate Accountant. " * 40))
    monkeypatch.setattr(ingest.adtext, "save_text", lambda conn, pid, text, src: saved.update(pid=pid, src=src))
    text, kind = ingest._browser_text(None, {"id": 7, "url": "https://www.seek.com.au/job/1"}, "teaser", "teaser")
    assert kind == "full" and saved == {"pid": 7, "src": "browser"}


def test_one_site_cannot_take_the_whole_fetch_budget(monkeypatch):
    rows = [{"id": i, "source": "ats_smartrecruiters", "url": "u", "company": "c", "title": "t", "location": "Melbourne",
             "raw_json": None, "description": ""} for i in range(20)]
    rows += [{"id": 100 + i, "source": "seek", "url": "u", "company": "c", "title": "t", "location": "Melbourne",
              "raw_json": None, "description": ""} for i in range(5)]
    tried = []
    monkeypatch.setattr(ingest, "candidates", lambda conn, ids=None: rows)
    monkeypatch.setattr(ingest.store, "ensure", lambda conn: None)
    monkeypatch.setattr(ingest, "Rules", lambda *a, **kw: SimpleNamespace(location_rule=lambda p: "melbourne", prescreen=None))
    monkeypatch.setattr(ingest, "posting_of", lambda r: r)
    monkeypatch.setattr(ingest.adtext, "fetch_host", lambda src: src)
    monkeypatch.setattr(ingest.adtext, "wants_fetch", lambda conn, r: True)
    monkeypatch.setattr(ingest.adtext, "pace", lambda: None)
    monkeypatch.setattr(ingest, "BROWSER_FALLBACK", set())

    def ensure_text(conn, r, fetcher=None, *, allow_fetch=True, deadline=None):
        if allow_fetch:
            tried.append(r["source"])
        return "", "teaser"
    monkeypatch.setattr(ingest.adtext, "ensure_text", ensure_text)
    ingest.run(None, SimpleNamespace(rules=None, employers=None), fetch_budget=25)
    assert tried.count("ats_smartrecruiters") == ingest.PER_HOST_FETCHES and tried.count("seek") == 5
