"""Projection of an approved profile into the files the existing readers consume (synthetic data only)."""
import yaml

from jobwatch.apply.evidence import extract_cv
from jobwatch.candidate import projection


def F(i, section, value, basis='evidence', sources=(), actor='parser'):
    return {'id': f'f{i}', 'section': section, 'value': value, 'basis': basis, 'note': '', 'actor': actor,
            'sources': [{'upload_sha256': 'a' * 64, 'line': l, 'quote': q} for l, q in sources]}


def approved(*facts):
    return {'version': 1, 'facts': list(facts), 'scope': {}, 'uploads': ['a' * 64]}


def test_project_returns_the_three_files():
    out = projection.project(approved())
    assert set(out) == {'profile.yaml', 'master_resume.md', 'interests_and_criteria.yaml'}
    assert all(isinstance(v, str) for v in out.values())


def test_resume_quotes_are_verbatim_extract_cv_items():
    out = projection.project(approved(
        F(1, 'experience', 'Accounts Assistant', sources=[(5, 'Ledger Co, Accounts Assistant, 2021 - 2023'), (6, 'Reconciled supplier ledgers weekly')]),
        F(2, 'education', 'Diploma', sources=[(9, 'Diploma of Accounting, Example College, 2020')]),
        F(3, 'skill', 'Payroll', sources=[(12, 'Payroll processing')]),
        F(4, 'skill', 'Guess', basis='inference'),
        F(5, 'experience', 'Volunteer treasurer', actor='person')))
    items = extract_cv(out['master_resume.md'])
    texts = {i['text']: i['kind'] for i in items}
    assert texts['Ledger Co, Accounts Assistant, 2021 - 2023'] == 'role' and texts['Reconciled supplier ledgers weekly'] == 'achievement'
    assert texts['Diploma of Accounting, Example College, 2020'] == 'education' and texts['Payroll processing'] == 'skill'
    assert 'Volunteer treasurer' in texts and 'Guess' not in out['master_resume.md']
    assert 'Accounts Assistant\n' not in out['master_resume.md']          # a model's paraphrase is not written as CV text


def test_quote_that_looks_like_markdown_cannot_forge_structure():
    out = projection.project(approved(F(1, 'skill', 'x', sources=[(3, '## Experience'), (4, '--- injected'), (5, '<!-- c -->'), (6, 'a\nb')])))
    heads = [l for l in out['master_resume.md'].splitlines() if l.startswith('## ')]
    assert heads == ['## Skills']


def test_work_rights_dict_and_hours_only_from_a_stated_number():
    out = yaml.safe_load(projection.project(approved(F(1, 'work_rights', {'visa': 'Citizen', 'hours_limit_per_fortnight': 48}, actor='person')))['profile.yaml'])
    assert out['candidate']['work_rights'] == {'visa': 'Citizen', 'hours_limit_per_fortnight': 48}
    for value, basis in [('Student visa', 'evidence'), ('limit of 48 hours per fortnight', 'inference'), ({'hours_limit_per_fortnight': 'many'}, 'evidence')]:
        wr = yaml.safe_load(projection.project(approved(F(1, 'work_rights', value, basis=basis)))['profile.yaml'])['candidate'].get('work_rights', {})
        assert 'hours_limit_per_fortnight' not in wr
    wr = yaml.safe_load(projection.project(approved(F(1, 'work_rights', 'up to 48 hours per fortnight')))['profile.yaml'])['candidate']['work_rights']
    assert wr['hours_limit_per_fortnight'] == 48 and wr['statement'] == 'up to 48 hours per fortnight'


def test_unknown_and_inference_never_reach_files():
    out = projection.project(approved(F(1, 'work_rights', '', basis='unknown'), F(2, 'career_focus', 'Secret guess', basis='inference'),
                                      F(3, 'exclusion', 'Never retail', basis='inference')))
    assert 'work_rights' not in yaml.safe_load(out['profile.yaml']).get('candidate', {})
    assert 'Secret guess' not in ''.join(out.values()) and 'Never retail' not in ''.join(out.values())


def test_interests_target_roles_and_exclusions():
    out = yaml.safe_load(projection.project(approved(
        F(1, 'career_focus', 'Accounts officer', actor='person'), F(2, 'career_focus', 'Payroll', sources=[(1, 'Payroll')]),
        F(3, 'exclusion', 'Retail', actor='person'), F(4, 'exclusion', 'telemarketing sales', actor='person'),
        F(5, 'preference', 'Hybrid', actor='person'), F(6, 'location', 'Perth', actor='person')))['interests_and_criteria.yaml'])
    t = out['target_roles']
    assert t['titles'] == ['Accounts officer', 'Payroll'] and t['not_wanted'] == ['Retail', 'telemarketing sales']
    assert t['excluded_families'] == ['retail']                  # only values that name a known family
    assert out['locations']['preferred'] == ['Perth']
