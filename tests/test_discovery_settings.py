import hashlib
import json
import stat
from types import SimpleNamespace

import pytest

from jobwatch import users
from jobwatch.candidate import intake
from pipeline.agentic import discovery_settings


CONFIG = {'pipeline': {'agentic': {'batch_token_ceiling': 1234}}}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'data'))
    users.create_user_dirs('sam')
    users.create_user_dirs('sue')
    return tmp_path / 'data'


def _confirmed_profile(person, ceiling=900):
    scope = intake.SearchScope(basis=('synthetic analyst',), locations=(), daily_assessments=40,
                               daily_token_ceiling=ceiling)
    pdir = users.user_dir(person) / 'profile'
    pdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw_profile = b'career_focus: synthetic analyst\n'
    (pdir / 'profile.yaml').write_bytes(raw_profile)
    version = users.user_dir(person) / 'profile-versions' / '1'
    version.mkdir(parents=True, exist_ok=True, mode=0o700)
    approved = {
        'version': 1,
        'scope': scope.model_dump(mode='json'),
        'scope_digest': intake._scope_digest(scope),
        'file_sha256': {'profile.yaml': hashlib.sha256(raw_profile).hexdigest()},
    }
    path = version / 'approved.json'
    path.write_text(json.dumps(approved), encoding='utf-8')
    path.chmod(0o600)
    return path, approved, scope


def test_default_is_finite_and_inherits_confirmed_scope(data_dir, monkeypatch):
    monkeypatch.setattr('jobwatch.model_choice.chosen', lambda: {})
    assert discovery_settings.get_settings('sam', CONFIG) == {'daily_token_ceiling': 1234}
    _, _, _ = _confirmed_profile('sam', ceiling=876)
    assert discovery_settings.get_settings('sam', CONFIG) == {'daily_token_ceiling': 876}
    assert discovery_settings._path('sam').parent == data_dir / 'users' / 'sam' / 'config'


def test_unlimited_setting_is_person_scoped_and_written_privately(data_dir, monkeypatch):
    monkeypatch.setattr('jobwatch.model_choice.chosen', lambda: {})
    assert discovery_settings.set_settings('sam', CONFIG, None) == {'daily_token_ceiling': None}
    assert discovery_settings.get_settings('sam', CONFIG) == {'daily_token_ceiling': None}
    assert discovery_settings.get_settings('sue', CONFIG) == {'daily_token_ceiling': 1234}
    path = discovery_settings._path('sam')
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize('value', [0, -1, True, 1.5, '100'])
def test_daily_limit_requires_positive_strict_integer(data_dir, value):
    with pytest.raises(ValueError):
        discovery_settings.set_settings('sam', CONFIG, value)


def test_settings_schema_forbids_extra_fields():
    with pytest.raises(ValueError):
        discovery_settings.DailySettings.model_validate(
            {'daily_token_ceiling': 100, 'unlimited': True}, strict=True)


def test_malformed_existing_setting_fails_closed(data_dir, monkeypatch):
    monkeypatch.setattr('jobwatch.model_choice.chosen', lambda: {})
    _confirmed_profile('sam', ceiling=900)
    path = discovery_settings._path('sam')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"daily_token_ceiling": true}', encoding='utf-8')

    with pytest.raises(ValueError, match='invalid_discovery_settings'):
        discovery_settings.get_settings('sam', CONFIG)
    with pytest.raises(ValueError, match='invalid_discovery_settings'):
        intake.discovery_scope('sam')


def test_allowance_preserves_finite_daily_and_per_run_guards():
    assert discovery_settings.allowance(1000, 850, 200) == 150
    assert discovery_settings.allowance(1000, 1000, 200) == 0
    assert discovery_settings.allowance(None, 9_000_000, 200) == 200


def test_user_override_does_not_rewrite_or_bypass_confirmed_profile_digest(data_dir):
    path, approved, original = _confirmed_profile('sam', ceiling=900)
    before = path.read_bytes()
    assert intake.discovery_scope('sam') == original

    discovery_settings.set_settings('sam', CONFIG, None)
    effective = intake.discovery_scope('sam')

    assert effective is not None and effective.daily_token_ceiling is None
    assert path.read_bytes() == before
    assert approved['scope_digest'] == intake._scope_digest(original)


def test_future_confirmation_scope_uses_current_user_setting(data_dir, monkeypatch):
    monkeypatch.setattr('jobwatch.model_choice.chosen', lambda: {})
    discovery_settings.set_settings('sam', CONFIG, None)
    proposal = intake.Proposal(
        id='a' * 16, revision=1, base_version=None, uploads=(),
        facts=(intake.ProfileFact(id='f' * 16, section='career_focus', value='synthetic analyst',
                                  basis=intake.Basis.EVIDENCE),),
        questions=(), status='draft')

    with users.use('sam'):
        scope = intake.scope_for('sam', proposal, CONFIG)
    assert scope.daily_token_ceiling is None


def test_unlimited_embeddings_skip_daily_check_but_keep_per_run_cap(data_dir, monkeypatch):
    import time

    from jobwatch import db
    from jobwatch.occupations.embeddings import discovery_budget

    monkeypatch.setattr(intake, 'discovery_scope', lambda person: SimpleNamespace(daily_token_ceiling=None))
    conn = db.connect(data_dir / 'embeddings.sqlite')
    try:
        conn.execute("INSERT INTO discovery_spend(at,purpose,charged_tokens) VALUES(?,?,?)",
                     (time.time(), 'historical', 9_000_000))
        conn.commit()
        with discovery_budget(conn, 'unlimited', token_ceiling=321) as budget:
            assert budget.batch._state.token_ceiling == 321
    finally:
        conn.close()
