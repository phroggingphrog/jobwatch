from jobwatch import db
from jobwatch.models import Posting
from jobwatch.dedupe import ingest

def item(**changes):
    return Posting(source='ats_workday', source_id='fixture:req1', url='https://example.invalid/job/1',
        title='Example vacancy', company='Example employer', **changes)

def test_delayed_primary_source_details_enrich_the_existing_listing(tmp_path):
    conn = db.connect(tmp_path / 'jobs.db')
    ident, _ = ingest(conn, item(location=''))
    detailed = item(location='Sydney NSW', description='Full actual employer advertisement.',
                    raw={'detail': {'jobDescription': 'Full actual employer advertisement.'}})
    assert ingest(conn, detailed) == (ident, False)
    saved = dict(conn.execute('SELECT * FROM postings WHERE id=?', (ident,)).fetchone())
    assert saved['description'] == detailed.description
    assert saved['location'] == 'Sydney NSW'
    assert 'jobDescription' in saved['raw_json']
    # Later sparse metadata must not erase acquired evidence.
    ingest(conn, item(location=''))
    assert conn.execute('SELECT description FROM postings WHERE id=?', (ident,)).fetchone()[0] == detailed.description

def test_another_source_cannot_replace_primary_evidence(tmp_path):
    conn = db.connect(tmp_path / 'jobs.db')
    ident, _ = ingest(conn, item(location=''))
    other = Posting(source='synthetic_aggregator', source_id='other', url='https://example.invalid/job/1',
                    title='Example vacancy', location='Perth WA', description='Other source text.')
    assert ingest(conn, other) == (ident, False)
    assert conn.execute('SELECT description FROM postings WHERE id=?', (ident,)).fetchone()[0] == ''
