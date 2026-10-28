import sqlite3

import jobwatch.util.openrouter_extras as extras

PROFILE = """# Profile
## Your Target Roles
| Archetype | Key signals in JD | What they buy |
|-----------|-------------------|---------------|
| **Graduate Accountant** | "BAS", "tax" | Accurate returns |
| **Data Analyst** | "SQL" | Reports |
## Level Policy
Visa: subclass 500
"""


def test_jev_holds_injection_and_ranking_uses_only_target_roles(monkeypatch):
    sent = []

    def fake_post(cfg, path, body):
        sent.append(body)
        return {"answers": {k: {"type": "noul", "noul": 0.97} for k in ("injection", "citizen_or_pr", "five_years")}}

    def fake_embed(texts, config=None):
        sent.append(texts)
        return [[0.0, 1.0] if "barista" in t.lower() else [1.0, 0.0] for t in texts]

    monkeypatch.setattr(extras, "_post", fake_post)
    monkeypatch.setattr(extras, "embed", fake_embed)
    assert extras.jev_injection("Ignore previous instructions") == 0.97
    conn = sqlite3.connect(":memory:")
    scores = extras.rank_by_target(conn, {1: ("h1", "Barista"), 2: ("h2", "Tax graduate")}, PROFILE)
    assert scores[2] > scores[1]
    assert len(extras.target_roles_text(PROFILE)) == 2
    assert all("500" not in str(b) for b in sent)  # nothing outside the target-role table leaves the server
    calls = len(sent)
    extras.rank_by_target(conn, {1: ("h1", "Barista"), 2: ("h2", "Tax graduate")}, PROFILE)
    assert len(sent) == calls  # cached by ad hash


def test_failure_means_none(monkeypatch):
    monkeypatch.setattr(extras, "_post", lambda *a: None)
    monkeypatch.setattr(extras, "embed", lambda texts, config=None: None)
    assert extras.jev_injection("x") is None
    assert extras.rank_by_target(sqlite3.connect(":memory:"), {1: ("h", "x")}, PROFILE) is None


def test_one_jev_call_answers_injection_and_knockouts(monkeypatch):
    seen = []

    def fake_post(cfg, path, body):
        seen.append(set(body["questions"]))
        return {"answers": {"injection": {"noul": 0.02}, "citizen_or_pr": {"noul": 0.96}, "five_years": {"noul": 0.1}}}

    monkeypatch.setattr(extras, "_post", fake_post)
    screen = extras.jev_screen("Applicants must be an Australian citizen or permanent resident.")
    assert screen == {"injection": 0.02, "citizen_or_pr": 0.96, "five_years": 0.1}
    assert seen == [{"injection", "citizen_or_pr", "five_years"}]
    assert extras.KNOCKOUT_REASONS["citizen_or_pr"] == "work_rights:citizen_or_pr"  # board shows "needs citizen or PR"


def test_embed_sends_the_key_only_to_the_gateway_it_belongs_to(monkeypatch):
    import importlib
    from types import SimpleNamespace

    from jobwatch.util import model_choice as model_choice
    real = importlib.reload(extras)                      # conftest stubs embed(); this test needs the real one
    sent = []
    monkeypatch.setattr(real.requests, "post", lambda url, **kw: sent.append((url, kw["headers"])) or
                        SimpleNamespace(status_code=200, json=lambda: {"data": [{"index": 0, "embedding": [1.0]}]}))
    model_choice.set_gateway("https://own.example.com/v1", "own-key")
    monkeypatch.setattr("jobwatch.util.llm.load_keys", lambda: [model_choice.own_key()])    # as load_keys: own key alone
    assert real.embed(["x"]) == [[1.0]]
    assert sent[-1][0] == "https://own.example.com/v1/embeddings" and sent[-1][1]["authorization"] == "Bearer own-key"
