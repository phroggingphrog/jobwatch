"""Offline human prompts: canonical comparisons, raw answers and bounded issuance."""
from types import SimpleNamespace

import pytest

from jobwatch import preference_service, users
from jobwatch.candidate import intake
from jobwatch.preferences import PreferenceStore, PreferenceError
from tests.preferences.test_core import alternative


def test_identical_profiles_have_distinct_person_contexts_and_shared_db_sets(monkeypatch, tmp_path):
    from jobwatch import db
    monkeypatch.setattr(intake, 'current_version', lambda person: {'version':1, 'facts':[]})
    kwargs = dict(bundle=SimpleNamespace(bundle_hash='b'*64),
                  policy=SimpleNamespace(model_dump=lambda **kwargs: {}), cfg={},
                  structural=SimpleNamespace(run_key='same-structural-input'))
    conn = db.connect(tmp_path / 'shared.db')
    try:
        with users.use('fixture-a'):
            identity_a = preference_service.preference_context(**kwargs)
            item = PreferenceStore(conn).create_set([alternative(i) for i in (1, 2, 3)], identity_a)
        with users.use('fixture-b'):
            identity_b = preference_service.preference_context(**kwargs)
            assert identity_b != identity_a
            assert PreferenceStore(conn).list_sets(identity_b) == []
        with users.use('fixture-a'):
            assert PreferenceStore(conn).list_sets(identity_a)[0]['id'] == item['id']
    finally:
        conn.close()


