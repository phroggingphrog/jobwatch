"""The decision-policy flag, the single live gate call, the decision log and the policy-aware knock-outs.

Synthetic data only: the service world is a temporary directory and the model is the synthetic gateway."""
import copy
import inspect
import re

import pytest

from jobwatch import preference_service
from jobwatch.candidate.policy import default_policy
from jobwatch.llm import LLM
from pipeline.agentic import decision_log, gate, service
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.location import commute_km_for, km_from_home
from pipeline.agentic.persistence import latest_result
from pipeline.schemas import Stage
from tests.candidate.policy_fixtures import fact, policy_of
from tests.test_agentic_service import SyntheticGateway, world  # noqa: F401  (world is a fixture)

ACCOUNTING = fact('exclusion', {'kind': 'family', 'value': 'accounting'})


def with_flag(config, value):
    """A copy of the config with `pipeline.agentic.decision_policy` set; the original is untouched."""
    clone = copy.copy(config)
    clone.settings = copy.deepcopy(config.settings)
    clone.settings['pipeline']['agentic']['decision_policy'] = value
    return clone


def key_for(conn, config, bundle, pid=42):
    """The RunKey of an already-added posting, built exactly as the run builds it."""
    cfg = service._config(config)
    inputs = service.load_inputs(bundle, cfg)
    return service._run_key(pid, service._capture(conn, pid), bundle, default_policy(), cfg, inputs)


def evaluate(world, config, *, llm=None, pid=42):
    conn, _, bundle, _ = world
    llm = llm or LLM(transport=SyntheticGateway(bundle), keys=['synthetic'])
    stage = service.run_agentic_job(pid, config, conn, evidence_bundle=bundle, llm=llm, operation='evaluate')
    return stage, latest_result(conn, pid)


