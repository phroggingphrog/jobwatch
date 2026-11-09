"""Owner config resolution: real owner files first, neutral examples as the fresh-clone fallback."""
from pathlib import Path

import yaml
import pytest

from jobwatch import config as config_module


@pytest.mark.parametrize('seed_owner_files', [False, True])
def test_shipped_config_disables_execution_with_a_valid_mode(tmp_path, seed_owner_files):
    from jobwatch.execution_mode import effective_mode

    directory = config_module.DEFAULT_CONFIG_DIR
    if seed_owner_files:
        config_module.init_config(tmp_path)
        directory = tmp_path
    assert effective_mode(config_module.load_config(directory)) == 'off'


@pytest.mark.parametrize('selection', ['default', 'env', 'global', 'subcommand', 'global_over_env', 'subcommand_over_global'])
def test_init_config_cli_uses_the_selected_directory(tmp_path, monkeypatch, selection):
    from jobwatch import cli, users

    arguments = ['init-config']
    target = users.user_dir() / 'config'
    if selection in ('env', 'global_over_env', 'subcommand_over_global'):
        target = tmp_path / 'env-config'
        monkeypatch.setenv('JOBWATCH_CONFIG_DIR', str(target))
    if selection in ('global', 'global_over_env', 'subcommand_over_global'):
        target = tmp_path / 'global-config'
        arguments = ['--config-dir', str(target), *arguments]
    if selection in ('subcommand', 'subcommand_over_global'):
        target = tmp_path / 'subcommand-config'
        arguments += ['--config-dir', str(target)]

    assert cli.main(arguments) == 0
    assert (target / 'jobwatch.yaml').is_file()
    assert (target / 'rules.yaml').is_file()
    if selection != 'default':
        assert not (users.user_dir() / 'config').exists()


def _write(path: Path, document: dict) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_owner_runtime_config_is_loaded_first(tmp_path, monkeypatch):
    runtime = tmp_path / "data" / "config"
    runtime.mkdir(parents=True)
    _write(runtime / "rules.yaml", {"arms": [{"id": "owner_rule"}]})
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("JOBWATCH_CONFIG_DIR", raising=False)
    monkeypatch.delenv("JOBWATCH_EMPLOYERS", raising=False)

    loaded = config_module.load_config()

    assert [arm["id"] for arm in loaded.rules["arms"]] == ["owner_rule"]


def test_owner_file_wins_over_an_example_in_the_same_source(tmp_path):
    _write(tmp_path / "rules.yaml", {"arms": [{"id": "owner_rule"}]})
    _write(tmp_path / "rules.example.yaml", {"arms": [{"id": "example_rule"}]})

    assert config_module.load_config(tmp_path).rules["arms"][0]["id"] == "owner_rule"


def test_example_files_fill_a_fresh_checkout(tmp_path):
    _write(tmp_path / "rules.example.yaml", {"arms": [{"id": "example_rule"}]})
    _write(tmp_path / "jobwatch.example.yaml", {"timezone": "Example/Zone"})
    _write(tmp_path / "searches.example.yaml", {"location": "Example City"})

    loaded = config_module.load_config(tmp_path)

    assert [arm["id"] for arm in loaded.rules["arms"]] == ["example_rule"]
    assert loaded.settings["timezone"] == "Example/Zone"
    assert loaded.searches["location"] == "Example City"


def test_example_fallback_keeps_the_txt_suffix(tmp_path):
    (tmp_path / "vic_localities.example.txt").write_text("Exampleville\n", encoding="utf-8")

    resolved = config_module._first_file([tmp_path], "vic_localities.txt")

    assert resolved == tmp_path / "vic_localities.example.txt"


def test_missing_file_without_an_example_stays_unset(tmp_path):
    assert config_module._first_file([tmp_path], "rules.yaml") is None
    assert config_module._load_first([tmp_path], "rules.yaml") == {}


def test_employers_fall_back_to_the_neutral_example(tmp_path):
    _write(tmp_path / "employers.example.yaml", {"employers": [{"name": "Example Co"}]})

    loaded = config_module.load_config(tmp_path)

    assert [employer["name"] for employer in loaded.employers] == ["Example Co"]


def test_init_config_copies_examples_without_overwriting_owner_files(tmp_path):
    (tmp_path / "example").mkdir()
    _write(tmp_path / "example" / "rules.example.yaml", {"arms": [{"id": "example_rule"}]})
    (tmp_path / "example" / "vic_localities.example.txt").write_text("Exampleville\n", encoding="utf-8")
    owner_dir = tmp_path / "owner"
    owner_dir.mkdir()
    _write(owner_dir / "rules.yaml", {"arms": [{"id": "owner_rule"}]})

    created = config_module.init_config(owner_dir, examples=tmp_path / "example")

    assert sorted(path.name for path in created) == ["vic_localities.txt"]
    assert (owner_dir / "vic_localities.txt").read_text(encoding="utf-8") == "Exampleville\n"
    assert "owner_rule" in (owner_dir / "rules.yaml").read_text(encoding="utf-8")