@pytest.fixture
def prompts(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from jobwatch import db
    from jobwatch.candidate.contracts import digest
    from jobwatch.preferences.features import FAMILIES
    from pipeline.agentic import feedback_prompts as module
    conn = db.connect(tmp_path / 'prompts.db')
    w = SimpleNamespace(conn=conn, module=module, approved={'version':1, 'facts':[]},
        questions=[], entries=[], alternatives=[alternative(i) for i in range(1, 13)],
        now=datetime(2026, 10, 23, tzinfo=timezone.utc),
        config=SimpleNamespace(settings={'pipeline':{'agentic':{}}}))
    for i, alt in enumerate(w.alternatives):
        alt['features']['coverage'] = i / 12
        alt['family'] = FAMILIES[i % 3]
    def pool(conn, config):
        return digest([users.current(), w.approved]), list(w.alternatives)
    monkeypatch.setattr(module, '_pool', pool)
    monkeypatch.setattr(preference_service, 'pool', pool)
    monkeypatch.setattr(intake, 'current_version', lambda person:w.approved)
    monkeypatch.setattr(module, 'policy_for', lambda person, **kw:SimpleNamespace(
        policy_hash=digest(w.approved), open_questions=tuple(w.questions)))
    monkeypatch.setattr(module, '_entries', lambda conn, config:list(w.entries))
    monkeypatch.setattr(module, '_now', lambda:w.now)
    yield w
    conn.close()


def next_prompt(w):
    return w.module.next_prompt(w.conn, w.config, now=w.now)


def accepted_fit(identity='a'*64):
    from jobwatch.preferences.features import NAMES, FAMILIES
    beta = [[0.]*(2*len(NAMES)) for _ in range(2)]
    beta[0][NAMES.index('coverage')] = 3.
    beta[1][NAMES.index('coverage')] = -3.
    return dict(id='synthetic-arithmetic-only', origin='owner', context_hash=identity,
        profile_hash='b'*64, draws={'beta':beta, 'alpha':[[0.]*len(FAMILIES) for _ in beta]},
        preprocessing={'names':list(NAMES), 'centers':[0.]*len(NAMES),
                       'scales':[1.]*len(NAMES), 'missing_rates':[0.]*len(NAMES)})


def test_information_gain_and_probabilities_match_canonical_prediction():
    from pipeline.agentic import feedback_prompts as module
    from jobwatch.preferences.model import predict_set
    rows = [alternative(i) for i in (1, 2, 3)]
    for row, coverage in zip(rows, [0., .5, 1.]):
        row['features']['coverage'] = coverage
    fit = accepted_fit()
    class Store:
        def status(self, identity):
            return {'status':'valid', 'fit':fit}
    canonical = predict_set(Store(), rows, fit['context_hash'])
    information = module.information_gain(fit, rows)
    assert information > 0
    result = module.posterior_choices(Store(), rows, fit['context_hash'])
    assert result['information_gain'] == pytest.approx(information)
    assert result['probabilities'] == pytest.approx([
        item['choice_probability']['mean'] for item in canonical['alternatives']])
    assert result['none_probability'] == pytest.approx(canonical['none_probability']['mean'])
    for row in rows:
        row['features']['coverage'] = 0.
    assert module.information_gain(fit, rows) == pytest.approx(0., abs=1e-12)


def test_cold_start_is_deterministic_with_no_invented_differences():
    from pipeline.agentic import feedback_prompts as module
    from jobwatch.preferences.features import FAMILIES
    rows = [alternative(i) for i in (7, 2, 9, 4)]
    for row, family in zip(rows, FAMILIES[:4]):
        row['family'] = family
    assert module.cold_start_triple(rows) == (2, 4, 7)
    assert module.cold_start_triple(list(reversed(rows))) == (2, 4, 7)
    for row in rows:
        row['family'] = 'accounting'
    rows[0]['family'] = 'Accounting'
    assert module.cold_start_triple(rows) is None


def test_next_comparison_is_unpaid_current_and_reuses_one_open_prompt(prompts):
    w = prompts
    result = next_prompt(w)
    prompt = result['prompt']
    assert result['reason'] is None and prompt['type'] == 'comparison'
    assert len(prompt['options']) == 3
    assert all(option['posting_id'] >= 4 for option in prompt['options'])  # newest nine
    assert prompt['basis'] == 'cold_start_disagreement' and prompt['ordering'] == 'provisional'
    assert prompt['none_probability'] is None
    assert all(option['display_propensity'] is None for option in prompt['options'])
    assert prompt['subject_digest'] and prompt['manifest']['person'] == users.current()
    assert next_prompt(w)['prompt'] == prompt
    assert w.module.outstanding_prompt(w.conn) == prompt
    assert w.module.list_prompts(w.conn) == [prompt]
    assert w.conn.execute('SELECT count(*) FROM feedback_prompts').fetchone()[0] == 1
    assert not w.conn.execute('SELECT 1 FROM preference_picks').fetchone()


def test_comparison_pick_is_canonical_exact_and_idempotent(prompts):
    from pipeline.agentic import feedback
    w = prompts
    prompt = next_prompt(w)['prompt']
    selected = prompt['options'][0]['posting_id']
    event = w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], selected,
        request_id='choice', actor='person', source='chat')
    assert event['kind'] == 'comparison' and event['source'] == 'chat'
    assert event['detail']['selected'] == selected
    assert event['detail']['subject_digest'] == prompt['subject_digest']
    assert event['posting_id'] == selected
    assert PreferenceStore(w.conn).get_set(prompt['set_id'])['selected'] == selected
    assert w.module.outstanding_prompt(w.conn) is None
    assert w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], selected,
        request_id='choice', actor='person', source='chat') == event
    with pytest.raises((w.module.PromptError, feedback.FeedbackError), match='feedback_conflict'):
        w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], None,
            request_id='choice', actor='person', source='chat')
    assert w.conn.execute('SELECT count(*) FROM preference_picks').fetchone()[0] == 1


def test_none_is_a_genuine_choice_and_invalid_option_is_not(prompts):
    w = prompts
    prompt = next_prompt(w)['prompt']
    with pytest.raises(w.module.PromptError, match='invalid_request'):
        w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], 999,
            request_id='bad', actor='person')
    event = w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], None,
        request_id='none', actor='person')
    assert event['posting_id'] is None and event['detail']['selected'] is None
    item = PreferenceStore(w.conn).get_set(prompt['set_id'])
    assert item['answered'] and item['selected'] is None


