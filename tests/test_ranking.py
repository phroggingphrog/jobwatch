"""Ranking conventions, deterministic order and evidence provenance boundaries."""
from dataclasses import replace

import pytest

from pipeline.agentic.ranking import (
    Scored, ShortlistEntry, candidate_status, coverage, exclusion_reason, explain,
    label_for, rank_candidates,
)
from tests.ranking_support import make_evaluation, policy_stub, relevance_stub


def test_partial_unknown_bounds_and_gap_kinds():
    cov = coverage(make_evaluation([('r1','high','partial'),('r2','high','unknown')]))
    assert (cov.weight_total, cov.weighted, cov.weighted_upper, cov.unresolved_share) == (6, .25, .75, .5)
    assert cov.real_gaps == ('r1',) and cov.missing_documentation == ('r2',) and cov.conflicts == ()


def test_all_weights_and_credit_are_importance_based_not_holistic_score():
    spec = [('c','critical','demonstrated'),('h','high','partial'),('m','meaningful','unknown'),
            ('p','preferred','contradicted'),('l','low_signal','unknown')]
    low = coverage(make_evaluation(spec, score=1., north_star=1.))
    high = coverage(make_evaluation(spec, score=5., north_star=5.))
    assert low == high
    assert (low.weight_total, low.weighted, low.weighted_upper, low.unresolved_share) == (10, .55, .75, .2)
    assert (low.demonstrated, low.partial, low.unknown, low.contradicted) == (1,1,2,1)
    assert low.conflicts == ('p',) and low.missing_documentation == ('m',)


def test_historical_status_mapping_keeps_missing_unknown_and_supported_matches():
    cov = coverage(make_evaluation([('r1','high','unknown'),('r2','meaningful','partial'),
        ('r3','meaningful','demonstrated')], legacy=('r1','r2','r3')))
    assert (cov.unknown, cov.partial, cov.demonstrated, cov.without_judgment) == (1,1,1,3)
    assert cov.missing_documentation == ('r1',) and cov.real_gaps == ('r2',) and not cov.conflicts


def test_mandatory_lists_and_order_do_not_depend_on_requirement_order():
    spec = [('r1','critical','demonstrated'),('r2','critical','unknown'),
            ('r3','meaningful','partial'),('r4','high','contradicted')]
    cov = coverage(make_evaluation(spec, blockers=('r3','r4')))
    assert cov == coverage(make_evaluation(list(reversed(spec)), blockers=('r3','r4')))
    assert cov.mandatory_unmet == ('r2','r4','r3')
    assert cov.mandatory_unknown == ('r2',) and cov.mandatory_partial == ('r3',)
    assert cov.mandatory_conflicts == ('r4',)
    assert exclusion_reason(cov) == 'mandatory_conflict'


@pytest.mark.parametrize('spec', [[], [('r','low_signal','unknown')], [('r','preferred','not_applicable')]])
def test_no_weight_is_clarification_without_division_by_zero(spec):
    cov = coverage(make_evaluation(spec))
    assert (cov.weight_total,cov.weighted,cov.weighted_upper,cov.unresolved_share) == (0,0.,0.,0.)
    assert label_for(cov,None,policy_stub()) == 'needs_clarification'


@pytest.mark.parametrize(('spec','blockers','expected'), [
    ([('r1','critical','unknown'),('r2','high','unknown')], (), 'needs_clarification'),
    ([('r1','meaningful','demonstrated'),('r2','preferred','unknown')], (), 'stronger_match'),
    ([('r1','preferred','demonstrated'),('r2','meaningful','unknown')], (), 'needs_clarification'),
    ([('r1','high','demonstrated'),('r2','preferred','unknown')], ('r2',), 'needs_clarification'),
    ([('r1','high','demonstrated'),('r2','preferred','partial')], ('r2',), 'stretch'),
    ([('r1','high','demonstrated'),('r2','preferred','contradicted')], (), 'stretch'),
    ([('r1','high','partial')], (), 'stretch'),
])
def test_label_boundaries_and_mandatory_rules(spec,blockers,expected):
    assert label_for(coverage(make_evaluation(spec,blockers=blockers)),None,policy_stub()) == expected


def test_held_or_uncertain_career_focus_needs_clarification():
    cov = coverage(make_evaluation([('r','high','demonstrated')]))
    assert label_for(cov,None,policy_stub(),held=True) == 'needs_clarification'
    assert label_for(cov,relevance_stub('uncertain'),policy_stub()) == 'stronger_match'
    assert label_for(cov,'uncertain',policy_stub('career_focus')) == 'needs_clarification'
    assert label_for(cov,'uncertain',policy_stub('balanced')) == 'needs_clarification'
    assert exclusion_reason(cov,'no') == 'relevance_no'
    assert exclusion_reason(cov,None) is None


