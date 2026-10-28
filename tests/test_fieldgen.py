from jobwatch import fieldgen, users
from jobwatch.config import load_config

NURSE = {"candidate": {"location": "Melbourne, VIC"}, "level": "graduate",
         "target_titles": ["graduate nurse", "registered nurse", "nursing assistant"],
         "avoid_titles": ["accountant"]}


def test_nurse_config(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    users.create_user_dirs("friend")
    fieldgen.generate_config(NURSE, "friend")
    with users.use("friend"):
        cfg = load_config()
    txt = str(cfg.searches) + str(cfg.rules)
    assert "graduate nurse" in txt and "nursing assistant" in txt
    assert "accounts payable" not in txt and "bookkeeper" not in txt
    assert cfg.rules["arms"][0]["id"] == "graduate_nurse"