@pytest.mark.parametrize('change', ['ad', 'profile', 'dismissal'])
def test_stale_comparison_closes_without_recording_a_choice(prompts, change):
    from pipeline.agentic import feedback
    w = prompts
    prompt = next_prompt(w)['prompt']
    selected = prompt['options'][0]['posting_id']
    if change == 'ad':
        next(row for row in w.alternatives if row['posting_id']==selected)['ad_hash'] = 'c'*64
    elif change == 'profile':
        w.approved = {'version':2, 'facts':[]}
    else:
        w.conn.execute('BEGIN')
        feedback.append_event(w.conn, kind='reject', actor='person', request_id='dismiss-job',
            posting_id=selected, reason_code='pay_too_low')
        w.conn.commit()
    with pytest.raises(w.module.PromptError, match='comparison_stale'):
        w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], selected,
            request_id='stale-pick', actor='person')
    assert not w.conn.execute('SELECT 1 FROM preference_picks').fetchone()
    assert w.module.list_prompts(w.conn)[0]['closed_reason'] == 'stale'


def test_pick_crash_recovery_finalizes_an_existing_exact_pick_even_if_now_stale(prompts, monkeypatch):
    from pipeline.agentic import feedback
    w = prompts
    prompt = next_prompt(w)['prompt']
    selected = prompt['options'][0]['posting_id']
    original = feedback.append_event
    def crash(*args, **kwargs):
        raise RuntimeError('synthetic post-pick crash')
    monkeypatch.setattr(feedback, 'append_event', crash)
    with pytest.raises(RuntimeError, match='synthetic post-pick crash'):
        w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], selected,
            request_id='recover-me', actor='person')
    assert w.conn.execute('SELECT count(*) FROM preference_picks').fetchone()[0] == 1
    monkeypatch.setattr(feedback, 'append_event', original)
    w.approved = {'version':2, 'facts':[]}
    event = w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], selected,
        request_id='recover-me', actor='person')
    assert event['detail']['selected'] == selected
    assert w.module.list_prompts(w.conn)[0]['closed_reason'] == 'answered'
    assert w.conn.execute('SELECT count(*) FROM preference_picks').fetchone()[0] == 1
    assert len(feedback.list_events(w.conn)) == 1


def test_set_creation_crash_recovers_the_same_reserved_prompt(prompts, monkeypatch):
    w = prompts
    original = PreferenceStore.create_set
    def crash(*args, **kwargs):
        raise RuntimeError('synthetic set crash')
    monkeypatch.setattr(PreferenceStore, 'create_set', crash)
    with pytest.raises(RuntimeError, match='synthetic set crash'):
        next_prompt(w)
    reserved = w.module.outstanding_prompt(w.conn)
    assert reserved and reserved['set_id'] is None
    monkeypatch.setattr(PreferenceStore, 'create_set', original)
    recovered = next_prompt(w)['prompt']
    assert recovered['prompt_id'] == reserved['prompt_id'] and recovered['set_id']
    assert w.conn.execute('SELECT count(*) FROM feedback_prompts').fetchone()[0] == 1
    assert w.conn.execute('SELECT count(*) FROM preference_sets').fetchone()[0] == 1


def test_question_answer_preserves_words_without_profile_amendment(prompts):
    w = prompts
    w.alternatives = []
    w.questions = ['What work hours do you want?']
    approved = dict(w.approved)
    prompt = next_prompt(w)['prompt']
    assert prompt['type'] == 'question' and prompt['text'] == w.questions[0]
    text = '  My exact answer.\n'
    event = w.module.answer_question(w.conn, w.config, prompt['prompt_id'], text,
        request_id='answer', actor='person')
    assert event['reason_text'] == text and event['kind'] == 'answer'
    assert w.approved == approved
    assert w.module.answer_question(w.conn, w.config, prompt['prompt_id'], text,
        request_id='answer', actor='person') == event
    assert not w.conn.execute("SELECT 1 FROM sqlite_master WHERE name='preference_picks'").fetchone()


