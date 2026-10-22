"""Decision policy and search strategy derived from a confirmed profile (synthetic data only)."""
import pytest
from pydantic import ValidationError

from jobwatch.candidate import intake
from jobwatch.candidate.contracts import KNOWN_FAMILIES, MINIMUM_EXCLUDED_CODES, TargetPolicy, digest
from jobwatch.candidate.policy import (DecisionPolicy, default_policy, describe, exclusion_hit, policy_for, profile_target_policy,
                                       rules_from_fact, strategy_for)
from tests.test_agentic_service import world  # noqa: F401  (world is a fixture)

from .policy_fixtures import approved, fact, policy_of


def test_unemployed_without_contrary_instruction_is_employment_first():
    p = policy_of(fact('employment_status', 'Currently unemployed, seeking work'), fact('experience', 'Accounts Assistant, Ledger Co'))
    assert (p.strategy, p.focus) == ('employment_first', ())

def test_career_focus_wins_over_unemployment():
    p = policy_of(fact('employment_status', 'Currently unemployed'), fact('career_focus', 'Junior data analyst roles'))
    assert (p.strategy, p.focus) == ('career_focus', ('Junior data analyst roles',))

def test_unemployment_never_overrides_exclusions():
    p = policy_of(fact('employment_status', 'Currently unemployed'), fact('exclusion', {'kind': 'family', 'value': 'retail'}, fid='f9'))
    assert p.strategy == 'employment_first'
    assert [(r.kind, r.value, r.source_fact_id, r.actor) for r in p.exclusions] == [('family', 'retail', 'f9', 'person')]

def test_inferred_unemployment_and_unknown_status_are_balanced_and_ask():
    p = policy_of(fact('employment_status', 'unemployed', basis='inference'))
    assert p.strategy == 'balanced' and 'employment_status' in p.open_questions

def test_inference_and_unknown_facts_never_become_rules():
    p = policy_of(fact('exclusion', {'kind': 'family', 'value': 'hospitality'}, basis='inference'), fact('constraint', 'commute under 10 km', basis='inference'),
                  fact('work_rights', '40 hours per fortnight', basis='unknown'))
    assert p.exclusions == () and p.max_commute_km is None and 'hours_limit_per_fortnight' not in p.work_rights

@pytest.mark.parametrize('value', ['no remote work', 'casual jobs', 'never in Sydney', 'Acme Pty Ltd', {'kind': 'salary', 'value': 'x'}, {'kind': 'employer', 'value': ''}])
def test_free_text_exclusion_stays_prompt_text_and_asks(value):      # contract decision 6
    p = policy_of(fact('exclusion', value, fid='x1'))
    assert p.exclusions == () and 'exclusion:x1' in p.open_questions

@pytest.mark.parametrize('kind,value', [('family', 'retail'), ('employer', 'Example Co'), ('title_term', 'sales'), ('location', 'NSW'), ('work_type', 'remote')])
def test_a_structured_exclusion_becomes_a_rule_with_its_source_fact(kind, value):
    p = policy_of(fact('exclusion', {'kind': kind, 'value': value}, fid='x2'))
    assert [(r.kind, r.value, r.source_fact_id, r.actor) for r in p.exclusions] == [(kind, value, 'x2', 'person')]
    assert not any(q.startswith('exclusion:') for q in p.open_questions)

def test_a_family_rule_value_must_be_a_known_family():
    p = policy_of(fact('exclusion', {'kind': 'family', 'value': 'not-a-family'}, fid='x3'))
    assert p.exclusions == () and 'exclusion:x3' in p.open_questions

def test_location_and_commute_are_read_from_evidence_text():
    p = policy_of(fact('location', 'I live in Box Hill, VIC; open to Melbourne or remote work'), fact('constraint', 'Will not commute more than 30 km'))
    assert p.home == {'place': 'Box Hill, VIC', 'state': 'VIC', 'country': 'AU'}
    assert (p.regions, p.remote_ok, p.max_commute_km) == (('VIC',), True, 30.0)

def test_no_location_facts_means_no_area_limit():
    p = policy_of(fact('experience', 'Accounts Assistant'))
    assert (p.regions, p.home, p.max_commute_km, p.remote_ok) == ((), None, None, None) and 'location' in p.open_questions

