"""Human revisions change exact pipeline inputs without editing profile evidence."""
from jobwatch import users
from pipeline.agentic import revisions
from pipeline.agentic.service import snapshot_inventory
from tests.test_agentic_service import world  # noqa: F401


def test_revision_changes_run_key_and_is_isolated(world):
    conn,config,bundle,add=world
    add(1)
    before=snapshot_inventory(conn,config,posting_ids=[1],limit=1)[0]['run_key']
    evidence=dict(bundle.sources)
    revisions.record(1,'Use shorter paragraphs.','synthetic-human-approval')
    after=snapshot_inventory(conn,config,posting_ids=[1],limit=1)[0]['run_key']
    assert before!=after
    assert revisions.current(1)['instructions']=='Use shorter paragraphs.'
    assert bundle.sources==evidence
    with users.use('other-person'):
        assert revisions.current(1) is None
    assert snapshot_inventory(conn,config,posting_ids=[1],limit=1)[0]['run_key']==after
