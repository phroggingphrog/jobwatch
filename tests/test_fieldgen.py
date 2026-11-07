import pytest
from jobwatch import fieldgen, users
from jobwatch.config import load_config


@pytest.fixture(autouse=True)
def _owner_folder_profile(monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", "")   # the owner's own data folder, not the conftest-pinned example profile

NURSE = {"candidate": {"location": "Melbourne, VIC"}, "level": "graduate",
         "target_titles": ["graduate nurse", "registered nurse", "nursing assistant"],
         "avoid_titles": ["accountant"]}


def test_nurse_config(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    fieldgen.generate_config(NURSE, users.current())
    cfg = load_config()
    txt = str(cfg.searches) + str(cfg.rules)
    assert "graduate nurse" in txt and "nursing assistant" in txt
    assert "accounts payable" not in txt and "bookkeeper" not in txt
    assert cfg.rules["arms"][0]["id"] == "graduate_nurse"


def test_generated_rules_do_not_read_a_national_title_as_remote(tmp_path, monkeypatch):
    from jobwatch.filters import Rules
    from jobwatch.models import Posting
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    fieldgen.generate_config({**NURSE, "remote_ok": True}, users.current())
    rules = Rules(load_config().rules)
    p = lambda title, loc: Posting(source="t", source_id=title + loc, url="https://x/" + title, title=title, location=loc)
    assert rules.location_rule(p("National Registered Nurse", "Sydney NSW")) != "remote_au"
    assert rules.location_rule(p("Registered Nurse", "Australia - National")) == "remote_au"


def test_generated_rules_do_not_invent_seniority_experience_or_remote_constraints(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    for level in ('', 'graduate', 'senior'):
        p = {'target_titles': ['nurse'], 'level': level}
        cdir = fieldgen.generate_config(p, users.current())
        rules = yaml.safe_load((cdir / 'rules.yaml').read_text())
        assert rules['seniority']['exclude_title'] == []
        assert rules['seniority']['exclude_min_years'] is None
        assert rules['flags']['experience_flag_min_years'] is None
        assert rules['location']['remote_patterns'] == []
        assert rules['location']['vic_patterns'] == []


def test_generated_rules_preserve_only_stated_exclusions_and_remote_preference(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    cdir = fieldgen.generate_config({**NURSE, 'remote_ok': True}, users.current())
    rules = yaml.safe_load((cdir / 'rules.yaml').read_text())
    assert rules['seniority']['exclude_title_global'] == ['\\baccountant\\b']
    assert rules['location']['remote_patterns']


def test_runtime_config_precedes_repository_defaults_and_explicit_overrides(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    fieldgen.generate_config(NURSE, users.current())
    runtime = users.config_dir()
    assert runtime == tmp_path / "config" and (runtime / "rules.yaml").is_file()
    assert load_config().config_dir == runtime
    assert "graduate nurse" in str(load_config().searches)

    explicit = tmp_path / "explicit"
    explicit.mkdir()
    (explicit / "rules.yaml").write_text(yaml.safe_dump({"arms": [{"id": "explicit_rule"}]}))
    assert load_config(explicit).rules["arms"][0]["id"] == "explicit_rule"
    assert load_config(explicit).searches == {}

    monkeypatch.setenv("JOBWATCH_CONFIG_DIR", str(explicit))
    assert load_config().config_dir == explicit
    assert load_config().rules["arms"][0]["id"] == "explicit_rule"


def test_fieldgen_refuses_a_non_owner_and_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="owner_required"):
        fieldgen.generate_config(NURSE, "friend")
    assert not (tmp_path / "config").exists()