def test_work_rights_come_from_approved_facts():
    p = policy_of(fact('work_rights', 'Student visa, up to 48 hours per fortnight'), fact('work_rights', {'full_time_programs_ok': True}))
    assert p.work_rights['hours_limit_per_fortnight'] == 48 and p.work_rights['full_time_programs_ok'] is True

@pytest.mark.parametrize('text,expect', [('Australian citizen', True), ('Permanent resident of Australia', True),
                                         ('I am not an Australian citizen', False), ('Working holiday visa', None)])
def test_citizen_or_pr_detection(text, expect):
    assert policy_of(fact('work_rights', text)).work_rights.get('citizen_or_pr') is expect

def test_seniority_from_stated_levels_ignores_negated_ones():
    assert policy_of(fact('preference', 'Looking for graduate and junior roles')).seniority == ('entry', 'junior')
    assert policy_of(fact('preference', 'no senior roles please')).seniority == ()
    assert policy_of(fact('experience', 'Senior Accountant, Ledger Co')).seniority == ()

def test_policy_hash_is_stable_and_tracks_content_and_version():
    ex = {'kind': 'family', 'value': 'retail'}
    a, b = policy_of(fact('exclusion', ex)), policy_of(fact('exclusion', ex))
    assert a.policy_hash == b.policy_hash and policy_of(fact('exclusion', ex), version=3).policy_hash != a.policy_hash
    with pytest.raises(ValueError, match='policy_hash_mismatch'):
        DecisionPolicy.model_validate({**a.model_dump(mode='json'), 'policy_hash': '0' * 64})

def test_changed_circumstances_change_the_strategy():
    v2 = policy_of(fact('employment_status', 'Currently unemployed'), version=2)
    v3 = policy_of(fact('employment_status', 'Currently unemployed'), fact('career_focus', 'Nursing'), version=3)
    assert (v2.strategy, v3.strategy) == ('employment_first', 'career_focus')

def test_policy_for_needs_a_confirmed_scope_bearing_version_and_is_per_person(monkeypatch):
    versions = {'fx-a': approved(fact('experience', 'Accounts Assistant')), 'fx-adopted': {'version': 1, 'facts': [], 'adopted_from_files': True}}
    monkeypatch.setattr(intake, 'current_version', lambda person: versions.get(person))
    assert policy_for('fx-a').profile_version == 2 and policy_for('fx-b') is None and policy_for('fx-adopted') is None

def test_policy_for_builds_from_a_pinned_approved_payload(monkeypatch):    # contract decision 1: a baseline's frozen approved.json
    live = approved(fact('exclusion', {'kind': 'family', 'value': 'retail'}), version=3)
    monkeypatch.setattr(intake, 'current_version', lambda person: live)
    frozen = approved(fact('exclusion', {'kind': 'family', 'value': 'accounting'}), version=2)
    pinned, current = policy_for('fx-a', approved=frozen), policy_for('fx-a')
    assert (pinned.profile_version, pinned.exclusions[0].value) == (2, 'accounting') and (current.profile_version, current.exclusions[0].value) == (3, 'retail')
    assert policy_for('fx-a', approved={'version': 1, 'facts': []}) is None
    assert policy_for('fx-a', approved=frozen).policy_hash == pinned.policy_hash          # deterministic


def _policy(*rules, regions=(), **kw):
    facts = [fact('exclusion', {'kind': k, 'value': v}, fid=f'r{i}') for i, (k, v) in enumerate(rules)]
    if regions:
        facts.append(fact('location', ' and '.join(regions)))
    return policy_of(*facts)


def _hit(p, **kw):
    args = dict(family=None, company='Example Co', title='Accounts Assistant', location_text='Melbourne VIC', remote=False, hours='')
    args.update(kw)
    return exclusion_hit(p, **args)


def test_exclusion_hit_family_employer_title_term():
    p = _policy(('family', 'retail'), ('employer', 'Example'), ('title_term', 'sales'))
    assert _hit(p, family='retail', company='Other Ltd').kind == 'family'
    assert _hit(p, family=None, company='Other Ltd') is None                       # no family known: a family rule cannot hit
    assert _hit(p, company='Other Ltd') is None
    assert _hit(p, company='THE EXAMPLE GROUP').kind == 'employer'
    assert _hit(p, company='Examples Ltd') is None                                 # whole word only
    assert _hit(p, company='Other', title='Senior Sales Lead').kind == 'title_term'
    assert _hit(p, company='Other', title='Salesforce Admin') is None


