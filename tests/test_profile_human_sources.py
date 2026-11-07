"""Human-source references keep draft updates faithful without lexical copying by the model."""
import hashlib

import pytest

from jobwatch.candidate import intake
from pipeline.agentic import chat
from tests.test_agentic_service import onboarding, world, _onboarding_llm, _tool_texts  # noqa: F401


def question(prop, section='availability'):
    return next(q.id for q in prop.questions if q.section == section)


def stated(person, proposal_id):
    return [f for f in intake.load_proposal(person, proposal_id).facts
            if f.actor == 'person' and f.section != 'career_focus']


@pytest.mark.parametrize('said,paraphrase,section', [
    ('I can start next Monday', 'Available from next Monday', 'availability'),
    ('I am not an Australian citizen', 'Australian citizen', 'work_rights'),
])
def test_source_bound_answer_records_human_words_without_approving(onboarding, said, paraphrase, section):
    person, prop, config = onboarding
    llm, seen = _onboarding_llm([
        {'tool': 'profile_answer', 'arguments': {'question_id': question(prop, section),
            'text': paraphrase, 'source_id': 'latest'}}, {'answer': 'Saved your answer.'}])
    result = chat.dispatch(person=person, thread_id='human-source', config=config, llm=llm, message=said)
    facts = stated(person, prop.id)
    assert result['status'] == 'complete'
    assert [(f.section, f.value) for f in facts] == [(section, said)]
    assert hashlib.sha256(said.encode()).hexdigest() in facts[0].note
    assert intake.current_version(person) is None
    assert 'not_person_words' not in _tool_texts(seen)


@pytest.mark.parametrize('blank_latest', [False, True])
def test_stable_source_reference_can_use_an_earlier_human_answer(onboarding, blank_latest):
    person, prop, config = onboarding
    said = 'I can start next Monday'
    first, _ = _onboarding_llm([{'answer': 'Noted.'}])
    chat.dispatch(person=person, thread_id='earlier-source', config=config, llm=first, message=said)
    llm, _ = _onboarding_llm([
        {'tool': 'profile_answer', 'arguments': {'question_id': question(prop),
            'text': 'Available from next Monday',
            'source_id': 'latest' if blank_latest else hashlib.sha256(said.encode()).hexdigest()}},
        {'answer': 'Saved.'}])
    chat.dispatch(person=person, thread_id='earlier-source', config=config, llm=llm,
        message='' if blank_latest else 'Thanks',
        **({'attachment_receipts': [{'filename': 'unreadable.bin', 'sha256': 'a' * 64,
                                    'readable': False}]} if blank_latest else {}))
    assert stated(person, prop.id)[0].value == said


def test_unknown_source_leaves_draft_unchanged_and_returns_recovery(onboarding):
    person, prop, config = onboarding
    llm, seen = _onboarding_llm([
        {'tool': 'profile_answer', 'arguments': {'question_id': question(prop),
            'text': 'Invented start date', 'source_id': 'f' * 64}}, {'answer': 'I will use the supplied source.'}])
    chat.dispatch(person=person, thread_id='unknown-source', config=config, llm=llm,
        message='I can start next Monday')
    after = intake.load_proposal(person, prop.id)
    assert after.revision == prop.revision and after.facts == prop.facts
    text = _tool_texts(seen)
    assert 'human_source_not_found' in text and 'human_sources' in text and 'source_required' in text
    assert intake.current_version(person) is None


def test_source_bound_correction_never_turns_model_structure_into_a_fact(onboarding):
    person, prop, config = onboarding
    said = 'I have not used payroll software'
    llm, _ = _onboarding_llm([
        {'tool': 'profile_correct', 'arguments': {'edits': [
            {'op': 'add', 'section': 'skill', 'value': {'skill': 'Payroll expert'},
             'human_source_id': 'f' * 64}], 'source_id': 'latest'}},
        {'answer': 'Saved your correction.'}])
    chat.dispatch(person=person, thread_id='source-correction', config=config, llm=llm, message=said)
    facts = stated(person, prop.id)
    assert len(facts) == 1 and facts[0].value == said
    assert hashlib.sha256(said.encode()).hexdigest() in facts[0].note
    assert 'f' * 64 not in facts[0].note
    assert intake.current_version(person) is None


