"""Models settings: a saved pick is returned by get_model; any model id is allowed."""
from jobwatch import model_choice as mc
from jobwatch import users


def test_pick_saved_and_returned(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    with users.use(users.DEFAULT_USER):
        mc.set_models({"writer": "claude/sonnet", "reader": "x/y:free"})
        assert mc.get_model("writer") == "claude/sonnet" and mc.get_model("reader") == "x/y:free"
        assert mc.get_model("chat") == mc.DEFAULT_MODEL
        mc.set_gateway("https://openrouter.ai/api/v1", "sk-secret-1234")
        assert mc.gateway_view()["key_tail"] == "1234" and "secret" not in str(mc.gateway_view())
        assert ((users.user_dir() / "config" / "gateway.json").stat().st_mode & 0o777) == 0o600
