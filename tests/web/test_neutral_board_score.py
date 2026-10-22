from jobwatch.web.queries import fit_score


def test_entry_flag_does_not_change_fallback_ordering():
    row = dict(arm_tier='core', age_days=1, has_salary=False, warn=[], srcs=['test'])
    assert fit_score({**row, 'entry': True}) == fit_score({**row, 'entry': False})


def test_question_cards_keep_unknown_or_legacy_rights_neutral(monkeypatch):
    from jobwatch.web.ask_cards import _personal
    monkeypatch.setattr('jobwatch.apply.render._candidate', lambda: {'work_rights': 'Work rights unstated'})
    question, options = _personal('visa_type', 'Which visa are you on?', [])
    assert question == 'Which visa are you on?'
    assert not any(value == 'Student (500)' for _, value in options)