def test_exclusion_hit_work_type():
    p = _policy(('work_type', 'remote'), ('work_type', 'casual'), ('work_type', 'full_time'), ('work_type', 'part_time'))
    kinds = {r.value for r in p.exclusions}
    assert kinds == {'remote', 'casual', 'full_time', 'part_time'}
    assert _hit(p, company='Other', remote=True).value == 'remote'
    assert _hit(p, company='Other', hours='casual').value == 'casual'
    assert _hit(p, company='Other', hours='full_time_only').value == 'full_time'
    assert _hit(p, company='Other', title='Part-time Clerk').value == 'part_time'
    assert _hit(p, company='Other') is None


def test_exclusion_hit_location_state_only_when_no_alternative():
    p = _policy(('location', 'NSW'))
    assert _hit(p, location_text='Sydney NSW').kind == 'location'
    assert _hit(p, location_text='Sydney NSW or Melbourne VIC') is None
    assert _hit(p, location_text='Melbourne VIC') is None


def test_exclusion_hit_location_place_token():
    p = _policy(('location', 'Geelong'))
    assert _hit(p, location_text='Geelong, VIC').kind == 'location'
    assert _hit(p, location_text='Geelong or Melbourne') is None
    assert _hit(p, location_text='Geelong / Remote') is None
    assert _hit(p, location_text='Geelong; Ballarat') is None
    assert _hit(p, location_text='Newtown') is None


@pytest.mark.parametrize('bad', [None, '', 123, '\x00\ud800', 'x' * 10000])
def test_exclusion_hit_and_strategy_never_raise_on_odd_text(bad):
    p = _policy(('family', 'retail'), ('employer', 'Example'), ('title_term', 'sales'), ('location', 'NSW'), ('work_type', 'part_time'))
    exclusion_hit(p, family=bad, company=bad, title=bad, location_text=bad, remote=False, hours=bad)
    strategy_for([{'section': 'employment_status', 'basis': 'evidence', 'value': bad}, None, {'value': {}}, {}])


def test_rule_id_uses_fact_id_else_hash():
    r = rules_from_fact(fact('exclusion', {'kind': 'employer', 'value': 'Example Co'}, fid='x9'))[0]
    assert r.rule_id == 'x9:employer'
    r2 = rules_from_fact({'section': 'exclusion', 'basis': 'evidence', 'value': {'kind': 'employer', 'value': 'Example Co'}})[0]
    assert r2.source_fact_id is None and len(r2.rule_id) == 12 and int(r2.rule_id, 16) >= 0


def test_rules_from_fact_ignores_other_shapes():
    assert rules_from_fact(fact('skill', {'kind': 'employer', 'value': 'x'})) == []
    assert rules_from_fact(fact('exclusion', {'kind': 'employer', 'value': 'x'}, basis='inference')) == []
    assert rules_from_fact(fact('exclusion', 'free text')) == []
    assert rules_from_fact({}) == [] and rules_from_fact(None) == []


def test_remote_and_regions_rules():
    assert policy_of(fact('preference', 'Happy with wfh')).remote_ok is True
    assert policy_of(fact('preference', 'remote work is fine'), fact('constraint', 'on-site only')).remote_ok is False
    p = policy_of(fact('location', 'Melbourne or Sydney'), fact('preference', 'Australia-wide is fine'))
    assert p.regions == ()
    assert policy_of(fact('location', 'Melbourne or Sydney')).regions == ('NSW', 'VIC')


def test_describe_modes(monkeypatch):
    monkeypatch.setattr(intake, 'current_version', lambda person: approved(fact('exclusion', 'no retail please', fid='x1')))
    got = describe('fx-a', mode='profile')
    assert got['enabled'] is True and got['policy']['profile_version'] == 2 and 'reason' not in got
    q = {x['code']: x for x in got['open_questions']}
    assert 'no retail please' in q['exclusion:x1']['question'] and q['employment_status']['why']
    assert describe('fx-a', mode='legacy')['enabled'] is False
    monkeypatch.setattr(intake, 'current_version', lambda person: None)
    assert describe('fx-b', mode='profile') == {'policy': None, 'mode': 'profile', 'enabled': True, 'open_questions': [],
                                                'reason': 'no_confirmed_profile'}