@pytest.mark.parametrize(('route','reason','expected'), [
    ('draft','eligible','eligible'),('hold','insufficient_evidence','held'),
    ('hold','verification_required',None),('archive','hard_gate',None),
    ('archive','policy_excluded',None),('archive','score_below_threshold',None),
])
def test_only_actionable_current_gate_results_enter_pool(route,reason,expected):
    assert candidate_status(route,reason) == expected


def scored(case_id, spec=None, **kwargs):
    cov = coverage(make_evaluation(spec or [('r','high','demonstrated')]))
    return Scored(case_id,cov,'yes',kwargs.pop('label','stronger_match'),**kwargs)


def ids(rows):
    return [r.case_id for r in rows]


def test_provisional_uses_tier_coverage_upper_similarity_then_numeric_posting_id():
    rows = [scored('10'),scored('2'),scored('3',similarity=.9),
            scored('1',label='stretch'),scored('0',label='needs_clarification')]
    ranked = rank_candidates(rows)
    assert ids(ranked) == ['3','2','10','1','0']
    assert ids(rank_candidates(list(reversed(rows)))) == ids(ranked)
    assert all(r.ordering == 'provisional' for r in ranked)
    assert [r.rank for r in ranked] == [1,2,3,4,5]
    a = scored('a', posting_id=20)
    b = scored('z', posting_id=3)
    assert ids(rank_candidates([a,b])) == ['z','a']


def test_coverage_then_upper_then_similarity_precede_id():
    rows = [scored('1',[('a','high','partial'),('b','preferred','demonstrated')],similarity=1),
            scored('2',[('a','meaningful','demonstrated'),('b','meaningful','unknown')]),
            scored('3',[('a','meaningful','demonstrated'),('b','meaningful','partial')])]
    assert ids(rank_candidates(rows)) == ['3','1','2']  # .75, .625, .5
    lower = scored('1',[('a','meaningful','partial'),('b','meaningful','demonstrated')])
    upper = scored('2',[('a','high','demonstrated'),('b','preferred','unknown')])
    assert ids(rank_candidates([lower,upper])) == ['2','1']  # .75 tied, upper 1 > .75


def test_focus_only_breaks_ties_when_requested_and_relevant():
    rows = [scored('1'),scored('2',focus_match=True)]
    assert ids(rank_candidates(rows)) == ['1','2']
    assert ids(rank_candidates(rows,strategy='career_focus')) == ['2','1']
    assert ids(rank_candidates([rows[0],replace(rows[1],relevance='uncertain')],strategy='career_focus')) == ['1','2']


def test_personalised_utilities_reorder_only_within_label_tiers():
    rows = [scored('1'),scored('2'),scored('3',label='stretch')]
    ranked = rank_candidates(rows,utilities={'1':0.,'2':1.,'3':100.})
    assert ids(ranked) == ['2','1','3'] and all(r.ordering == 'personalised' for r in ranked)


@pytest.mark.parametrize('utilities', [{'1':1.}, {'1':1.,'2':float('nan')},
    {'1':1.,'2':float('inf')}, {'1':1.,'2':None}])
def test_incomplete_or_invalid_utilities_make_whole_list_provisional(utilities):
    ranked = rank_candidates([scored('1'),scored('2')], utilities=utilities, answered=7)
    assert ids(ranked) == ['1','2'] and all(r.ordering == 'provisional' for r in ranked)
    assert '7 of 25' in ranked[0].uncertainty
    assert '1.00' in ranked[0].rank_reason and 'provisional' in ranked[0].rank_reason


def explanation(ev, *, policy=None, facts=(), relevance=None):
    cov = coverage(ev)
    return explain(ev,cov,label_for(cov,relevance,policy or policy_stub()),
        policy=policy or policy_stub(), relevance=relevance, approved_facts=facts)


def test_explanation_orders_exact_frozen_citations_and_omits_unknowns():
    ev = make_evaluation([('p','preferred','partial'),('u','critical','unknown'),('h','high','demonstrated')])
    result = explanation(ev)
    assert [r['requirement_id'] for r in result['evidence']] == ['h','p']
    assert result['evidence'][0]['citations'] == [ev.matches[2].evidence[0].model_dump(mode='json')]
    assert 'Requirement u [unknown]' in result['mandatory_requirements']
    assert 'Can you clarify u?' in result['unresolved']