def test_questions_prefer_profile_then_shared_uncertainty_and_cool_down(prompts):
    from datetime import timedelta
    w = prompts
    w.alternatives = []
    w.questions = ['Confirm available hours?']
    w.entries = [SimpleNamespace(posting_id=i, entry_id=f'e{i}', run_key=f'r{i}', rank=i,
                                unresolved=['Shared uncertainty?']) for i in (1,2)]
    first = next_prompt(w)['prompt']
    assert first['source'] == 'open_question'
    dismissed = w.module.dismiss_prompt(w.conn, first['prompt_id'], config=w.config,
        request_id='dismiss-first', actor='person')
    assert w.module.dismiss_prompt(w.conn, first['prompt_id'], config=w.config,
        request_id='dismiss-first', actor='person') == dismissed
    second = next_prompt(w)['prompt']
    assert second['source'] == 'shared_unresolved' and second['text'] == 'Shared uncertainty?'
    w.module.dismiss_prompt(w.conn, second['prompt_id'], config=w.config,
        request_id='dismiss-second', actor='person')
    assert next_prompt(w)['prompt'] is None
    w.now += timedelta(days=31)
    assert next_prompt(w)['prompt']['text'] == first['text']


def test_weekly_cap_counts_dismissed_prompts_and_settings_can_disable(prompts):
    from datetime import timedelta
    w = prompts
    w.alternatives = []
    for i in range(3):
        w.questions = [f'Question {i}?']
        prompt = next_prompt(w)['prompt']
        w.module.dismiss_prompt(w.conn, prompt['prompt_id'], config=w.config,
            request_id=f'dismiss-{i}', actor='person')
    w.questions = ['Question four?']
    assert next_prompt(w) == {'prompt':None, 'reason':'rate_limited'}
    w.now += timedelta(days=8)
    assert next_prompt(w)['prompt'] is not None
    w.config.settings['pipeline']['agentic']['prompts_per_week'] = 0
    assert next_prompt(w) == {'prompt':None, 'reason':'disabled'}


def test_prompt_and_choice_visibility_is_person_bound_on_shared_connection(prompts):
    w = prompts
    with users.use('fixture-a'):
        prompt = next_prompt(w)['prompt']
    with users.use('fixture-b'):
        assert w.module.outstanding_prompt(w.conn) is None
        assert w.module.list_prompts(w.conn) == []
        with pytest.raises(w.module.PromptError, match='prompt_not_found'):
            w.module.answer_comparison(w.conn, w.config, prompt['prompt_id'], None,
                request_id='steal', actor='person')
        own = next_prompt(w)['prompt']
        assert own['set_id'] != prompt['set_id']
    with users.use('fixture-a'):
        assert w.module.outstanding_prompt(w.conn)['prompt_id'] == prompt['prompt_id']


@pytest.mark.parametrize('actor', ['agent', None, 'owner'])
def test_human_writes_require_the_person(prompts, actor):
    w = prompts
    with pytest.raises(w.module.PromptError, match='person_required'):
        w.module.answer_question(w.conn, w.config, 'unknown', 'text', request_id='a', actor=actor)


def test_rejected_jobs_and_previous_sets_are_not_offered(prompts):
    from pipeline.agentic import feedback
    from jobwatch.candidate.contracts import digest
    w = prompts
    identity = digest([users.current(), w.approved])
    PreferenceStore(w.conn).create_set(w.alternatives[:3], identity)
    w.conn.execute('BEGIN')
    feedback.append_event(w.conn, kind='reject', actor='person', request_id='r',
        posting_id=12, reason_code='pay_too_low')
    w.conn.commit()
    prompt = next_prompt(w)['prompt']
    assert {option['posting_id'] for option in prompt['options']}.isdisjoint({1,2,3,12})


