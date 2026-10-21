
from jobwatch import model_choice
from jobwatch.settings import DEFAULT_MODEL
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from jobwatch.candidate.evidence import snapshot_evidence
from pipeline.agentic.contracts import AgenticError
from pipeline.agentic.interview import (AUDIENCES, CRITERIA, PACK_TOPICS, PROCESS_TOPICS, SECTIONS,
    InterviewProposal, InterviewReport, prepare_interview, validate_report)
from pipeline.agentic.runtime import BatchBudget, JobBudget, validate_model_payload, RuntimeErrorSafe


def proposal(bundle=None, ad_text='Reconcile accounts using SQL.'):
    sections = []
    for key in SECTIONS:
        topics = PROCESS_TOPICS if key == 'process' else PACK_TOPICS.get(key, (key,))
        items = [{'topic': topic, 'text': 'Unknown — not enough data.', 'kind': 'unknown',
                  'audience': key if key in AUDIENCES else None} for topic in topics]
        if key in ('story_bank', 'company_signals'):
            items = [{'topic': key, 'text': 'Unknown — source unavailable.', 'kind': 'unknown', 'audience': a} for a in AUDIENCES]
        sections.append({'key': key, 'title': key, 'items': items})
    if bundle is not None:
        from jobwatch.candidate.contracts import content_hash
        ad = ad_text
        evidence = bundle.items[0]
        for audience, question in (
                ('recruiter-screen', 'Why are you interested in accounts reconciliation?'),
                ('hiring-manager', 'How would you approach reconciliation in your first month?'),
                ('peer-tech', 'How would you reconcile accounts using SQL?')):
            item = next(s for s in sections if s['key'] == audience)['items'][0]
            item.update(kind='jd_inference', text='Practise a role-specific reconciliation answer.',
                        question=question, citations=[{'source_id':'ad',
                        'content_hash':content_hash(ad.encode()), 'quote':ad}])
        item['answer'] = {'headline':'I reconciled ledgers.', 'effect':'The ledgers were reconciled.',
                          'rationale':'Explain the actual constraints; these are not recorded.',
                          'operations':'Explain the actual steps; these are not recorded.'}
        item['answer_citations'] = [{'source_id':evidence.source_file,
                                    'content_hash':evidence.source_hash, 'quote':evidence.quote}]
    return {'sections': sections}


class Writer:
    base_url = model_choice.SERVER_URL
    def __init__(self, bundle, payload=None, skip_read=False):
        self.bundle, self.payload, self.skip_read = bundle, payload or proposal(bundle), skip_read
        self.calls = []
    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages))
        if len(self.calls) % 2 and not self.skip_read:
            data = {'tool': 'read_candidate_evidence', 'arguments': {'evidence_ids': [self.bundle.items[0].id]}}
        else:
            data = {'tool': 'complete_interview', 'arguments': self.payload}
        return SimpleNamespace(data=data, usage={'prompt_tokens': 10, 'completion_tokens': 10})


class Reviewer:
    base_url = model_choice.SERVER_URL
    def __init__(self, verdicts=('approve',), bad_hash=False, missing=False):
        self.verdicts, self.bad_hash, self.missing = iter(verdicts), bad_hash, missing
        self.calls = []
    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages))
        ctx = json.loads(messages[-1]['content'])
        data = {'sources_hash': ctx['sources_hash'], 'draft_hash': '0'*64 if self.bad_hash else ctx['draft_hash'], 'verdict': next(self.verdicts),
                'criteria': [{'name': k, 'passed': True} for k in (CRITERIA[:-1] if self.missing else CRITERIA)],
                'feedback': ['Add a grounded company signal.']}
        return SimpleNamespace(data={'tool': 'complete_review', 'arguments': data}, usage={'prompt_tokens': 10, 'completion_tokens': 10})


