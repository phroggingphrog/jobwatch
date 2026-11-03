"""Clients project current understanding without preparing or replacing authority."""
import pytest
import sqlite3
from types import SimpleNamespace

from jobwatch import users
from jobwatch.candidate.presentation import current_understanding


@pytest.fixture(autouse=True)
def _owner_folder_profile(monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", "")   # the owner's own data folder, not the conftest-pinned example profile


