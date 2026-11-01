"""A category action needs explicit exclusion authority."""
from pipeline import screened, store
from pipeline.nodes import ingest
from pipeline.schemas import Stage
from test_pipeline import confirmed_candidate, world  # noqa: F401


def config_for(base, confirmed):
    base.settings = {'pipeline': {'execution_mode': 'screened', 'screened': {
        'unlisted_action': 'archive', 'category_snapshot': {'categories': [{
            'id': 'goal', 'label': 'Goal', 'priority': 0, 'phrases': ['cashier'],
            'action': 'archive', 'exclusion_confirmed': confirmed,
            'promote': True, 'hours': 'standard'}]}}}}
    return base


def test_goal_and_unlisted_titles_do_not_archive(world):
    conn, add, run, _ = world
    pid = add('Cashier')
    other = add('Unlisted job', company='Another company')
    cfg = config_for(run.config, False)
    ingest.run(conn, cfg, posting_ids=[pid, other], fetch_budget=0)
    assert store.get(conn, pid)['stage'] == 'ingested'
    assert store.get(conn, other)['stage'] == 'ingested'


def test_confirmed_category_can_archive(world):
    conn, add, run, _ = world
    pid = add('Cashier')
    ingest.run(conn, config_for(run.config, True), posting_ids=[pid], fetch_budget=0)
    assert store.get(conn, pid)['stage'] == 'archived'


def test_sort_untracked_never_drops_unlisted(world):
    conn, add, run, _ = world
    pid = add('Unlisted job')
    store.ensure(conn)
    store.admit(conn, pid, 'synthetic', {'evaluate': {'overall': 2}}, Stage.SHORTLISTED)
    screened.sort_untracked(conn, config_for(run.config, False))
    assert store.get(conn, pid)['stage'] == 'shortlisted'
