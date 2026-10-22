"""Confirmed style choices never become another person's defaults."""
from pipeline.agentic.writing_guide import writing_guide, writing_preferences, templates_for
from pipeline.agentic.draft import _role


def approved(**options):
    return {'facts': [{'section': 'preference', 'basis': 'evidence',
                       'value': {'kind': 'writing', 'value': options}}]}


def test_confirmed_options_keep_contrasting_voices_and_templates():
    warm = approved(tone='warm, eager and admiring', cv_template='cv_graduate_2page',
                    letter_template='cl_graduate_academic', omit_grades=True, responsibilities_per_role=6)
    direct = approved(tone='reserved and concise', cv_template='cv_compact_1page', omit_grades=False)
    assert writing_preferences(warm)['tone'] == 'warm, eager and admiring'
    assert writing_preferences(direct)['tone'] == 'reserved and concise'
    assert templates_for(warm)[0] == 'cv_graduate_2page'
    assert templates_for(direct)[0] == 'cv_compact_1page'
    assert writing_guide('', '', '', approved=warm)['preferences']['omit_grades'] is True
    assert writing_guide('', '', '', approved=direct)['preferences']['omit_grades'] is False


def test_unknown_and_inferred_style_is_neutral_and_not_a_graduate_template():
    inferred = approved(tone='eager')
    inferred['facts'][0]['basis'] = 'inference'
    assert writing_preferences(inferred) == {}
    guide = writing_guide('', 'Senior data scientist', 'analytics', approved={})
    assert guide['preferences'] == {}
    assert templates_for({}) == ('cv_consult_default', 'cl_consult_default')
    assert 'neutral' in guide['letter_approach'].lower()
    assert 'human_examples' not in guide
    prompt = _role(None, None, '').system_prompt
    for mandate in ('Show real eagerness', 'no grades', '5-6 key responsibilities', 'graduate template'):
        assert mandate not in prompt


def test_other_person_and_global_career_examples_are_not_loaded(tmp_path, monkeypatch):
    from jobwatch import users
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBWATCH_CAREER_DIR', str(tmp_path / 'outside'))
    outside = tmp_path / 'outside' / 'style' / 'examples'
    outside.mkdir(parents=True)
    (outside / 'owner.md').write_text('OTHER PERSON VOICE')
    users.create_user_dirs('friend')
    local = users.user_dir('friend') / 'style' / 'examples'
    local.mkdir(parents=True, exist_ok=True)
    (local / 'friend.md').write_text('OWN APPROVED VOICE')
    with users.use('friend'):
        guide = writing_guide('', '', '', approved=approved(use_style_examples=True))
    assert 'OWN APPROVED VOICE' in str(guide)
    assert 'OTHER PERSON VOICE' not in str(guide)


def test_style_opinions_only_apply_after_person_selects_them():
    from pipeline.agentic.letter_rules import third_opinion
    content = {'letter': {'paragraphs': [[{'text': 'I am writing to apply — a proven ability.'}]]}}
    assert third_opinion(content) == []
    assert third_opinion(content, style_rules={'avoid_stock_phrases': True, 'avoid_em_dashes': True})
    content['letter']['paragraphs'][0][0]['text'] = 'Hello [employer]'
    assert third_opinion(content)


def test_free_text_writing_preferences_are_preserved_as_framing_only():
    profile = {'facts': [{'section': 'preference', 'basis': 'evidence',
                          'value': 'For my cover letters, use an enthusiastic voice and no grades.'}]}
    guide = writing_guide('', '', '', approved=profile)
    assert 'enthusiastic voice' in str(guide['stated_preferences'])
    assert templates_for(profile) == ('cv_consult_default', 'cl_consult_default')


def test_legacy_drafter_and_cleanup_do_not_impose_unconfirmed_style(monkeypatch):
    from jobwatch.apply import review
    monkeypatch.setattr('pipeline.agentic.writing_guide.approved_writing_profile', lambda: {})
    messages = review.drafter_messages('ad', [], 'cv', [])
    assert 'neutral factual prose' in messages[0]['content']
    assert '2-5 bullets' not in messages[0]['content']
    content = {'letter': {'paragraphs': [[{'id': 'c1', 'text': 'I am applying for this role.', 'tier': 'framing'}]]}}
    assert review.stock_edits(content) == []
    assert review.drop_stock_framing(content) == 0
    assert content['letter']['paragraphs']


def test_legacy_template_selector_uses_confirmed_choice_instead_of_title(monkeypatch):
    from jobwatch.apply.render import pick_templates
    monkeypatch.setattr('pipeline.agentic.writing_guide.approved_writing_profile', lambda: {})
    assert pick_templates({'title': 'Graduate data analyst'}) == ('cv_consult_default', 'cl_consult_default')
    monkeypatch.setattr('pipeline.agentic.writing_guide.approved_writing_profile',
                        lambda: approved(cv_template='cv_compact_1page', letter_template='cl_short_direct'))
    assert pick_templates({'title': 'Senior engineer'}) == ('cv_compact_1page', 'cl_short_direct')


def test_malformed_style_values_cannot_crash_or_select_templates():
    profile = approved(cv_template=['cv_compact_1page'], letter_template={'name': 'cl_short_direct'},
                       tone=False, responsibilities_per_role=True)
    assert writing_preferences(profile) == {}
    assert templates_for(profile) == ('cv_consult_default', 'cl_consult_default')


def test_pdf_trimming_has_no_unconfirmed_six_skill_or_three_bullet_floor():
    from pipeline.agentic.draft import _trim_cv
    content = {'cv': {'skills': [{'text': 'Skill A'}, {'text': 'Skill B'}]}}
    assert _trim_cv(content)
    assert content['cv']['skills'] == [{'text': 'Skill A'}]


def test_symlinked_style_directory_cannot_read_another_person(tmp_path, monkeypatch):
    from jobwatch import users
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    users.create_user_dirs('friend')
    other = tmp_path / 'other-person' / 'examples'
    other.mkdir(parents=True)
    (other / 'private.md').write_text('OTHER PERSON PRIVATE VOICE')
    style = users.user_dir('friend') / 'style'
    style.mkdir(exist_ok=True)
    (style / 'examples').symlink_to(other, target_is_directory=True)
    with users.use('friend'):
        guide = writing_guide('', '', '', approved=approved(use_style_examples=True))
    assert 'human_examples' not in guide


def test_legacy_sample_opt_out_prevents_sample_text_in_model_prompt(monkeypatch):
    from jobwatch.apply.review import drafter_messages
    monkeypatch.setattr('pipeline.agentic.writing_guide.approved_writing_profile',
                        lambda: approved(use_style_examples=False))
    messages = drafter_messages('ad', [], 'cv', [], letter_samples=['PRIVATE OPTIONAL STYLE SAMPLE'])
    assert 'PRIVATE OPTIONAL STYLE SAMPLE' not in str(messages)