def test_transferable_evidence_requires_exact_link_to_existing_support_not_word_overlap_or_inference():
    ev = make_evaluation([('r','high','partial')])
    quote = ev.matches[0].evidence[0].quote
    facts = [
        {'id':'supported','section':'transferable_skill','basis':'evidence','value':'Report preparation',
         'sources':[{'upload_sha256':'a'*64,'line':1,'quote':quote}]},
        {'id':'overlap','section':'transferable_skill','basis':'evidence','value':'Requirement reporting'},
        {'id':'inferred','section':'transferable_skill','basis':'inference','value':'Inferred expertise',
         'sources':[{'quote':quote}]},
        {'id':'unknown','section':'transferable_skill','basis':'unknown','value':'Unknown expertise'},
        {'id':'wrongsection','section':'skill','basis':'evidence','value':'Something','sources':[{'quote':quote}]},
    ]
    result = explanation(ev,facts=facts)
    assert result['transferable_skills'] == ['Report preparation']
    assert any('Inferred expertise' in q for q in result['unresolved'])
    assert all('Inferred expertise' not in str(e) for e in result['evidence'])
    # Contradictions and unknowns cannot be used as positive transferable support.
    assert explanation(make_evaluation([('r','high','contradicted')]),facts=facts)['transferable_skills'] == []


def test_ad_conditions_are_descriptive_and_location_uses_quote_not_legacy_label():
    ev = make_evaluation([('r','high','demonstrated')])
    from pipeline.agentic.contracts import SourceCitation
    ev = ev.model_copy(update={'location_fit':'melbourne','location_evidence':SourceCitation(
        source_id='ad',content_hash=ev.run_key.ad_hash,quote='Sydney NSW')})
    policy = policy_stub('career_focus',focus=('Public reporting',))
    policy.regions = ('NSW',)
    result = explanation(ev,policy=policy,relevance=relevance_stub(matched=('Public reporting',)))
    assert any('Sydney NSW' in c and 'in your area' in c for c in result['conditions'])
    assert not any('Melbourne' in c for c in result['conditions'])
    assert any('part_time_ok' in c for c in result['conditions'])
    assert any('junior' in c and '1' in c for c in result['conditions'])
    assert any('rights' in c.lower() for c in result['conditions'])
    assert 'career focus' in result['objective_fit'] and 'Public reporting' in result['objective_fit']
    assert '1.00' in result['objective_fit']


def test_no_facts_gain_default_focus_and_missing_inputs_stay_questions():
    result = explanation(make_evaluation([],hours='unstated'),policy=policy_stub(open_questions=('career_focus',)))
    assert 'employment-first' in result['objective_fit']
    assert any('hours' in q.lower() for q in result['unresolved'])
    assert any('location' in q.lower() for q in result['unresolved'])
    assert any('career_focus' in q for q in result['unresolved'])
    assert 'accounting' not in str(result).lower()


def test_shortlist_entry_preserves_explanation_and_detail_as_json():
    ev = make_evaluation([('r','high','demonstrated')])
    entry = ShortlistEntry(entry_id='entry',shortlist_id='list',posting_id=1,
        run_key=ev.run_key.value,profile_version=1,label='stronger_match',rank=1,
        rank_reason='Synthetic rank.',ordering='provisional',uncertainty='Unfitted.',
        holistic_score=1.,created_at='2026-10-22T00:00:00Z',posting={'title':'Synthetic'},
        coverage=coverage(ev).model_dump(mode='json'), requirements=(),**explanation(ev))
    serialized = entry.model_dump(mode='json')
    assert serialized['evidence'][0]['citations'][0]['quote'] == 'Approved primary evidence for r.'
    assert serialized['holistic_score'] == 1. and serialized['utility'] is None


def test_explanation_caps_evidence_at_six_in_weight_and_id_order():
    ev = make_evaluation([('z','preferred','partial'),('g','high','demonstrated'),
        ('f','high','demonstrated'),('e','high','demonstrated'),('d','high','demonstrated'),
        ('c','high','demonstrated'),('b','high','demonstrated'),('a','high','demonstrated')])
    result = explanation(ev)
    assert [r['requirement_id'] for r in result['evidence']] == ['a','b','c','d','e','f']


def test_missing_years_and_uncertain_legitimacy_remain_visible_questions():
    ev = make_evaluation([('r','high','demonstrated')])
    ev = ev.model_copy(update={'facts':ev.facts.model_copy(update={'min_years':None}),
                               'legitimacy':'uncertain'})
    result = explanation(ev)
    assert any('years' in q.lower() for q in result['unresolved'])
    assert any('legitimacy' in q.lower() for q in result['unresolved'])


def test_unclear_location_quote_is_not_in_area_even_with_legacy_label():
    from pipeline.agentic.contracts import SourceCitation
    ev = make_evaluation([('r','high','demonstrated')])
    ev = ev.model_copy(update={'location_fit':'melbourne','location_evidence':SourceCitation(
        source_id='ad',content_hash=ev.run_key.ad_hash,quote='Level 3, 1 Example St')})
    policy = policy_stub()
    policy.regions = ('NSW',)
    result = explanation(ev,policy=policy)
    assert any('Location not stated' in c for c in result['conditions'])
    assert not any('in your area' in c for c in result['conditions'])


