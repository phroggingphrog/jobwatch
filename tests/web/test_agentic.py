"""Agentic career-ops board presentation tests using synthetic rows only."""
import json

from fastapi.testclient import TestClient

from jobwatch import db as dbm
from jobwatch.config import DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, Config, _merge
from jobwatch.web.app import create_app
from pipeline import store as pstore


OK = {"host": "localhost", "origin": "http://localhost"}


def _client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(data))
    monkeypatch.delenv("JOBWATCH_DB", raising=False)
    config = Config(config_dir=DEFAULT_CONFIG_DIR,
                    settings=_merge(DEFAULT_SETTINGS, {"db_path": str(data / "jobwatch.db")}),
                    rules={}, searches={}, feeds={}, employers=[])
    conn = dbm.connect(config.db_path)
    pstore.ensure(conn)
    now = dbm.ts()
    cur = conn.execute(
        """INSERT INTO postings(source,source_id,url,url_hash,dedupe_key,title,company,location,state,
               description,flags_json,first_seen_at,last_seen_at,posted_at)
           VALUES('seek','synthetic','https://example.org/job','h','k',?,?, 'Melbourne VIC','VIC', ?, '[]',?,?,?)""",
        ("Analyst <b>role</b>", "Synthetic Co", "Research <script>unsafe()</script>", now, now, now))
    pid = cur.lastrowid
    conn.execute("INSERT INTO matches(posting_id,arm,arm_tier,arms_json,rules_json,flags_json,matched_at) "
                 "VALUES(?, 'analyst', 'core', '[]', '{}', '[]', ?)", (pid, now))
    conn.execute("INSERT INTO applications(posting_id,status,created_at,updated_at) VALUES(?, 'interested', ?, ?)",
                 (pid, now, now))
    conn.execute("INSERT INTO ad_reviews(posting_id,content_hash,prompt_version,model,text_source,verdict,fit,reason,reviewed_at) "
                 "VALUES(?, 'hash', 2, 'test/model', 'full', 'show', 80, ?, ?)",
                 (pid, "Strong fit <img src=x onerror=alert(1)>", now))
    conn.execute("INSERT INTO pipeline_state(posting_id,stage,content_hash,data_json,updated_at) "
                 "VALUES(?, 'ready', 'hash', ?, ?)",
                 (pid, json.dumps({"evaluate": {"justification": "Agent reason <b>securely</b>",
                                     "technical_skills": {"score": 4}}}), now))
    conn.commit()
    conn.close()
    client = TestClient(create_app(config), base_url="http://localhost", headers=OK)
    client.pid = pid
    client.data = data
    return client


def test_board_shows_agent_reason_as_escaped_text(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/board")           # plain text in JSON; the app escapes it when drawing
    assert response.status_code == 200
    assert "Agent reason <b>securely</b>" in response.json()["rows"][0]["ai"]["reason"]


def test_applications_shows_safe_agentic_hold_and_ready_package(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    conn = dbm.connect(client.data / "jobwatch.db")
    # Agentic tables are optional in a legacy database; add representative synthetic data.
    conn.execute("CREATE TABLE agentic_runs(run_key TEXT, posting_id INTEGER, status TEXT, reason TEXT, checkpoint_json TEXT)")
    checkpoint = {"extract": {}, "evaluate": {"justification": "Matched <em>skills</em>",
                                                "technical_skills": {"score": 4},
                                                "experience": {"score": 5}, "domain": {"score": 4}},
                  "draft": {"claims": [{"verified": True}, {"verified": False}], "hold": "Owner check"},
                  "form_map": {"owner_to_answer": 1}}
    conn.execute("UPDATE pipeline_state SET stage='ready', data_json=?, updated_at=? WHERE posting_id=?",
                 (json.dumps(checkpoint), dbm.ts(), client.pid))
    conn.execute("INSERT INTO drafts(application_id,version,created_at,status,dir,claims_json,verify_json) "
                 "VALUES(1,1,?,'ready','/private',?,?)",
                 (dbm.ts(), json.dumps({"claims": [{"verified": True}, {"verified": False}]}),
                  json.dumps({"verified_claims": 1, "total_claims": 2})))
    conn.commit()
    conn.close()

    response = client.get("/api/applications")
    assert response.status_code == 200
    assert "Owner check" in response.text
    assert "/private/cv.pdf" not in response.text
    assert "Matched <em>skills</em>" in response.text


def test_legacy_database_without_agentic_tables_still_serves_board_and_applications(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    conn = dbm.connect(client.data / "jobwatch.db")
    conn.execute("DROP TABLE IF EXISTS agentic_runs")
    conn.commit()
    conn.close()
    assert client.get("/api/board").status_code == 200
    assert client.get("/api/applications").status_code == 200


def test_answers_page_saves_and_keeps_comments(tmp_path, monkeypatch):
    prof = tmp_path / "prof"; prof.mkdir()
    (prof / "answers.yaml").write_text('version: 1\n\nsalary:\n  expected_annual_aud: ""  # number\nreferees:\n  - name: ""\n    role: ""\n')
    monkeypatch.setattr("jobwatch.apply.paths.profile_dir", lambda: prof)
    from jobwatch.web.answers_routes import parse, save
    out = save((prof / "answers.yaml").read_text(), {"salary.expected_annual_aud": "90000", "referees.1.name": 'A "B"'})
    assert 'expected_annual_aud: "90000"  # number' in out and 'name: "A \'B\'"' in out
    assert [f["id"] for f in parse(out)[0]] == ["salary.expected_annual_aud", "referees.1.name", "referees.1.role"]