# --- a place the person rules out is asked about, never dropped
def test_never_in_a_place_asks_and_adds_no_region():
    p = policy_of(fact('location', 'I live in Box Hill, VIC'), fact('constraint', 'never in Sydney', fid='n1'))
    assert 'exclusion:n1' in p.open_questions and 'NSW' not in p.regions and p.regions == ('VIC',)


def test_a_welcomed_place_survives_a_negated_one_in_the_same_sentence():
    p = policy_of(fact('location', 'Open to Melbourne, but not Sydney', fid='n2'))
    assert p.regions == ('VIC',) and 'exclusion:n2' in p.open_questions
    assert 'location' not in p.open_questions


def test_not_australia_wide_is_a_narrowing_that_asks():
    p = policy_of(fact('location', 'Not Australia-wide, just Melbourne', fid='n3'))
    assert p.regions == ('VIC',) and 'exclusion:n3' in p.open_questions


def test_anywhere_except_asks():
    p = policy_of(fact('location', 'Anywhere in Victoria except Geelong', fid='n4'))
    assert 'exclusion:n4' in p.open_questions and p.regions == ('VIC',)


def test_a_clean_state_and_suburb_pair_is_not_split():
    p = policy_of(fact('location', 'Richmond, NSW'))
    assert p.regions == ('NSW',) and not any(q.startswith('exclusion:') for q in p.open_questions)


def test_not_far_does_not_negate_a_place():
    p = policy_of(fact('location', 'I live in Box Hill VIC, not far from the city', fid='n5'))
    assert p.regions == ('VIC',) and 'exclusion:n5' not in p.open_questions


def test_negated_australia_wide_does_not_clear_regions_or_the_location_question():
    p = policy_of(fact('location', 'Not Australia-wide', fid='n7'), fact('location', 'Melbourne'))
    assert p.regions == ('VIC',) and 'location' not in p.open_questions
    assert any(q.startswith('exclusion:') for q in p.open_questions) and 'exclusion:n7' in p.open_questions


def test_australia_wide_answers_the_location_question():
    p = policy_of(fact('location', 'Australia-wide'))
    assert p.regions == () and 'location' not in p.open_questions


def test_the_question_text_comes_from_any_evidence_fact(monkeypatch):
    monkeypatch.setattr(intake, 'current_version', lambda person: approved(fact('constraint', 'never in Sydney', fid='n6')))
    q = {x['code']: x for x in describe('fx-a', mode='profile')['open_questions']}
    assert 'never in Sydney' in q['exclusion:n6']['question']


@pytest.mark.parametrize('text,km', [('within 10.5 km of home', 10.5), ('Can travel up to 2.5 km', 2.5),
                                      ('Commute under 30 km. Within 12 km if possible', 12.0)])
def test_decimal_and_sentence_distances(text, km):
    assert policy_of(fact('constraint', text)).max_commute_km == km


def test_a_contracted_negation_ignores_the_level():
    assert policy_of(fact('preference', "I don't want senior roles")).seniority == ()
    assert policy_of(fact('preference', "I don’t want senior roles, junior is fine")).seniority == ('junior',)


def test_a_non_dict_fact_does_not_void_the_policy():
    payload = approved(fact('work_rights', 'Australian citizen'))
    payload['facts'].append('stray')
    p = policy_for('fx-a', approved=payload)
    assert p is not None and p.work_rights['citizen_or_pr'] is True


def test_unknown_work_type_is_an_open_question_not_a_rule():
    p = policy_of(fact('exclusion', {'kind': 'work_type', 'value': 'night shift'}, fid='w1'))
    assert p.exclusions == () and 'exclusion:w1' in p.open_questions
    q = policy_of(fact('exclusion', {'kind': 'work_type', 'value': 'Full-time'}, fid='w2'))
    assert [r.value for r in q.exclusions] == ['full_time']