def test_unknown_match_citations_cannot_link_a_transferable_skill():
    ev = make_evaluation([('r','high','unknown')])
    from pipeline.agentic.contracts import SourceCitation
    citation = SourceCitation(source_id='master_resume.md',content_hash='a'*64,quote='A whole approved skill quote')
    ev = ev.model_copy(update={'matches':(ev.matches[0].model_copy(update={'evidence':(citation,)}),)})
    fact = {'id':'skill','section':'transferable_skill','basis':'evidence',
        'value':'Reporting', 'sources':[{'quote':citation.quote}]}
    result = explanation(ev,facts=[fact])
    assert result['evidence'] == [] and result['transferable_skills'] == []


def test_empty_ranking_and_invalid_similarity_are_deterministic():
    assert rank_candidates([],utilities={}) == []
    assert ids(rank_candidates([scored('2',similarity=float('nan')),scored('1',similarity=0.)])) == ['1','2']


def test_transferable_quote_uses_canonical_profile_projection_whitespace():
    from hashlib import sha256
    from jobwatch.candidate.projection import project
    from pipeline.agentic.contracts import AgenticEvaluation, SourceCitation

    fact = {'id':'multiline','section':'transferable_skill','basis':'evidence',
        'value':'Reporting across teams','sources':[{'upload_sha256':'a'*64,'line':1,
        'quote':'Built cross-team dashboards\n    for weekly reporting.'}]}
    canonical = project({'facts':[fact]})['master_resume.md']
    quote = 'Built cross-team dashboards for weekly reporting.'
    assert quote in canonical
    ev = make_evaluation([('r','high','partial')])
    citation = SourceCitation(source_id='master_resume.md',
        content_hash=sha256(canonical.encode()).hexdigest(),quote=quote)
    ev = AgenticEvaluation.model_validate(ev.model_copy(update={
        'matches':(ev.matches[0].model_copy(update={'evidence':(citation,)}),)
    }).model_dump())
    result = explanation(ev,facts=[fact])
    assert result['transferable_skills'] == ['Reporting across teams']
    assert result['evidence'][0]['citations'][0] == citation.model_dump(mode='json')
    # Projection normalization cannot turn a paraphrase into exact evidence.
    altered = {**fact,'sources':[{**fact['sources'][0],
        'quote':'Built dashboards across teams for weekly reporting.'}]}
    assert explanation(ev,facts=[altered])['transferable_skills'] == []


@pytest.mark.parametrize('quote', ['Location to be advised', 'Level 3, 1 Example St'])
def test_unstated_location_stays_question_without_confirmed_region_restrictions(quote):
    from pipeline.agentic.contracts import SourceCitation
    ev = make_evaluation([('r','high','demonstrated')])
    citation = SourceCitation(source_id='ad',content_hash=ev.run_key.ad_hash,quote=quote)
    ev = ev.model_copy(update={'location_fit':'melbourne','location_evidence':citation})
    result = explanation(ev,policy=policy_stub())
    assert 'What is the job location?' in result['unresolved']
    assert f'Location not stated clearly: {quote}' in result['conditions']
    assert not any('no confirmed region restriction' in c for c in result['conditions'])
    assert ev.location_evidence == citation


def test_structured_person_skill_links_using_canonical_projection_field_order():
    from hashlib import sha256
    from jobwatch.candidate.projection import project
    from pipeline.agentic.contracts import AgenticEvaluation, SourceCitation

    fact = {'id':'structured','section':'transferable_skill','basis':'evidence',
        'actor':'person','sources':[],
        'value':{'skill':'Report preparation','context':'Weekly reports'}}
    canonical = project({'facts':[fact]})['master_resume.md']
    quote = 'Report preparation, Weekly reports'
    assert quote in canonical
    ev = make_evaluation([('r','high','partial')])
    citation = SourceCitation(source_id='master_resume.md',
        content_hash=sha256(canonical.encode()).hexdigest(),quote=quote)
    ev = AgenticEvaluation.model_validate(ev.model_copy(update={
        'matches':(ev.matches[0].model_copy(update={'evidence':(citation,)}),)
    }).model_dump())
    result = explanation(ev,facts=[fact])
    assert len(result['transferable_skills']) == 1
    assert set(result['transferable_skills'][0].split(', ')) == {'Report preparation','Weekly reports'}
    assert result['evidence'][0]['citations'][0] == citation.model_dump(mode='json')