def test_valid_posterior_is_used_and_malformed_or_wrong_profile_falls_back(prompts, monkeypatch):
    from jobwatch.candidate.contracts import digest
    w = prompts
    fit = accepted_fit(digest([users.current(), w.approved]))
    real_store = PreferenceStore(w.conn)
    validations = []
    def status(identity):
        validations.append(identity)
        return {'status':'valid', 'fit':fit}
    monkeypatch.setattr(real_store, 'status', status)
    monkeypatch.setattr(w.module, '_preference_store', lambda conn:real_store)
    prompt = next_prompt(w)['prompt']
    assert prompt['basis'] == 'information_gain' and prompt['ordering'] == 'personalised'
    assert len(validations) == 1
    assert prompt['expected_information_gain'] >= 0.
    assert sum(option['choice_probability'] for option in prompt['options']) + prompt['none_probability'] == pytest.approx(1.)
    w.module.dismiss_prompt(w.conn, prompt['prompt_id'], config=w.config, request_id='d', actor='person')
    fit['profile_hash'] = 'c'*64
    fallback = next_prompt(w)['prompt']
    assert fallback['basis'] == 'cold_start_disagreement' and fallback['ordering'] == 'provisional'
    assert all(option['choice_probability'] is None for option in fallback['options'])


def test_question_can_preserve_four_thousand_human_characters(prompts):
    w = prompts
    w.alternatives = []
    w.questions = ['Explain availability?']
    prompt = next_prompt(w)['prompt']
    text = 'Exact human answer. ' * 200
    assert len(text) == 4000
    event = w.module.answer_question(w.conn, w.config, prompt['prompt_id'], text,
        request_id='long-answer', actor='person')
    assert event['detail']['text'] == text
    assert event['reason_text'] == ''


def test_stale_question_cannot_become_a_profile_fact_or_feedback(prompts):
    w = prompts
    w.alternatives = []
    w.questions = ['What hours?']
    prompt = next_prompt(w)['prompt']
    w.approved = {'version':2, 'facts':[]}
    with pytest.raises(w.module.PromptError, match='prompt_stale'):
        w.module.answer_question(w.conn, w.config, prompt['prompt_id'], 'Weekdays',
            request_id='stale-answer', actor='person')
    assert w.module.list_prompts(w.conn)[0]['closed_reason'] == 'stale'
    assert w.conn.execute('SELECT count(*) FROM feedback_events').fetchone()[0] == 0
    assert w.approved['facts'] == []


def test_large_pool_still_uses_only_the_nine_newest_unseen(prompts):
    from jobwatch.preferences.features import FAMILIES
    w = prompts
    w.alternatives = [alternative(i) for i in range(1, 151)]
    for i, row in enumerate(w.alternatives):
        row['family'] = FAMILIES[i % 3]
    prompt = next_prompt(w)['prompt']
    assert all(option['posting_id'] >= 142 for option in prompt['options'])


def test_malformed_posterior_falls_back_after_canonical_validation(prompts, monkeypatch):
    from jobwatch.candidate.contracts import digest
    w = prompts
    fit = accepted_fit(digest([users.current(), w.approved]))
    fit['draws']['beta'][0][0] = float('nan')
    store = PreferenceStore(w.conn)
    monkeypatch.setattr(store, 'status', lambda identity:{'status':'valid','fit':fit})
    monkeypatch.setattr(w.module, '_preference_store', lambda conn:store)
    assert next_prompt(w)['prompt']['basis'] == 'cold_start_disagreement'


def test_information_gain_never_uses_more_than_one_thousand_draws():
    from pipeline.agentic import feedback_prompts as module
    rows = [alternative(i) for i in (1, 2, 3)]
    for row, value in zip(rows, [0., .5, 1.]):
        row['features']['coverage'] = value
    fit = accepted_fit()
    first = fit['draws']['beta'][0]
    opposite = fit['draws']['beta'][1]
    alpha = fit['draws']['alpha'][0]
    fit['draws']['beta'] = [first]*1000 + [opposite]*1000
    fit['draws']['alpha'] = [alpha]*2000
    assert module.information_gain(fit, rows) == pytest.approx(0., abs=1e-12)
    with pytest.raises(PreferenceError, match='invalid_draw_limit'):
        module.information_gain(fit, rows, max_draws=1001)


