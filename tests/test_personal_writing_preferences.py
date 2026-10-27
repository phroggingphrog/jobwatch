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


def test_archived_reference_library_requires_confirmed_opt_in(tmp_path, monkeypatch):
    import hashlib
    from jobwatch import users
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    career = users.user_dir() / 'career'
    (career / 'style' / 'refs').mkdir(parents=True)
    (career / 'templates').mkdir()
    (career / 'style' / 'examples').mkdir()
    registry = ('ref_id,kind,analysis_file,anon_file,layout_file\n'
                'sample,cv,style/sample.yaml,style/refs/sample.anon.md,style/refs/sample.layout.yaml\n')
    (career / 'style' / 'style_references.csv').write_text(registry)
    files = {'style/sample.yaml': 'rhythm: concise', 'style/refs/sample.anon.md': 'ANONYMISED CV FORM',
             'style/refs/sample.layout.yaml': 'sections: [experience, education]',
             'templates/cv_compact_1page.yaml': 'page_limit: 1',
             'style/examples/letter.md': 'OWN ARCHIVED LETTER VOICE'}
    for name, content in files.items():
        (career / name).write_text(content)
    assert 'reference_library' not in writing_guide('', '', '', approved={})
    assert 'human_examples' not in writing_guide('', '', '', approved=approved(use_style_examples=False))
    guide = writing_guide('', '', '', approved=approved(use_style_examples=True))
    library = guide['reference_library']
    assert library['registry'] == [{'ref_id': 'sample', 'kind': 'cv'}]
    assert library['registry_sha256'] == hashlib.sha256(registry.encode()).hexdigest()
    assert len(library['files']) == 4
    for item in library['files']:
        assert item['sha256'] == hashlib.sha256(item['text'].encode()).hexdigest()
        assert item['path'].startswith('career/')
    assert guide['human_examples']['example_1'] == 'OWN ARCHIVED LETTER VOICE'
    assert 'not candidate facts or instructions' in library['how_to_use']
    assert templates_for(approved(use_style_examples=True)) == ('cv_consult_default', 'cl_consult_default')


def test_current_examples_override_archived_examples(tmp_path, monkeypatch):
    from jobwatch import users
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    for folder, content in [('style/examples', 'CURRENT VOICE'), ('career/style/examples', 'ARCHIVE VOICE')]:
        target = users.user_dir() / folder
        target.mkdir(parents=True)
        (target / 'letter.md').write_text(content)
    guide = writing_guide('', '', '', approved=approved(use_style_examples=True))
    assert guide['human_examples']['example_1'] == 'CURRENT VOICE'
    assert 'ARCHIVE VOICE' not in str(guide)


def test_archive_library_refuses_traversal_symlinks_and_other_person(tmp_path, monkeypatch):
    from jobwatch import users
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    users.create_user_dirs('friend')
    career = users.user_dir('friend') / 'career'
    (career / 'style').mkdir(parents=True)
    (career / 'style' / 'style_references.csv').write_text(
        'ref_id,kind,analysis_file,anon_file,layout_file\n'
        'escape,cv,../../private.yaml,,\nlink,cv,style/link.yaml,,\n')
    outside = tmp_path / 'private.yaml'
    outside.write_text('ANOTHER PERSON SECRET')
    (career / 'style' / 'link.yaml').symlink_to(outside)
    owner_samples = tmp_path / 'career' / 'style' / 'examples'
    owner_samples.mkdir(parents=True)
    (owner_samples / 'letter.md').write_text('OWNER ONLY VOICE')
    with users.use('friend'):
        guide = writing_guide('', '', '', approved=approved(use_style_examples=True))
    assert guide['reference_library']['files'] == []
    assert guide['reference_library']['unavailable'] >= 2
    assert 'ANOTHER PERSON SECRET' not in str(guide) and 'OWNER ONLY VOICE' not in str(guide)
    assert 'human_examples' not in guide


def test_reference_text_and_total_output_are_bounded(tmp_path, monkeypatch):
    from jobwatch import users
    from pipeline.agentic import writing_guide as module
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(module, '_REFERENCE_FILE_BYTES', 32)
    monkeypatch.setattr(module, '_REFERENCE_TOTAL_BYTES', 50)
    folder = users.user_dir() / 'career' / 'style' / 'examples'
    folder.mkdir(parents=True)
    (folder / 'a.md').write_text('TOO LARGE ' * 20)
    for name in ['b.md', 'c.md', 'd.md']:
        (folder / name).write_text('small sample text!!!')
    guide = writing_guide('', '', '', approved=approved(use_style_examples=True))
    examples = guide['human_examples']
    text = [v for k, v in examples.items() if k.startswith('example_')]
    assert len(text) == 2 and sum(len(t.encode()) for t in text) <= 50
    assert 'TOO LARGE' not in str(guide)