def test_a_policy_survives_a_json_round_trip():
    p = policy_of(fact('exclusion', {'kind': 'family', 'value': 'retail'}), fact('location', 'I live in Box Hill, VIC'),
                  fact('constraint', 'within 10.5 km of home'))
    assert DecisionPolicy.model_validate(p.model_dump(mode='json')) == p


def test_not_near_a_place_rules_it_out():
    p = policy_of(fact('location', 'I live in Box Hill, VIC'), fact('constraint', 'Not near Sydney', fid='n8'),
                  fact('preference', 'not close to Sydney NSW', fid='n9'))
    assert p.regions == ('VIC',) and 'exclusion:n8' in p.open_questions and 'exclusion:n9' in p.open_questions


def test_not_far_from_the_city_keeps_the_home_region_and_asks_nothing():
    p = policy_of(fact('location', 'I live in Box Hill VIC, not far from the city', fid='n10'))
    assert p.regions == ('VIC',) and not any(q.startswith('exclusion:') for q in p.open_questions)
    q = policy_of(fact('location', 'Box Hill VIC not far from the city', fid='n11'))
    assert q.regions == ('VIC',) and 'exclusion:n11' not in q.open_questions


def test_australia_wide_except_a_place_asks():
    p = policy_of(fact('location', 'Australia-wide except Geelong', fid='n12'))
    assert p.regions == () and 'exclusion:n12' in p.open_questions and 'location' not in p.open_questions


@pytest.mark.parametrize('text', ['Box Hill VIC not far from Melbourne', 'I live in Box Hill VIC, not far from Melbourne',
                                  'Box Hill VIC, not far from Box Hill station'])
def test_not_far_from_a_place_describes_the_area_and_asks_nothing(text):
    p = policy_of(fact('location', text, fid='nf'))
    assert p.regions == ('VIC',) and not any(q.startswith('exclusion:') for q in p.open_questions)


def test_not_far_from_the_city_names_no_region_and_keeps_the_location_question():
    p = policy_of(fact('location', 'not far from the city', fid='nf2'))
    assert p.regions == () and 'location' in p.open_questions and 'exclusion:nf2' not in p.open_questions


@pytest.mark.parametrize('text,asks', [('Box Hill VIC not near Sydney', True), ('Box Hill VIC not near the city', False),
                                       ('Box Hill VIC not close to the station', False), ('Melbourne not near the beach', False),
                                       ('Box Hill VIC, not near Sydney', True), ('I live in Box Hill VIC. Not near Sydney', True)])
def test_not_near_and_not_close_are_clause_boundaries(text, asks):
    p = policy_of(fact('location', text, fid='nn'))
    assert p.regions == ('VIC',) and ('exclusion:nn' in p.open_questions) is asks


def test_not_near_a_place_with_no_home_gives_no_region():
    p = policy_of(fact('location', 'Not near Sydney', fid='nn2'))
    assert p.regions == () and 'exclusion:nn2' in p.open_questions


@pytest.mark.parametrize('text', ['I live in Box Hill VIC not near Sydney', 'I live in Box Hill VIC, not near Sydney',
                                  'I live in Box Hill VIC not close to the station'])
def test_home_state_ignores_a_not_near_tail(text):
    p = policy_of(fact('location', text))
    assert p.home['state'] == 'VIC' and p.home['place'] == 'Box Hill VIC' and p.regions == ('VIC',)


# ----------------------------------------------------------------------------- built-in excluded codes are a parameter
# Both literals were recorded from a run of the unmodified code (before require_minimum_excluded_codes existed):
#   digest(default_policy().model_dump(mode='json'))                       -> PINNED_DEFAULT_POLICY_DIGEST
#   service._run_key(42, capture, bundle, default_policy(), cfg, inputs)   -> PINNED_DEFAULT_RUN_KEY (synthetic world, posting 42)
PINNED_DEFAULT_POLICY_DIGEST = '42863f98ea5a76eac285d186c501bc9fc7c1c865f1e2200698a216b9409c5a90'
PINNED_DEFAULT_RUN_KEY = {
    'posting_id': 42,
    'ad_hash': '6a0ef7f9cd759ac44697456e44aa2993280c7b5995ac046c74a43f2b4aaaa2b9',
    'evidence_hash': 'e6955150e8f1870037c9bfa3ed39625b48f5bdee1adec0096107f671db704297',
    'rubric_version': 'career-ops-v1',
    'config_hash': '7ad3ec7bc7535f12faedfb7bf6097822514568d03c7c9936c45619ab1edb515f',
    'candidate_hash': '84be033aff69ab506d631bc5a3d274705eea669a65fd01bbea815435f70f49bd',
}


