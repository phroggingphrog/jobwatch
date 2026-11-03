"""Human revisions change exact pipeline inputs without editing profile evidence."""
import pytest
from jobwatch import users
from pipeline.agentic import revisions
from pipeline.agentic.service import snapshot_inventory
from tests.test_agentic_service import world  # noqa: F401


@pytest.fixture(autouse=True)
def _owner_folder_profile(monkeypatch):
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", "")   # the owner's own data folder, not the conftest-pinned example profile