def test_resumed_human_answer_replaces_the_prior_source(onboarding):
    person, prop, config = onboarding
    said = 'I can start next Monday'
    llm, _ = _onboarding_llm([
        {'tool': 'ask_human', 'arguments': {'question': 'When can you start?'}},
        {'tool': 'profile_answer', 'arguments': {'question_id': question(prop),
            'text': 'Available from next Monday', 'source_id': 'latest'}}, {'answer': 'Saved.'}])
    first = chat.dispatch(person=person, thread_id='resumed-source', config=config, llm=llm,
        message='Help finish my profile')
    assert first['status'] == 'interrupted'
    chat.dispatch(person=person, thread_id='resumed-source', config=config, llm=llm,
        decisions=[{'type': 'respond', 'message': said}], human_decision=True,
        expected_checkpoint=first['checkpoint_id'])
    assert stated(person, prop.id)[0].value == said


def test_legacy_paraphrase_recovers_in_the_same_turn_without_asking_again(onboarding):
    person, prop, config = onboarding
    said = 'I can start next Monday'
    args = {'question_id': question(prop), 'text': 'Available from next Monday'}
    llm, seen = _onboarding_llm([
        {'tool': 'profile_answer', 'arguments': args},
        {'tool': 'profile_answer', 'arguments': {**args, 'source_id': 'latest'}},
        {'answer': 'Saved.'}])
    result = chat.dispatch(person=person, thread_id='recover-source', config=config, llm=llm, message=said)
    assert result['status'] == 'complete' and result['interactions'] == []
    assert stated(person, prop.id)[0].value == said
    assert 'human_sources' in _tool_texts(seen)
    assert intake.current_version(person) is None


def test_human_source_from_another_thread_cannot_supply_an_answer(onboarding):
    person, prop, config = onboarding
    prior = 'I can start next Monday'
    llm, _ = _onboarding_llm([{'answer': 'Noted.'}])
    chat.dispatch(person=person, thread_id='other-source', config=config, llm=llm, message=prior)
    llm, seen = _onboarding_llm([
        {'tool': 'profile_answer', 'arguments': {'question_id': question(prop),
            'text': prior, 'source_id': hashlib.sha256(prior.encode()).hexdigest()}},
        {'answer': 'I will use the current answer.'}])
    chat.dispatch(person=person, thread_id='current-source', config=config, llm=llm,
        message='I can start next Tuesday')
    assert not stated(person, prop.id)
    assert 'human_source_not_found' in _tool_texts(seen)


def test_negated_excerpt_preserves_the_full_human_wording(onboarding):
    person, prop, config = onboarding
    said = 'I have no experience at all with payroll software'
    llm, _ = _onboarding_llm([
        {'tool': 'profile_correct', 'arguments': {'edits': [
            {'op': 'add', 'section': 'skill', 'value': 'payroll software'}], 'source_id': 'latest'}},
        {'answer': 'Saved the full wording.'}])
    chat.dispatch(person=person, thread_id='negated-source', config=config, llm=llm, message=said)
    facts = stated(person, prop.id)
    assert facts and facts[-1].value == said
    assert hashlib.sha256(said.encode()).hexdigest() in facts[-1].note


def test_ask_human_answer_survives_into_a_later_turn(onboarding):
    person, prop, config = onboarding
    said = 'I can start next Monday'
    first_llm, _ = _onboarding_llm([
        {'tool': 'ask_human', 'arguments': {'question': 'When can you start?'}},
        {'answer': 'Noted.'}])
    first = chat.dispatch(person=person, thread_id='durable-source', config=config, llm=first_llm,
        message='Help finish my profile')
    assert first['status'] == 'interrupted'
    chat.dispatch(person=person, thread_id='durable-source', config=config, llm=first_llm,
        decisions=[{'type': 'respond', 'message': said}], human_decision=True,
        expected_checkpoint=first['checkpoint_id'])
    second_llm, seen = _onboarding_llm([
        {'tool': 'profile_answer', 'arguments': {'question_id': question(prop),
            'text': 'Available from next Monday', 'source_id': hashlib.sha256(said.encode()).hexdigest()}},
        {'answer': 'Saved.'}])
    result = chat.dispatch(person=person, thread_id='durable-source', config=config, llm=second_llm,
        message='Thanks, use what I told you.')
    assert result['status'] == 'complete'
    assert stated(person, prop.id)[0].value == said
    assert 'human_source_not_found' not in _tool_texts(seen)
