from jobwatch import cli, users


def test_user_flag_writes_only_that_users_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    assert cli.main(["--user", "friend", "init-db"]) == 0
    assert (tmp_path / "users" / "friend" / "jobwatch.db").exists()
    assert not (tmp_path / "jobwatch.db").exists()
