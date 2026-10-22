import hashlib
from types import SimpleNamespace

import yaml

from jobwatch import onboarding, users

CV = """# Sam Friend
sam@example.com

## Summary
Graduate nurse who completed clinical placements in a busy emergency ward.

## Education
### Bachelor of Nursing
*Example University, 2023*
"""
LETTER = "Dear team,\nI like people and I like ward work.\nSam"
DIPLOMA = "Bachelor of Nursing, Example University, 2023\nCourses: Anatomy 101; Pharmacology 200\nCertificate: Provide First Aid"


class FakeLLM:
    def chat(self, model, messages, json_mode=True, **kw):
        if "extract a job-search profile" in messages[0]["content"]:
            return SimpleNamespace(data={"name": "Sam Friend", "level": "graduate", "target_titles": ["graduate nurse"],
                                         "questions": ["Work rights?"]})
        return SimpleNamespace(data={"certifications": ["Bachelor of Nursing, Example University, 2023", "Pharmacology 200",
                                                         "Made up course"],
                                     "projects": []})


def snap(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()
            and "users" not in p.relative_to(root).parts}


def test_friend_wrangle(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "cv.md").write_text("owner cv")
    (tmp_path / "profile" / "evidence.yaml").write_text("items: []")
    users.create_user_dirs("friend")
    before = snap(tmp_path)
    with users.use("friend"):
        onboarding.wrangle([("cv", "cv.txt", CV), ("letter", "My Letter.docx", LETTER),
                            ("evidence", "diploma.txt", DIPLOMA)], "friend", FakeLLM())
        assert onboarding.style_examples() == [LETTER]
    f = tmp_path / "users" / "friend"
    ev = yaml.safe_load((f / "profile" / "evidence.yaml").read_text())["items"]
    texts = [i["text"] for i in ev]
    print((f / "profile" / "profile.yaml").read_text())
    print((f / "profile" / "evidence.yaml").read_text())
    print(sorted(str(p.relative_to(f)) for p in (f / "style").rglob("*") if p.is_file()))
    assert "Pharmacology 200" in texts and "Made up course" not in texts
    assert (f / "style" / "examples" / "01-my-letter.md").read_text() == LETTER
    assert snap(tmp_path) == before  # owner files byte-identical


def test_friend_cannot_reach_owner(tmp_path, monkeypatch):
    import base64, json, time
    import pytest
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from jobwatch.web.auth_routes import COOKIE, install_auth, make_cookie

    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBWATCH_SESSION_SECRET", "s3cret")
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "cv.md").write_text("owner cv")
    (tmp_path / "style" / "examples").mkdir(parents=True)
    (tmp_path / "style" / "examples" / "01.md").write_text("owner letter")
    users.create_user_dirs("friend")
    before = snap(tmp_path)
    # 1. path tricks in file names never leave friend's folder
    with users.use("friend"):
        for bad in ("../../../profile/cv.md", "../x.md", "/etc/passwd", ".hidden"):
            with pytest.raises(ValueError):
                onboarding.write_user_file("friend", "style/examples", bad, "x")
        onboarding.wrangle([("cv", "cv.txt", CV), ("letter", "../../../profile/cv.md", LETTER)], "friend", FakeLLM())
        # 2. friend cannot name the owner as the target or read owner's samples
        with pytest.raises(PermissionError):
            onboarding.write_user_file("owner", "style/examples", "x.md", "x")
        with pytest.raises(PermissionError):
            onboarding.wrangle([("cv", "cv.txt", CV)], "owner", FakeLLM())
        with pytest.raises(PermissionError):
            onboarding.style_examples("owner")
        assert onboarding.style_examples() == [LETTER]
    # 3. forged / tampered / traversal session cookies never become owner or another folder
    app = FastAPI()
    install_auth(app)

    @app.get("/who")
    def who():
        return {"user": users.current()}

    c = TestClient(app, base_url="http://127.0.0.1:8960")
    good = make_cookie("friend")
    body, sig = good.rsplit(".", 1)
    forged = base64.urlsafe_b64encode(json.dumps({"u": "owner", "exp": int(time.time()) + 999}).encode()).decode()
    traversal = make_cookie("../owner") if users.valid_name("../owner") else None
    for bad in (f"{forged}.{sig}", f"{forged}.", "owner", f"{body}.{'0' * 64}"):
        r = c.get("/who", cookies={COOKIE: bad}, follow_redirects=False)
        assert r.status_code in (303, 401) and "owner" not in r.text, bad
    assert not users.valid_name("../owner") and not users.valid_name("owner/../x")
    assert c.get("/who", cookies={COOKIE: good}).json() == {"user": "friend"}
    assert snap(tmp_path) == before  # owner files untouched


