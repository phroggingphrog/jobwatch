from types import SimpleNamespace

from pipeline import tracks
from pipeline.nodes import gate
from pipeline.schemas import JobFacts, MatchScore

from pipeline.category_migration import migrate_legacy

LEGACY_WORDS = ["graduate", "grad program", "internship", "intern", "vacation", "summer clerk", "cadet", "cadetship",
                "undergraduate", "undergrad", "student", "trainee", "traineeship"]

def migrated_config(screened):
    policy = [dict(id=name, label=name, priority=i, action=action, promote=promote, hours=hours)
              for i, (name, action, promote, hours) in enumerate([
                  ('undergraduate', 'admit', True, 'allow_hours_only'),
                  ('primary', 'admit', True, 'standard'),
                  ('secondary', 'side', False, 'standard'),
                  ('drop', 'archive', False, 'standard')])]
    migrated = migrate_legacy(screened, legacy_program_phrases=LEGACY_WORDS,
        legacy_policy=policy, program_category='undergraduate',
        id_mapping={p['id']: p['id'] for p in policy})["migrated"]
    return SimpleNamespace(settings={"pipeline": {"screened": migrated}})

CFG = migrated_config({"tracks": {"primary": ["accounts payable"], "secondary": ["barista", "chef"], "drop": ["registered nurse"]}})


def test_classify_order_and_defaults():
    t = tracks.settings(CFG)
    assert tracks.classify("Graduate Chef Program", t) == "undergraduate"
    assert tracks.classify("2027 Summer Vacation Internship", t) == "undergraduate"
    assert tracks.classify("Accounts Payable Officer", t) == "primary"
    assert tracks.classify("Barista (casual)", t) == "secondary"
    assert tracks.classify("Registered Nurse - Ward 4", t) == "drop"
    assert tracks.classify("Operations Coordinator", t) is None
    assert tracks.classify("Internal Auditor", t) is None          # "intern" is a whole word only


def test_no_private_lists_means_only_programs():
    t = tracks.settings(SimpleNamespace(settings={}))
    assert tracks.classify("Chef", t) is None
    assert tracks.classify("Graduate Analyst", t) is None


def _score():
    return MatchScore.model_validate({"technical_skills": {"score": 4, "evidence": "evidence text"},
                                      "experience": {"score": 4, "evidence": "evidence text"},
                                      "domain": {"score": 4, "evidence": "evidence text"},
                                      "wanted": "core", "justification": "a plain justification"})


def test_program_is_not_hidden_for_hours(monkeypatch):
    from jobwatch.candidate import eligibility
    monkeypatch.setattr(eligibility, "evaluate_eligibility",
                        lambda job, ad_text="": eligibility._result("excluded", "hours_exceeded"))
    facts = JobFacts.model_construct(real_job=True)
    monkeypatch.setattr(JobFacts, "model_dump", lambda self, **k: {})
    route, dec = gate.decide(facts, _score(), "full-time 38 hours per week", "Graduate Analyst",
                             posting={"track": "undergraduate"}, hours_policy="allow_hours_only")
    assert route == "draft" and dec.reason == "eligible_check_hours"
    route, _ = gate.decide(facts, _score(), "full-time 38 hours per week", "Analyst", posting={"track": "primary"})
    assert route == "archive"


def test_graph_gets_all_time_when_nothing_is_shortlisted(monkeypatch, tmp_path):
    import sqlite3
    from pipeline import screened, store
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    store.ensure(conn)
    got = {}

    class G:
        def __init__(self, **k): pass
        async def run(self, max_seconds=None):
            got["graph"] = max_seconds
            return {}
    monkeypatch.setattr(screened, "ScreenedGraph", G)
    monkeypatch.setattr(screened.graph.Settings, "from_config", staticmethod(lambda c: None))
    monkeypatch.setattr(screened, "promote", lambda *a, **k: {})
    monkeypatch.setattr(screened, "retry_transport", lambda c: 0)
    monkeypatch.setattr(screened, "_title_triage", lambda *a: {})
    monkeypatch.setattr(screened, "sort_untracked", lambda *a: {})
    cfg = SimpleNamespace(settings={}, db_path=tmp_path / "x.db")
    from jobwatch.util import adtext
    monkeypatch.setattr(adtext, "lock_path", lambda c: tmp_path / "lock")
    screened.after_collect(conn, cfg, max_seconds=400)
    assert got["graph"] > 399