@pytest.fixture
def case(tmp_path):
    (tmp_path/'cv.md').write_text('# Synthetic Candidate\n\n## Skills\n- Reconciled ledgers.\n')
    bundle = snapshot_evidence(tmp_path)
    return bundle, {'company': 'Synthetic', 'title': 'Accounts assistant'}, JobBudget('a'*64, BatchBudget('interview'), token_ceiling=300000)


def prepare(case, writer=None, reviewer=None):
    bundle, context, budget = case
    return prepare_interview(context, 'Reconcile accounts using SQL.', bundle, budget, writer or Writer(bundle), reviewer or Reviewer())


def test_real_deep_agents_tools_independent_review_and_roundtrip(case):
    writer, reviewer = Writer(case[0]), Reviewer()
    report = prepare(case, writer, reviewer)
    assert report.review.draft_hash == report.proposal.draft_hash
    assert [m for m, _ in writer.calls] == [DEFAULT_MODEL]*2  # owner 2026-10-19: no Claude subscription
    assert reviewer.calls[0][0] == DEFAULT_MODEL
    assert case[2].charged_tokens == 60
    ctx = json.loads(reviewer.calls[0][1][-1]['content'])
    assert 'previous_proposal' not in ctx and 'review_feedback' not in ctx
    restored = validate_model_payload(InterviewReport, json.loads(report.model_dump_json()))
    assert validate_report(restored, case[1], 'Reconcile accounts using SQL.', case[0]) == report


@pytest.mark.parametrize('mode', ['hash', 'criteria', 'reject', 'read'])
def test_failure_never_publishes(case, mode):
    with pytest.raises(AgenticError):
        prepare(case, Writer(case[0], skip_read=mode == 'read'), Reviewer(
            bad_hash=mode == 'hash', missing=mode == 'criteria', verdicts=('reject',) if mode == 'reject' else ('approve',)))


def test_one_bounded_revision(case):
    writer, reviewer = Writer(case[0]), Reviewer(('revise', 'approve'))
    assert prepare(case, writer, reviewer).review.verdict == 'approve'
    assert len(writer.calls) == 4 and len(reviewer.calls) == 2
    assert json.loads(writer.calls[2][1][-1]['content'])['review_feedback'] == ['Add a grounded company signal.']


def test_repeated_revision_fails(case):
    with pytest.raises(AgenticError, match='interview_review_not_accepted'):
        prepare(case, reviewer=Reviewer(('revise', 'revise')))


def test_optional_inputs_captured_and_source_changes_rejected(case):
    for name in ('invite', 'panelist_profiles', 'story_bank', 'prior_compensation', 'coffee_chat', 'prior_round_notes', 'evaluation'):
        case[1][name] = 'Synthetic optional note'
    report = prepare(case)
    assert {s.source_id for s in report.sources} >= set(case[1]) - {'company', 'title'}
    case[1]['invite'] = 'Changed'
    with pytest.raises(AgenticError):
        validate_report(report, case[1], 'Reconcile accounts using SQL.', case[0])


def test_full_coverage_and_technical_cap():
    payload = proposal()
    payload['sections'].pop()
    with pytest.raises(RuntimeErrorSafe): validate_model_payload(InterviewProposal, payload)
    payload = proposal()
    next(s for s in payload['sections'] if s['key'] == 'technical_prep')['items'] *= 11
    with pytest.raises(RuntimeErrorSafe): validate_model_payload(InterviewProposal, payload)


def test_primary_candidate_proof_and_invite_modality(case):
    from pipeline.agentic.interview import source_map, validate_proposal
    sources = source_map(case[1], 'Reconcile accounts using SQL.', case[0])
    ad = sources['ad']
    cite = {'source_id': 'ad', 'content_hash': ad.content_hash, 'quote': ad.text}
    for topic, kind in [('platform', 'reported'), ('modality', 'inference')]:
        payload = proposal(case[0])
        item = next(i for i in payload['sections'][0]['items'] if i['topic'] == topic)
        item.update(kind=kind, text='AI interview.', citations=[cite])
        p = validate_model_payload(InterviewProposal, payload)
        with pytest.raises(AgenticError, match='interview_platform_requires_invite'):
            validate_proposal(p, sources, case[0])
    payload = proposal(case[0])
    payload['sections'][-1]['items'][0].update(kind='candidate', text='I used SQL.', citations=[cite])
    with pytest.raises(AgenticError):
        validate_proposal(validate_model_payload(InterviewProposal, payload), sources, case[0])