def test_prompt_reads_and_no_profile_issuance_never_create_schema(monkeypatch):
    import sqlite3
    from pipeline.agentic import feedback_prompts as module
    value = sqlite3.connect(':memory:')
    monkeypatch.setattr(intake, 'current_version', lambda person:None)
    def refuse(*args, **kwargs):
        raise AssertionError('unconfirmed profile must not inspect candidate inputs')
    monkeypatch.setattr(module, '_pool', refuse)
    assert module.outstanding_prompt(value) is None
    assert module.list_prompts(value) == []
    assert module.prompts_this_week(value) == 0
    assert module.next_prompt(value, SimpleNamespace(settings={}))['prompt'] is None
    assert value.execute('SELECT count(*) FROM sqlite_master').fetchone()[0] == 0
    value.close()


@pytest.mark.parametrize('settings', [{'prompts_enabled':'true'}, {'prompts_per_week':True},
    {'prompts_per_week':-1}, {'question_cooldown_days':None}])
def test_invalid_prompt_configuration_is_refused(prompts, settings):
    w = prompts
    w.config.settings['pipeline']['agentic'].update(settings)
    with pytest.raises(w.module.PromptError, match='invalid_configuration'):
        next_prompt(w)
    assert w.module.list_prompts(w.conn) == []


def test_request_ids_cannot_cross_pending_prompt_responses(prompts, monkeypatch):
    from pipeline.agentic import feedback
    w = prompts
    w.alternatives = []
    w.questions = ['Question one?']
    first = next_prompt(w)['prompt']
    w.module.dismiss_prompt(w.conn, first['prompt_id'], config=w.config,
        request_id='one-key', actor='person')
    w.questions = ['Question two?']
    second = next_prompt(w)['prompt']
    with pytest.raises(w.module.PromptError, match='feedback_conflict'):
        w.module.answer_question(w.conn, w.config, second['prompt_id'], 'My answer',
            request_id='one-key', actor='person')
    assert feedback.list_events(w.conn) == []


def test_real_frozen_pool_and_question_round_trip_without_model_calls(frozen):
    from pipeline.agentic import feedback_prompts as module
    from pipeline.agentic import shortlist
    from jobwatch.candidate.contracts import digest
    shortlist.build_shortlist(frozen.conn, frozen.config)
    before = digest(intake.current_version(users.current()))
    result = module.next_prompt(frozen.conn, frozen.config)
    prompt = result['prompt']
    assert prompt is not None
    if prompt['type'] == 'question':
        event = module.answer_question(frozen.conn, frozen.config, prompt['prompt_id'],
            'Synthetic human clarification.', request_id='real-fixture-answer', actor='person')
        assert event['detail']['text'] == 'Synthetic human clarification.'
    else:
        event = module.answer_comparison(frozen.conn, frozen.config, prompt['prompt_id'],None,
            request_id='real-fixture-none', actor='person')
        assert event['detail']['selected'] is None
    assert digest(intake.current_version(users.current())) == before

from tests.baseline_support import world, frozen  # noqa: E402, F401


def test_concurrent_issuance_keeps_one_durable_prompt_and_set(prompts, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from jobwatch import db
    w = prompts
    path = w.conn.execute('PRAGMA database_list').fetchone()[2]
    barrier = Barrier(2)
    original = w.module._snapshot
    def aligned(conn, config):
        result = original(conn,config)
        if not conn.in_transaction:
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(w.module, '_snapshot', aligned)
    def issue():
        conn = db.connect(path)
        try:
            return w.module.next_prompt(conn,w.config,now=w.now)['prompt']
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _:issue(), range(2)))
    assert first['prompt_id'] == second['prompt_id']
    assert first['set_id'] == second['set_id']
    assert w.conn.execute('SELECT count(*) FROM feedback_prompts').fetchone()[0] == 1
    assert w.conn.execute('SELECT count(*) FROM preference_sets').fetchone()[0] == 1