def test_waiting_shortlist_is_promoted_before_scoring(monkeypatch, tmp_path):
    import sqlite3
    from pipeline import screened, store
    from pipeline.schemas import Stage
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    store.ensure(conn)
    conn.execute("INSERT INTO pipeline_state (posting_id, stage, content_hash, data_json, updated_at) VALUES (1, ?, 'h', '{}', 'x')",
                 (str(Stage.SHORTLISTED),))
    order = []

    class G:
        def __init__(self, **k): pass
        async def run(self, max_seconds=None):
            order.append(("graph", max_seconds))
            return {}
    monkeypatch.setattr(screened, "ScreenedGraph", G)
    monkeypatch.setattr(screened.graph.Settings, "from_config", staticmethod(lambda c: None))
    monkeypatch.setattr(screened, "promote", lambda c, cfg, max_seconds=None, deadline=None: order.append(("promote", max_seconds)) or {})
    monkeypatch.setattr(screened, "retry_transport", lambda c: 0)
    monkeypatch.setattr(screened, "_title_triage", lambda *a: {})
    monkeypatch.setattr(screened, "sort_untracked", lambda *a: {})
    cfg = SimpleNamespace(settings={}, db_path=tmp_path / "x.db")
    from jobwatch.util import adtext
    monkeypatch.setattr(adtext, "lock_path", lambda c: tmp_path / "lock")
    screened.after_collect(conn, cfg, max_seconds=400)
    assert [n for n, _ in order] == ["promote", "graph"] and order[0][1] == 200 and order[1][1] > 390


def test_title_triage_drops_and_keeps_unsure(monkeypatch):
    import sqlite3
    from pipeline import store, title_triage
    from pipeline.nodes import ingest
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    store.ensure(conn)
    rows = [{"id": 1, "title": "Specialist Anaesthetist"}, {"id": 2, "title": "Planning and Performance Analyst"},
            {"id": 3, "title": "Accountant"}]
    monkeypatch.setattr(ingest, "candidates", lambda c, ids=None: rows)
    seen = {}

    def fake(llm, model, system, user, schema, **k):
        seen["user"] = user
        return schema(items=[{"id": 1, "track": "drop"}, {"id": 2, "track": "unsure"}]), 1
    monkeypatch.setattr(title_triage, "call", fake)
    cfg = migrated_config({"tracks": {"primary": ["accountant"]}})
    out = title_triage.run(conn, cfg, None, "m")
    assert out["asked"] == 2 and out["drop"] == 1 and out["unsure"] == 1
    assert "Accountant" not in seen["user"]            # a listed title is never sent
    assert title_triage.known(conn, tracks.settings(cfg)) == {1: "drop", 2: "unsure"}
    assert title_triage.run(conn, cfg, None, "m")["asked"] == 0   # asked once only


def test_unlisted_drop_setting():
    from pipeline import tracks
    on = migrated_config({"unlisted": "drop"})
    assert tracks.unlisted_drop(on) and not tracks.unlisted_drop(SimpleNamespace(settings={}))


def test_untracked_jobs_get_a_track_before_promotion():
    import sqlite3
    from pipeline import screened, store
    from pipeline.schemas import Stage
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    store.ensure(conn)
    conn.execute("CREATE TABLE postings (id INTEGER PRIMARY KEY, title TEXT)")
    for pid, title in [(1, "Retail Assistant - Mildura"), (2, "Graduate Accountant"), (3, "Casual Crew")]:
        conn.execute("INSERT INTO postings VALUES (?, ?)", (pid, title))
        store.admit(conn, pid, f"h{pid}", {}, Stage.SHORTLISTED)
    cfg = migrated_config({"unlisted": "drop", "tracks": {"secondary": ["retail"]}})
    assert screened.sort_untracked(conn, cfg) == {"secondary": 1, "undergraduate": 1, "unassigned": 1}
    stages = {r[0]: r[1] for r in conn.execute("SELECT posting_id, stage FROM pipeline_state")}
    assert stages == {1: "side", 2: "shortlisted", 3: "archived"}