def test_deeply_immutable_report(case):
    report = prepare(case)
    with pytest.raises(ValidationError): report.review.criteria[0].passed = False
    with pytest.raises(ValidationError): report.sources[0].text = 'changed'


def test_public_tools_expose_only_fixed_intents_and_preserve_snapshots(case):
    from pipeline.agentic.research import ResearchIntent, ResearchResult, ResearchPage
    from pipeline.agentic.interview import validate_proposal
    seen = []
    class Research:
        def search(self, intent):
            seen.append(intent)
            assert type(intent) is ResearchIntent
            return (ResearchResult('r1', 'Public interview report', 'https://example.org/interview'),)
        def fetch(self, result_id):
            assert result_id == 'r1'
            return ResearchPage('r1', 'They asked: How do you reconcile a ledger?')
    class ResearchWriter(Writer):
        base_url = model_choice.SERVER_URL
        def chat_once(self, model, messages, **kwargs):
            self.calls.append((model, messages))
            n = len(self.calls)
            if n == 1:
                data = {'tool': 'read_candidate_evidence', 'arguments': {'evidence_ids': [self.bundle.items[0].id]}}
            elif n == 2:
                data = {'tool': 'search_public', 'arguments': {'intent': 'interview_questions'}}
            elif n == 3:
                data = {'tool': 'fetch_public', 'arguments': {'result_id': 'r1'}}
            else:
                data = {'tool': 'complete_interview', 'arguments': self.payload}
            return SimpleNamespace(data=data, usage={'prompt_tokens': 10, 'completion_tokens': 10})
    case[1]['panelist_profiles'] = 'Synthetic private panelist note, never a search parameter'
    report = prepare_interview(case[1], 'Reconcile accounts using SQL.', case[0], case[2], ResearchWriter(case[0]), Reviewer(), research=Research())
    assert seen == [ResearchIntent.INTERVIEW_QUESTIONS]
    public = next(s for s in report.sources if s.kind == 'research')
    assert public.url == 'https://example.org/interview' and public.accessed_at
    assert validate_report(report, case[1], 'Reconcile accounts using SQL.', case[0]) == report
    payload = proposal(case[0])
    payload['sections'][-1]['items'][0].update(kind='reported', text='Reported question',
        question='Invented systems design question?', citations=[{'source_id': public.source_id,
        'content_hash': public.content_hash, 'quote': public.text}])
    with pytest.raises(AgenticError, match='interview_question_not_reported'):
        validate_proposal(validate_model_payload(InterviewProposal, payload), {s.source_id:s for s in report.sources}, case[0])


def test_grounded_result_first_answer(case):
    from pipeline.agentic.interview import source_map, validate_proposal
    sources = source_map(case[1], 'Reconcile accounts using SQL.', case[0])
    evidence = case[0].items[0]
    payload = proposal(case[0])
    item = next(s for s in payload['sections'] if s['key'] == 'peer-tech')['items'][0]
    item.update(kind='jd_inference', text='Practise explaining your reconciliation method.',
        question='How would you reconcile the accounts?', citations=[{'source_id':'ad',
        'content_hash':sources['ad'].content_hash, 'quote':sources['ad'].text}],
        answer={'headline':'I reconciled ledgers.', 'effect':'The ledgers were reconciled.',
                'rationale':'Describe your actual constraints; these are not recorded.',
                'operations':'Describe your actual steps; these are not recorded.'},
        answer_citations=[{'source_id':evidence.source_file, 'content_hash':evidence.source_hash, 'quote':evidence.quote}])
    assert validate_proposal(validate_model_payload(InterviewProposal, payload), sources, case[0])


