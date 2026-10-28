"""List, filters and cards use actual immutable agentic output and readiness."""
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from jobwatch import db
from jobwatch.util.llm import LLM
from jobwatch.web import queries
from jobwatch.web.app import create_app
from pipeline.agentic.persistence import latest_result
from pipeline.agentic.service import run_agentic_job
from pipeline.schemas import Stage
from tests.test_agentic_service import SyntheticGateway, world


@pytest.mark.parametrize('reason,label', [
    ('draft_daily_limit', 'Daily drafting limit reached'),
    ('draft_batch_limit', 'Drafting limit for this run reached'),
])
def test_quota_hold_keeps_evaluation_visible_without_ready_badge(world, reason, label):
    conn, config, bundle, add = world
    add(42)
    run_agentic_job(42, config, conn, evidence_bundle=bundle,
                    llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']))
    conn.execute("UPDATE agentic_runs SET status='held',reason=? WHERE posting_id=42", (reason,))
    conn.commit()
    row = queries.load_rows(conn, 'all')[0]
    assert row['ai']['package_ready'] is False
    assert label in row['ai']['reason'] and 'evaluation is saved' in row['ai']['reason']
    summaries = queries.agentic_models(conn, [42])
    assert summaries[42]['has_evaluation'] and label in summaries[42]['hold']


def test_real_agentic_score_reason_archetype_drive_board_filters_and_cards(world):
    conn, config, bundle, add = world
    add(42); add(43, 'Synthetic Stronger'); add(44, low=True)
    for pid, score in ((42, 4.3), (43, 4.8), (44, 2.7)):
        result = run_agentic_job(pid, config, conn, evidence_bundle=bundle,
                                llm=LLM(transport=SyntheticGateway(bundle, score=score), keys=['synthetic']))
        assert result == Stage.READY
    rows = queries.load_rows(conn, 'all')
    by_id = {r['id']: r for r in rows}
    assert [r['id'] for r in queries.sort_rows(rows, 'fit')] == [43, 42, 44]
    row = by_id[42]
    assert row['score5'] == 4.3 and row['score_src'] == 'ai'
    assert row['archetype'] == 'junior accounting'
    assert 'Synthetic evidence supports reconciliation' in row['ai']['reason']
    assert row['ai']['package_ready'] is True and row['ai']['form_ready'] is False
    assert 'submit by hand' not in row['ai']['reason']
    filtered, counts = queries.apply_filters(rows, queries.Filters(scope='all', ai='show', minscore=4.5,
                                                                  arch=['junior accounting']))
    assert [r['id'] for r in filtered] == [43]
    assert counts['arch']['junior accounting'] == 1
    hidden, _ = queries.apply_filters(rows, queries.Filters(scope='all', ai='hide'))
    assert hidden == []
    assert by_id[44]['score5'] == 2.7 and by_id[44]['ai_state'] == 'show'
    with TestClient(create_app(config), base_url='http://localhost', headers={'host': 'localhost'}) as client:
        card = client.get('/api/board?scope=all&ai=show').text
        table = client.get('/api/table?scope=all&ai=show').text
    assert 'Documents ready; open preparation to check the form.' in card
    assert 'Synthetic evidence supports reconciliation' in card
    assert 'junior accounting' in card and '4.3' in card
    assert 'Ready for you to submit by hand' not in card
    assert '4.8' in table and 'junior accounting' in table


def test_board_corrupt_package_is_held_and_corrupt_evaluation_never_uses_stale_reader_score(world):
    conn, config, bundle, add = world; add(42)
    assert run_agentic_job(42, config, conn, evidence_bundle=bundle,
                          llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic'])) == Stage.READY
    conn.execute('INSERT INTO ad_reviews(posting_id,content_hash,prompt_version,model,text_source,verdict,fit,'
                 'reason,reviewed_at,score) VALUES(42,?,?,?,?,?,?,?,?,?)',
                 ('old', 2, 'synthetic', 'full', 'show', 100, 'Stale reader reason', db.ts(), 5.0))
    conn.commit()
    package = latest_result(conn, 42)
    Path(package['cv_pdf']).write_bytes(b'corrupt')
    row = queries.load_rows(conn, 'all', ids=[42])[0]
    assert row['ai_state'] == 'review' and row['score5'] == 4.3
    # Plain words since 88321da; the raw code alone was dropped from the card, hiding why the job is held.
    assert row['ai']['package_ready'] is False and 'CV or letter files failed their check' in row['ai']['reason']
    Path(package['artifact_paths']['evaluation']).write_text('{}')
    row = queries.load_rows(conn, 'all', ids=[42])[0]
    assert row['ai_state'] == 'review' and row['score5'] is None
    assert 'Stale reader reason' not in row['ai']['reason']
    assert row['ai']['package_ready'] is False
