"""The owner decision of 2026-11-09: every configured source sets respect_robots: false.

The declaration must be explicit in the shipped examples and in generated defaults, and it must
not weaken the third-party plugin safety boundary (an unacknowledged override is still refused,
and an unconfigured plugin still respects robots.txt).
"""
from pathlib import Path

import yaml

from conftest import FakeHttp, make_ctx
from jobwatch import fieldgen
from jobwatch.collectors import source_plugins
from jobwatch.config import DEFAULT_CONFIG_DIR, _first_file


def _example(name: str) -> dict:
    path = _first_file([DEFAULT_CONFIG_DIR], name)
    assert path is not None
    return yaml.safe_load(path.read_text())


def _configured_sources(searches: dict) -> dict[str, dict]:
    return {name: value for name, value in searches.items() if isinstance(value, dict) and "enabled" in value}


def test_every_example_search_source_declares_the_owner_policy():
    searches = _example("searches.yaml")
    assert searches["respect_robots"] is False
    sources = _configured_sources(searches)
    assert sources, "the example must configure at least one source"
    assert all(source.get("respect_robots") is False for source in sources.values()), sources.keys()


def test_every_example_feed_source_declares_the_owner_policy():
    feeds = _example("feeds.yaml")
    assert feeds["respect_robots"] is False
    assert feeds["reddit"]["respect_robots"] is False
    assert all(feed.get("respect_robots") is False for feed in feeds["feeds"])


def test_generated_search_defaults_declare_the_owner_policy(tmp_path, monkeypatch):
    profile = {"target_titles": ["Software Engineer"], "candidate": {"location": "Example City, VIC"}}
    monkeypatch.setattr(fieldgen.users, "user_dir", lambda: tmp_path)
    folder = fieldgen.generate_config(profile, "owner")
    searches = yaml.safe_load((folder / "searches.yaml").read_text())
    assert all(source["respect_robots"] is False for source in _configured_sources(searches).values())


def test_context_reads_the_configured_policy_and_safe_default():
    ctx = make_ctx(FakeHttp({}), feeds={})
    ctx.config.searches = {"respect_robots": False}
    assert ctx.respect_robots() is False
    assert ctx.respect_robots("seek") is False

    ctx.config.searches = {"seek": {"respect_robots": True}}
    assert ctx.respect_robots("seek") is True
    assert ctx.respect_robots("careers_vic") is True, "an absent section keeps the safe default"


def test_unacknowledged_plugin_override_is_still_refused(tmp_path, monkeypatch):
    source = tmp_path / "sources"
    source.mkdir()
    (source / "fixture.py").write_text('NAME="p"\nVERSION="1"\nFIELDS=("title",)\ndef collect(context, options):\n return []\n')
    (source / "sources.yaml").write_text(
        'sources:\n - name: unacknowledged\n   kind: python\n   file: fixture.py\n   respect_robots: false\n')
    monkeypatch.setattr(source_plugins, "_plugin_dir", lambda: source)
    ctx = make_ctx(FakeHttp({}))
    assert source_plugins.collect(ctx) == []
    assert any("allow_robots_override" in error for error in ctx.errors)


def test_unconfigured_plugin_keeps_respecting_robots():
    class HTTP:
        def __init__(self):
            self.calls = 0

        def allowed(self, url):
            return False

        def get_text(self, url, **kw):
            self.calls += 1
            return "ok"

    http = HTTP()
    try:
        source_plugins.PluginHTTP(http, {}).get_text("https://example.org/a")
    except source_plugins.PluginError as exc:
        assert "disallows" in str(exc)
    else:
        raise AssertionError("an unconfigured plugin must respect robots.txt")
    assert http.calls == 0
