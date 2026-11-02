"""Synthetic screening regressions. No network or private profiles."""
import asyncio

from jobwatch.util.llm import LLM
from pipeline import graph, screened, store
from pipeline.nodes import gate, ingest
from pipeline.schemas import JobFacts, MatchScore, Stage
from test_pipeline import Gateway, confirmed_candidate, facts, score, world  # noqa: F401


def test_low_fit_is_retained_with_auditable_score(world):
    conn, add, run, drafts = world
    pid = add('Low fit')
    g = screened.ScreenedGraph(conn=conn, db_path=str(run.config.db_path), config=run.config,
                              settings=graph.Settings(sort_per_run=0),
                              llm=LLM(transport=Gateway(evaluate={'Low fit': score(1, 1, 1)}), keys=['test']))
    asyncio.run(g.run())
    row = store.get(conn, pid)
    assert row['stage'] == 'shortlisted'
    assert row['data']['gate']['assessment']['fit_score'] == 1.0
    assert row['data']['gate']['assessment']['recommendation'] == 'consider'
    assert drafts['n'] == 0


def test_unverified_constraint_keeps_assessment_out_of_dlq(world):
    conn, add, run, drafts = world
    pid = add('Unverified')
    gateway = Gateway(extract={'Unverified': facts(work_rights={'requirement': 'citizen_only', 'quote': 'not present'})})
    g = screened.ScreenedGraph(conn=conn, db_path=str(run.config.db_path), config=run.config,
                              settings=graph.Settings(sort_per_run=0), llm=LLM(transport=gateway, keys=['test']))
    asyncio.run(g.run())
    row = store.get(conn, pid)
    assert row['stage'] == 'shortlisted'
    assert row['data']['gate']['assessment']['recommendation'] == 'needs_clarification'
    assert row['data']['evaluate']['overall'] > 0
    assert conn.execute('SELECT count(*) FROM pipeline_dlq WHERE posting_id=?', (pid,)).fetchone()[0] == 0
    assert drafts['n'] == 0


def test_program_flag_cannot_override_confirmed_hours(monkeypatch):
    from jobwatch.candidate.policy import build_policy
    policy = build_policy({'version': 1, 'facts': [{'section': 'work_rights', 'basis': 'evidence',
              'value': {'hours_limit_per_fortnight': 48}}]})
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda *a, **k: policy)
    f = JobFacts.model_validate(facts(program=True, hours='full_time_only',
                                      work_rights={'requirement': 'none_stated', 'quote': ''}))
    route, decision = gate.decide(f, MatchScore.model_validate(score()),
                                  'This position requires 38 hours per week.', hours_policy='allow_hours_only')
    assert (route, decision.reason) == ('archive', 'hours_exceeded')


def test_short_ad_runs_extract_evaluate_and_gate(world):
    conn, add, run, drafts = world
    pid = add('Short listing', desc='Accounts assistant, flexible hours.')
    result = ingest.run(conn, run.config, posting_ids=[pid], fetch_budget=0)
    assert result['partial'] == 1 and store.get(conn, pid)['stage'] == 'ingested'
    gateway = Gateway(extract={'Short listing': facts(real_job=False, work_rights={'requirement': 'none_stated', 'quote': ''})})
    g = screened.ScreenedGraph(conn=conn, db_path=str(run.config.db_path), config=run.config,
                              settings=graph.Settings(sort_per_run=0), llm=LLM(transport=gateway, keys=['test']))
    asyncio.run(g.run(ingest_new=False))
    row = store.get(conn, pid)
    assert row['stage'] == str(Stage.SHORTLISTED)
    assert row['data']['ingest']['text_kind'] == 'teaser'
    assert row['data']['evaluate']['overall'] > 0
    assert 'full_ad_unavailable' in row['data']['gate']['assessment']['unknowns']
    assert row['data']['gate']['assessment']['recommendation'] == 'needs_clarification'
    assert [r['node'] for r in conn.execute('SELECT node FROM pipeline_events WHERE posting_id=? ORDER BY id', (pid,))] == ['ingest', 'extract', 'evaluate', 'gate']
    assert drafts['n'] == 0


def test_challenge_page_is_not_ingested(world):
    conn, add, run, _ = world
    pid = add('Challenge', desc='<title>Just a moment</title> verify you are human')
    result = ingest.run(conn, run.config, posting_ids=[pid], fetch_budget=0)
    assert result['waiting_text'] == 1 and store.get(conn, pid) is None