def table_exists(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gate_decisions'").fetchone() is not None


def test_flag_is_legacy_by_default_and_outside_the_run_key(world):
    conn, config, bundle, add = world
    add(42)
    assert service.decision_policy_mode(config) == 'legacy'
    on = with_flag(config, 'profile')
    assert service.decision_policy_mode(on) == 'profile' and service._config(on) == service._config(config)
    assert key_for(conn, on, bundle) == key_for(conn, config, bundle)    # same posting, same bundle -> identical RunKey with either value


@pytest.mark.parametrize('value', [True, 'yes', 1, None, ''])
def test_flag_must_be_legacy_or_profile(world, value):
    _, config, _, _ = world
    bad = with_flag(config, value)
    with pytest.raises(AgenticError, match='invalid_configuration'):
        service.decision_policy_mode(bad)
    with pytest.raises(AgenticError, match='invalid_configuration'):
        service.decision_policy_for(bad)


def test_decision_policy_fields_never_enter_the_run_key(world, monkeypatch):    # contract decision 4
    conn, config, bundle, add = world
    add(42)
    policies = [policy_of(ACCOUNTING),
                policy_of(fact('exclusion', {'kind': 'employer', 'value': 'Synthetic Beta'}),
                          fact('experience', 'Ledger clerk'), version=3),
                policy_of(fact('exclusion', 'something unclear', fid='x9'), version=4)]
    assert len({p.policy_hash for p in policies}) == 3 and len({p.profile_version for p in policies}) == 3
    assert policies[2].open_questions != policies[0].open_questions
    keys = []
    for mode in ('legacy', 'profile'):
        for policy in policies:
            monkeypatch.setattr(service, 'policy_for', lambda person, policy=policy: policy)
            keys.append(key_for(conn, with_flag(config, mode), bundle))
    assert len(keys) == 6
    for key in keys[1:]:
        assert (key.value, key.config_hash, key.candidate_hash) == (keys[0].value, keys[0].config_hash, keys[0].candidate_hash)
    source = inspect.getsource(service._run_key)
    assert 'DecisionPolicy' not in source and 'policy_hash' not in source


def test_profile_mode_gate_uses_the_confirmed_policy(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    dp = policy_of(ACCOUNTING)
    monkeypatch.setattr(service, 'policy_for', lambda person: dp)
    stage, result = evaluate(world, with_flag(config, 'profile'))
    assert stage == Stage.ARCHIVED and result['status'] == 'archived' and result['reason'] == 'policy_excluded'
    assert tuple(conn.execute('SELECT stage, reason FROM pipeline_state WHERE posting_id=42').fetchone()) == (
        str(Stage.ARCHIVED), 'policy_excluded')
    logged = decision_log.latest(conn, result['run_key'])
    assert logged['policy_hash'] == dp.policy_hash and logged['profile_version'] == dp.profile_version
    assert (logged['route'], logged['reason']) == ('archive', 'policy_excluded')


def test_legacy_mode_ignores_the_policy_and_writes_no_decision_row(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    monkeypatch.setattr(service, 'policy_for', lambda person: policy_of(ACCOUNTING))
    stage, result = evaluate(world, config)
    assert stage == Stage.DLQ and result['status'] == 'held' and result['reason'] == 'evaluation_complete'
    assert not table_exists(conn)
    assert decision_log.latest(conn, result['run_key']) is None


def test_profile_mode_without_a_confirmed_policy_runs_the_legacy_gate(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    monkeypatch.setattr(service, 'policy_for', lambda person: None)
    assert service.decision_policy_for(with_flag(config, 'profile')) is None
    stage, result = evaluate(world, with_flag(config, 'profile'))
    assert stage == Stage.DLQ and result['reason'] == 'evaluation_complete'     # the legacy result
    assert not table_exists(conn)


def test_removing_an_exclusion_releases_the_job_without_a_model_call(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    on = with_flag(config, 'profile')
    gateway = SyntheticGateway(bundle)
    llm = LLM(transport=gateway, keys=['synthetic'])
    excluded, released = policy_of(ACCOUNTING), policy_of(fact('experience', 'Ledger clerk'), version=3)
    monkeypatch.setattr(service, 'policy_for', lambda person: excluded)
    stage, first = evaluate(world, on, llm=llm)
    assert stage == Stage.ARCHIVED and first['reason'] == 'policy_excluded'
    calls = len(gateway.calls)
    assert calls > 0
    monkeypatch.setattr(service, 'policy_for', lambda person: released)
    stage, second = evaluate(world, on, llm=llm)
    assert second['run_key'] == first['run_key']
    assert stage != Stage.ARCHIVED and second['status'] == 'held' and second['reason'] == 'evaluation_complete'
    assert len(gateway.calls) == calls                                          # no model call
    assert decision_log.latest(conn, first['run_key'])['policy_hash'] == released.policy_hash
    rows = conn.execute('SELECT policy_hash, route FROM gate_decisions WHERE run_key=? ORDER BY policy_hash',
                        (first['run_key'],)).fetchall()
    assert sorted(map(tuple, rows)) == sorted([(excluded.policy_hash, 'archive'), (released.policy_hash, 'draft')])


def test_a_policy_excluded_archive_stays_archived_when_the_policy_path_is_off(world, monkeypatch):
    conn, config, bundle, add = world
    add(42)
    monkeypatch.setattr(service, 'policy_for', lambda person: policy_of(ACCOUNTING))
    stage, first = evaluate(world, with_flag(config, 'profile'))
    assert stage == Stage.ARCHIVED
    stage, again = evaluate(world, config)                                      # legacy: the old archive is final
    assert stage == Stage.ARCHIVED and again['reason'] == 'policy_excluded'


def test_gate_current_is_the_only_live_gate_call(world, monkeypatch):           # contract decision 2
    conn, config, bundle, add = world
    add(42)
    dp = policy_of(fact('experience', 'Ledger clerk'))
    monkeypatch.setattr(service, 'policy_for', lambda person: dp)
    on = with_flag(config, 'profile')
    via_gate_current, decide_kwargs = [], []
    real_current, real_decide = service.gate_current, gate.decide
    current_source = inspect.getsource(real_current)
    monkeypatch.setattr(service, 'gate_current',
                        lambda *a, **k: via_gate_current.append(k) or real_current(*a, **k))
    monkeypatch.setattr(service, 'decide', lambda *a, **k: decide_kwargs.append(k) or real_decide(*a, **k))
    summary = service.agentic_batch_run([42], on, conn, evidence_bundle=bundle,
                                        llm=LLM(transport=SyntheticGateway(bundle), keys=['synthetic']),
                                        operation='evaluate')
    assert summary['held'] == 1
    assert len(via_gate_current) == 1 and len(decide_kwargs) == 1
    for name in ('posting', 'ad_text', 'decision_policy', 'policy'):
        assert name in via_gate_current[0]
    assert via_gate_current[0]['decision_policy'] is dp and via_gate_current[0]['posting']['company'] == 'Synthetic Alpha'
    assert decide_kwargs[0]['decision_policy'] is dp and decide_kwargs[0]['company'] == 'Synthetic Alpha'
    # the preference pool takes the same road
    via_gate_current.clear(); decide_kwargs.clear()
    preference_service.pool(conn, on)
    assert len(via_gate_current) == 1 and via_gate_current[0]['decision_policy'] is dp
    assert len(decide_kwargs) == 1 and decide_kwargs[0]['decision_policy'] is dp
    # and no other source line calls the gate
    from pipeline.agentic import baseline
    for module in (service, preference_service, baseline):
        calls = re.findall(r'^(?!\s*(?:def|from|import|#)).*\bdecide\(', inspect.getsource(module), re.M)
        assert len(calls) == (1 if module is service else 0), module.__name__
    assert re.search(r'\bdecide\(', current_source)


def test_gate_current_derives_commute_and_company_from_the_posting(world, monkeypatch):
    from tests.baseline_support import synthetic_case
    case = synthetic_case()
    evaluation = service.validate_model_payload(service.AgenticEvaluation, case.evaluation)
    dp = policy_of(fact('location', 'I live in Box Hill, VIC; open to Melbourne or remote work'),
                   fact('exclusion', {'kind': 'employer', 'value': 'Synthetic Alpha'}))
    posting = {'title': 'Junior Analyst', 'company': 'Synthetic Alpha', 'location': 'Carlton VIC'}
    seen = []
    real = service.decide
    monkeypatch.setattr(service, 'decide', lambda *a, **k: seen.append(k) or real(*a, **k))
    decision = service.gate_current(evaluation, posting=posting, ad_text=case.snapshot['full_ad'], decision_policy=dp,
                                    policy=default_policy(), captured_complete=True)
    expected = commute_km_for('Box Hill, VIC', 'Carlton VIC')
    assert type(expected) is int
    assert seen[0]['commute_km'] == expected == service.commute_km_of(dp, 'Carlton VIC')
    assert seen[0]['company'] == 'Synthetic Alpha' and seen[0]['title'] == 'Junior Analyst'
    assert (decision.route, decision.reason) == ('archive', 'policy_excluded')       # the employer rule hits the company
    other = service.gate_current(evaluation, posting={**posting, 'company': 'Synthetic Beta'},
                                 ad_text=case.snapshot['full_ad'], decision_policy=dp, policy=default_policy())
    assert other.reason != 'policy_excluded'
    seen.clear()                                                                     # an explicit value is passed through
    service.gate_current(evaluation, posting=posting, ad_text=case.snapshot['full_ad'], decision_policy=dp,
                         policy=default_policy(), commute_km=7)
    assert seen[0]['commute_km'] == 7


def test_jev_knockouts_follow_the_policy():
    assert service.applicable_knockouts(None) == {'citizen_or_pr', 'five_years'}
    assert service.applicable_knockouts(policy_of(fact('preference', 'graduate roles'))) == {'citizen_or_pr', 'five_years'}
    assert service.applicable_knockouts(policy_of(fact('preference', 'mid-level roles'),
                                                  fact('work_rights', 'Australian citizen'))) == frozenset()
    assert service.applicable_knockouts(policy_of(fact('experience', 'x'))) == {'citizen_or_pr'}   # no stated level: no seniority knock-out


def test_run_filters_the_jev_knockouts_through_the_policy(world, monkeypatch):
    conn, config, bundle, add = world
    add(42); add(43, 'Synthetic Beta')
    assert service.extras_settings(config)['knockout_at']['citizen_or_pr'] <= 0.99
    answers = {'injection': 0.0, 'citizen_or_pr': 0.99, 'five_years': 0.99}
    monkeypatch.setattr(service, 'jev_screen', lambda ad, cfg=None: dict(answers))
    stage, result = evaluate(world, config, pid=42)                                  # legacy: the first knock-out wins
    assert stage == Stage.ARCHIVED and result['reason'] == 'work_rights:citizen_or_pr'
    on = with_flag(config, 'profile')
    # a citizen who states no level: neither knock-out applies, the job is judged and held for evaluation
    monkeypatch.setattr(service, 'policy_for', lambda person: policy_of(fact('work_rights', 'Australian citizen')))
    stage, result = evaluate(world, on, pid=43)
    assert stage != Stage.ARCHIVED and result['reason'] == 'evaluation_complete'
    # a non-citizen who wants junior roles keeps both
    monkeypatch.setattr(service, 'policy_for', lambda person: policy_of(fact('preference', 'junior roles')))
    answers['citizen_or_pr'] = 0.0
    add(44, 'Synthetic Gamma')
    stage, result = evaluate(world, on, pid=44)
    assert stage == Stage.ARCHIVED and result['reason'] == 'too_senior'


def test_commute_comes_from_the_policy_home(monkeypatch):
    monkeypatch.setattr('pipeline.agentic.location._profile_home', lambda: 'brunswick')   # the owner's profile suburb
    homed = policy_of(fact('location', 'I live in Box Hill, VIC'))
    homeless = policy_of(fact('experience', 'x'))
    assert homed.home['place'] == 'Box Hill, VIC' and homeless.home is None
    assert service.commute_km_of(homed, 'Carlton VIC') == commute_km_for('Box Hill, VIC', 'Carlton VIC')
    assert type(service.commute_km_of(homed, 'Carlton VIC')) is int
    assert km_from_home('Carlton VIC') is not None                                   # the owner lives in Brunswick
    assert service.commute_km_of(homeless, 'Carlton VIC') is None                   # no home -> no distance, whatever the owner
    assert service.commute_km_of(None, 'Carlton VIC') == km_from_home('Carlton VIC')
    assert service.commute_km_of(None, None) == km_from_home('')
    assert service.commute_km_of(homed, None) is None


def test_the_run_hands_the_evaluator_the_policy_commute(world, monkeypatch):
    conn, config, bundle, add = world
    add(42); add(43, 'Synthetic Beta')
    seen = []
    real = service.evaluate_job
    monkeypatch.setattr(service, 'evaluate_job', lambda *a, **k: seen.append(k['commute_km']) or real(*a, **k))
    on = with_flag(config, 'profile')
    monkeypatch.setattr(service, 'policy_for', lambda person: policy_of(fact('location', 'I live in Box Hill, VIC')))
    evaluate(world, on, pid=42)
    monkeypatch.setattr(service, 'policy_for', lambda person: policy_of(fact('experience', 'x')))
    evaluate(world, on, pid=43)
    assert seen == [commute_km_for('Box Hill, VIC', 'Melbourne VIC'), None]


def test_decision_log_is_idempotent_and_per_run_key(tmp_path):
    import sqlite3
    from pipeline.agentic.contracts import AgenticGateDecision, RunKey
    conn = sqlite3.connect(tmp_path / 'log.db')
    a, b = policy_of(ACCOUNTING), policy_of(fact('experience', 'x'), version=3)
    run = RunKey(posting_id=1, ad_hash='1' * 64, evidence_hash='2' * 64, rubric_version='t', config_hash='3' * 64)
    archive = AgenticGateDecision(route='archive', reason='policy_excluded', global_score=4.0, run_key=run)
    draft = AgenticGateDecision(route='draft', reason='eligible', global_score=4.0, run_key=run)
    assert decision_log.latest(conn, run.value) is None                              # no table yet, and a read creates none
    assert not table_exists(conn)
    decision_log.record(conn, run.value, a, archive)
    decision_log.record(conn, run.value, a, archive)
    assert conn.execute('SELECT COUNT(*) FROM gate_decisions').fetchone()[0] == 1
    decision_log.record(conn, run.value, b, draft)
    assert conn.execute('SELECT COUNT(*) FROM gate_decisions WHERE run_key=?', (run.value,)).fetchone()[0] == 2
    newest = decision_log.latest(conn, run.value)
    assert (newest['policy_hash'], newest['profile_version'], newest['route'], newest['reason']) == (
        b.policy_hash, b.profile_version, 'draft', 'eligible')
    assert decision_log.latest(conn, 'other-run') is None
    conn.close()