def test_default_policy_json_and_hash_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path))     # no person file: the default families are every known family
    dumped = default_policy().model_dump(mode='json')
    assert 'require_minimum_excluded_codes' not in dumped and dumped['excluded_codes'] == ['431111', '541211']
    assert digest(dumped) == PINNED_DEFAULT_POLICY_DIGEST


def test_minimum_excluded_codes_stay_the_legacy_default_and_stay_immutable_there():
    assert MINIMUM_EXCLUDED_CODES == ('431111', '541211') and TargetPolicy(version='v1', allowed_families=('accounting',)).excluded_codes == MINIMUM_EXCLUDED_CODES
    with pytest.raises(ValidationError):
        TargetPolicy(version='v1', allowed_families=('accounting',), excluded_codes=('999999',))
    with pytest.raises(ValidationError):
        TargetPolicy(version='v1', allowed_families=('accounting',), excluded_codes=('431111',), require_minimum_excluded_codes=True)


def test_dropping_the_minimum_needs_the_explicit_flag_and_still_checks_the_codes():
    p = TargetPolicy(version='v1', allowed_families=('accounting',), excluded_codes=('999999',), require_minimum_excluded_codes=False)
    assert p.excluded_codes == ('999999',) and p.model_dump(mode='json')['require_minimum_excluded_codes'] is False
    with pytest.raises(ValidationError):
        TargetPolicy(version='v1', allowed_families=('accounting',), excluded_codes=('99',), require_minimum_excluded_codes=False)
    assert TargetPolicy.model_validate(p.model_dump(mode='json')) == p        # the flag survives a round trip


def test_profile_target_policy_is_person_independent_and_drops_the_minimum():
    p = profile_target_policy()
    assert p.excluded_codes == () and p.allowed_families == KNOWN_FAMILIES and p.model_dump(mode='json')['require_minimum_excluded_codes'] is False
    assert p.version == 'profile-neutral-v1'
    assert p == profile_target_policy()                             # no profile read: identical for every person


def _person_who_excludes(tmp_path, monkeypatch, name, *families):
    """A synthetic profile dir whose interests file lists `families` as excluded_families, made the current profile."""
    d = tmp_path / name
    d.mkdir()
    (d / 'interests_and_criteria.yaml').write_text('target_roles:\n  excluded_families: [' + ', '.join(families) + ']\n')
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(d))


def test_profile_target_policy_builds_for_a_person_who_excludes_a_family_and_is_equal_across_people(tmp_path, monkeypatch):
    _person_who_excludes(tmp_path, monkeypatch, 'one', 'retail', 'hospitality')
    first = profile_target_policy()
    _person_who_excludes(tmp_path, monkeypatch, 'two', 'engineering')
    second = profile_target_policy()
    assert first.allowed_families == KNOWN_FAMILIES and 'retail' in first.allowed_families
    assert first == second and first.model_dump(mode='json') == second.model_dump(mode='json')


def test_a_default_policy_still_rejects_a_family_the_person_excludes(tmp_path, monkeypatch):
    _person_who_excludes(tmp_path, monkeypatch, 'three', 'retail')
    with pytest.raises(ValidationError, match='not_wanted'):
        TargetPolicy(version='v1', allowed_families=('accounting', 'retail'))
    with pytest.raises(ValidationError, match='not_wanted'):
        TargetPolicy(version='v1', allowed_families=('accounting', 'Retail'), require_minimum_excluded_codes=True)
    assert 'retail' not in default_policy().allowed_families           # the default projection still drops it


def test_run_key_for_the_default_policy_is_unchanged(world):
    from pipeline.agentic import service
    conn, config, bundle, add = world
    add(42)
    cfg = service._config(config)
    inputs = service.load_inputs(bundle, cfg)
    key = service._run_key(42, service._capture(conn, 42), bundle, default_policy(), cfg, inputs)
    assert key.model_dump(mode='json') == PINNED_DEFAULT_RUN_KEY