def test_source_metadata_is_bound_to_independent_review(case):
    report = prepare(case)
    changed = report.sources[0].model_copy(update={'accessed_at': '2099-01-01'})
    tampered = report.model_copy(update={'sources': (changed,) + report.sources[1:]})
    with pytest.raises(AgenticError, match='invalid_interview_artifact'):
        validate_report(tampered, case[1], 'Reconcile accounts using SQL.', case[0])


def test_all_unknown_report_rejected_before_shallow_approval(case):
    reviewer = Reviewer()
    with pytest.raises(AgenticError, match='interview_grounded_questions_required'):
        prepare(case, Writer(case[0], proposal()), reviewer)
    assert reviewer.calls == []


def test_primary_answer_required_even_when_questions_present(case):
    payload = proposal(case[0])
    for section in payload['sections']:
        for item in section['items']:
            item.pop('answer', None)
            item.pop('answer_citations', None)
    with pytest.raises(AgenticError, match='interview_primary_answer_required'):
        prepare(case, Writer(case[0], payload))


@pytest.mark.parametrize('audience', ['recruiter-screen', 'hiring-manager', 'peer-tech'])
def test_each_main_audience_requires_a_grounded_question(case, audience):
    payload = proposal(case[0])
    section = next(s for s in payload['sections'] if s['key'] == audience)
    for item in section['items']:
        item.pop('question', None)
        item.pop('answer', None)
        item.pop('answer_citations', None)
    with pytest.raises(AgenticError, match='interview_grounded_questions_required'):
        prepare(case, Writer(case[0], payload))


def owner_logistics_payload(case):
    from jobwatch.candidate.contracts import content_hash
    case[1]['prior_compensation'] = 'Previously stated expectation: 70000.'
    payload = proposal(case[0])
    item = next(s for s in payload['sections'] if s['key'] == 'recruiter-screen')['items'][1]
    item.update(kind='jd_inference', question='What compensation have you already discussed?',
                text='Keep the previously stated expectation consistent.',
                citations=[{'source_id':'ad', 'content_hash':content_hash(b'Reconcile accounts using SQL.'),
                            'quote':'Reconcile accounts using SQL.'}],
                answer_grounding='owner_fact',
                answer={'headline':'I previously stated 70000.', 'effect':'Keeps this discussion consistent.',
                        'rationale':'This was already stated.', 'operations':'Refer to the earlier discussion.'},
                answer_citations=[{'source_id':'prior_compensation',
                    'content_hash':content_hash(case[1]['prior_compensation'].encode()),
                    'quote':case[1]['prior_compensation']}])
    return payload


def test_explicit_owner_logistics_answer_accepted(case):
    payload = owner_logistics_payload(case)
    report = prepare(case, Writer(case[0], payload))
    assert any(i.answer_grounding == 'owner_fact' for s in report.proposal.sections for i in s.items)


def test_owner_fact_cannot_ground_experience_answer(case):
    payload = owner_logistics_payload(case)
    item = next(s for s in payload['sections'] if s['key'] == 'recruiter-screen')['items'][1]
    item['topic'] = 'narrative'
    # Keep required pack topic coverage while adding the attempted unsupported experience answer.
    next(s for s in payload['sections'] if s['key'] == 'recruiter-screen')['items'].append(
        {'topic':'compensation', 'text':'Unavailable.', 'kind':'unknown', 'audience':'recruiter-screen'})
    with pytest.raises(AgenticError, match='interview_owner_answer_not_logistics'):
        prepare(case, Writer(case[0], payload))


def test_owner_fact_cannot_replace_primary_answer_minimum(case):
    payload = owner_logistics_payload(case)
    for section in payload['sections']:
        for item in section['items']:
            if item.get('answer_grounding', 'primary') == 'primary':
                item.pop('answer', None)
                item.pop('answer_citations', None)
    with pytest.raises(AgenticError, match='interview_primary_answer_required'):
        prepare(case, Writer(case[0], payload))
