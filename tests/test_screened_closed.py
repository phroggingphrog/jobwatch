"""A closed ad (fetch says gone) is archived as posting_closed with no model call."""
from jobwatch.util import adtext
from pipeline import store
from pipeline.nodes import ingest
from test_pipeline import Gateway, confirmed_candidate, stage, world  # noqa: F401


def test_gone_ad_is_archived_as_posting_closed_without_a_model_call(world):
    conn, add, run, drafts = world
    pid = add("Accounts Assistant", desc="Teaser only.", source="seek")
    calls = []

    def gone(source_id):
        calls.append(source_id)
        adtext._note("gone")                    # what the real fetchers record on 400/404/410
        return ""
    stats = ingest.run(conn, run.config, fetcher=gone)
    assert calls and stats["closed"] == 1
    row = store.get(conn, pid)
    assert row["stage"] == "archived" and row["reason"] == "posting_closed"
    gw = Gateway()
    run(gw)
    assert gw.calls == [] and stage(conn, pid) == "archived"
