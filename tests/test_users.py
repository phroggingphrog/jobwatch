from jobwatch import users
from jobwatch.apply import paths
from jobwatch.config import load_config


def test_user_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    cfg = load_config()
    assert paths.data_dir() == tmp_path
    with users.use("friend"):
        assert paths.data_dir() == tmp_path / "users" / "friend"
        assert cfg.db_path == tmp_path / "users" / "friend" / "jobwatch.db"
        assert paths.profile_dir() == tmp_path / "users" / "friend" / "profile"
    assert paths.data_dir() == tmp_path
