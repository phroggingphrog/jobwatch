import json

import pytest

from jobwatch import cli, run as pipeline, users
from jobwatch.apply import paths as apaths
from jobwatch.candidate import intake


@pytest.fixture(autouse=True)
def _owner_folder_profile(monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", "")   # the owner's own data folder, not the conftest-pinned example profile






def _two_people(tmp_path, monkeypatch):
    from conftest import confirm_discovery
    from jobwatch.config import load_config
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    confirm_discovery(load_config(), "mate")                 # mate is confirmed; friend has nothing








