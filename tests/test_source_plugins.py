from pathlib import Path

from conftest import FakeHttp, fixture_text, make_ctx
from jobwatch.collectors import source_plugins as plugins
from jobwatch.models import Posting


def test_declarative_html_parses_fixture_and_fields():
    source = {"name": "example", "url": "https://example.org/jobs", "feed_type": "html",
              "item_selector": ".job", "mapping": {
                  "title": {"selector": "h2", "attribute": "text"},
                  "url": {"selector": "a.apply", "attribute": "href"},
                  "company": {"selector": ".company", "attribute": "text"},
                  "location": {"selector": ".place", "attribute": "text"},
                  "description": {"selector": ".desc", "attribute": "text"},
              }}
    rows = plugins._parse_declarative(fixture_text("plugin_jobs.html"), source)
    p = plugins._posting(rows[0], "example", source)
    assert p.title == "Part-time analyst" and p.company == "Example Co"
    assert p.location == "Melbourne, VIC" and p.url == "https://example.org/jobs/1"


def test_builtin_rss_plugin_maps_feed_fixture():
    class HTTP:
        def get_text(self, url):
            return fixture_text("rss_generic.xml")
    source = {"name": "fixture-feed", "feeds": [{"url": "https://example.org/feed", "company": "Example Co"}]}
    result = plugins.rss_plugin(source, HTTP())
    assert result and all(p.company == "Example Co" for p in result)


def test_invalid_result_has_clear_field_error():
    try:
        plugins._valid([Posting(source="bad", source_id="x", title="", url="https://example.org", company="x")], "broken")
    except plugins.PluginError as exc:
        assert "broken" in str(exc) and "title" in str(exc)
    else:
        assert False, "invalid posting accepted"


def test_page_limit_cache_respect_robots_and_rate(monkeypatch):
    class HTTP:
        def __init__(self): self.calls = []; self.allowed_calls = []
        def allowed(self, url): self.allowed_calls.append(url); return True
        def get_text(self, url, **kw): self.calls.append((url, kw)); return "cached"
    http = HTTP()
    wrapped = plugins.PluginHTTP(http, {"max_pages_per_run": 1, "respect_robots": True, "min_interval_seconds": 0})
    assert wrapped.get_text("https://example.org/a") == "cached"
    assert wrapped.get_text("https://example.org/a") == "cached"
    assert len(http.calls) == 1 and http.allowed_calls
    assert http.calls[0][1]["delay"] >= 2
    try:
        wrapped.get_text("https://example.org/b")
    except plugins.PluginError as exc:
        assert "page limit" in str(exc)
    else:
        assert False, "page limit was not enforced"


def test_respect_robots_false_skips_policy_check():
    class HTTP:
        def __init__(self): self.allowed_calls = 0; self.calls = 0
        def allowed(self, url): self.allowed_calls += 1; return False
        def get_text(self, url, **kw): self.calls += 1; return "ok"
    http = HTTP()
    assert plugins.PluginHTTP(http, {"respect_robots": False}).get_text("https://example.org/a") == "ok"
    assert http.allowed_calls == 0 and http.calls == 1


def test_fixture_python_plugin_loads_through_host(tmp_path, monkeypatch):
    source = tmp_path / "sources"
    source.mkdir()
    (source / "fixture.py").write_text((Path(__file__).parent / "fixtures" / "source_plugin.py").read_text())
    (source / "sources.yaml").write_text('sources:\n - name: fixture-plugin\n   kind: python\n   file: fixture.py\n   respect_robots: false\n   allow_robots_override: true\n   options: {url: https://example.org/jobs}\n')
    monkeypatch.setattr(plugins, "_plugin_dir", lambda: source)
    ctx = make_ctx(FakeHttp({"example.org/jobs": "fixture"}))
    result = plugins.collect(ctx)
    assert result[0].title == "Fixture role"
    assert not ctx.errors


def test_python_plugin_exception_is_source_scoped(tmp_path, monkeypatch):
    source = tmp_path / "sources"
    source.mkdir()
    (source / "bad.py").write_text('NAME="bad"\nVERSION="1"\nFIELDS=("title",)\ndef collect(context, options):\n raise RuntimeError("exact boom")\n')
    (source / "sources.yaml").write_text('sources:\n - name: named-bad\n   kind: python\n   file: bad.py\n')
    monkeypatch.setattr(plugins, "_plugin_dir", lambda: source)
    ctx = make_ctx(FakeHttp({}))
    assert plugins.collect(ctx) == []
    assert any("named-bad" in e and "exact boom" in e for e in ctx.errors)


def test_python_plugin_timeout():
    import time
    try:
        plugins._with_timeout(lambda: time.sleep(.05), .001)
    except plugins.PluginError as exc:
        assert "timed out after 0.001 seconds" in str(exc)
    else:
        assert False, "fixture plugin did not time out"