def test_drafter_gets_only_own_samples(tmp_path, monkeypatch):
    from jobwatch.apply import review
    monkeypatch.setattr('pipeline.agentic.writing_guide.approved_writing_profile', lambda: {'facts': [{
        'section': 'preference', 'basis': 'evidence', 'value': {'kind': 'writing', 'value': {'use_style_examples': True}}}]})

    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / "style" / "examples").mkdir(parents=True)
    (tmp_path / "style" / "examples" / "01.md").write_text("OWNER LETTER")
    users.create_user_dirs("friend")
    with users.use("friend"):
        onboarding.wrangle([("cv", "cv.txt", CV), ("letter", "l.txt", LETTER)], "friend", FakeLLM())
        msgs = review.drafter_messages("post", [], "cv", [], None, "", onboarding.style_examples())
    assert "I like people and I like ward work" in msgs[1]["content"] and "OWNER LETTER" not in msgs[1]["content"]


def test_run_chain_passes_only_own_samples(tmp_path, monkeypatch):
    import pytest
    from jobwatch.apply import chain

    monkeypatch.setattr('pipeline.agentic.writing_guide.approved_writing_profile', lambda: {'facts': [{
        'section': 'preference', 'basis': 'evidence', 'value': {'kind': 'writing', 'value': {'use_style_examples': True}}}]})

    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    (tmp_path / "style" / "examples").mkdir(parents=True)
    (tmp_path / "style" / "examples" / "01.md").write_text("OWNER LETTER")
    users.create_user_dirs("friend")
    seen = []

    class Stop(Exception):
        pass

    class CaptureLLM:
        def chat(self, model, messages, **kw):
            seen.append(messages[1]["content"])
            raise Stop

    monkeypatch.setattr(chain, "full_posting_text", lambda conn, p: "posting")
    monkeypatch.setattr(chain, "get_or_extract", lambda conn, pid, llm: [])
    monkeypatch.setattr(chain, "ad_reading", lambda conn, pid: None)
    monkeypatch.setattr(chain, "ensure_dir", lambda d: None)
    profile = SimpleNamespace(cv_body="cv", evidence=[], dir=tmp_path / "users" / "friend" / "profile")
    with users.use("friend"):
        onboarding.wrangle([("cv", "cv.txt", CV), ("letter", "l.txt", LETTER)], "friend", FakeLLM())
        with pytest.raises(Stop):
            chain.run_chain(None, {"id": 1, "title": "t", "company": "c"}, 1, 1, tmp_path, CaptureLLM(), profile)
    assert "I like people and I like ward work" in seen[0] and "OWNER LETTER" not in seen[0]


def test_legacy_string_work_rights_reads_as_unknown(tmp_path, monkeypatch):
    from jobwatch.candidate import person
    (tmp_path / "profile.yaml").write_text(yaml.safe_dump({"candidate": {"work_rights": "Australian citizen"}}))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(tmp_path))
    assert person.work_rights() == {"statement": "Australian citizen"}
    assert person.hours_limit_per_fortnight() is None


def test_build_profile_writes_structured_work_rights(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "write_profile_file", lambda user, name, text: None)
    class L:
        def chat(self, *a, **k):
            return SimpleNamespace(data={"name": "Sam", "work_rights": "Australian citizen"})
    profile, _ = onboarding.build_profile("cv", "sam", L())
    assert profile["candidate"]["work_rights"] == {"statement": "Australian citizen"}
    class E:
        def chat(self, *a, **k): return SimpleNamespace(data={"name": "Sam"})
    assert onboarding.build_profile("cv", "sam", E())[0]["candidate"]["work_rights"] == {}


def test_onboarding_missing_level_stays_unknown(monkeypatch):
    monkeypatch.setattr(onboarding, 'write_profile_file', lambda *args: None)
    class L:
        def chat(self, *args, **kwargs):
            return SimpleNamespace(data={'name': 'Sam'})
    profile, _ = onboarding.build_profile('cv', 'sam', L())
    assert profile['level'] == ''
    assert profile['avoid_titles'] == []
