"""Route smoke tests for the web board against a scratch DB (never the real ~/brain)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobwatch import db as dbm
from jobwatch.config import DEFAULT_CONFIG_DIR, DEFAULT_SETTINGS, Config, _merge
from jobwatch.web.app import create_app

OK = {"host": "localhost", "origin": "http://localhost"}


def seed(conn, n, title, company="Telstra", arm="call_centre", tier="core"):
    cur = conn.execute(
        """INSERT INTO postings(source, source_id, url, url_hash, dedupe_key, title, company, location, state,
               description, flags_json, first_seen_at, last_seen_at, posted_at)
           VALUES('seek', ?, ?, ?, ?, ?, ?, 'Melbourne VIC', 'VIC', 'Answer calls.\nHelp customers.', '[]', ?, ?, ?)""",
        (str(n), f"https://example.org/job/{n}", f"h{n}", f"k{n}", title, company, dbm.ts(), dbm.ts(), dbm.ts()))
    conn.execute("INSERT INTO matches(posting_id, arm, arm_tier, arms_json, rules_json, flags_json, matched_at) "
                 "VALUES(?,?,?,?,?,?,?)", (cur.lastrowid, arm, tier, '["%s"]' % arm, "{}", "[]", dbm.ts()))
    conn.commit()
    return cur.lastrowid


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(data))
    monkeypatch.delenv("JOBWATCH_DB", raising=False)
    settings = _merge(DEFAULT_SETTINGS, {"db_path": str(data / "jobwatch.db")})
    config = Config(config_dir=DEFAULT_CONFIG_DIR, settings=settings, rules={}, searches={}, feeds={}, employers=[])
    conn = dbm.connect(config.db_path)
    ids = {"a": seed(conn, 1, "Customer Service Officer"),
           "evil": seed(conn, 2, "<script>alert(1)</script> Clerk", company="=HYPERLINK(1)"),
           "b": seed(conn, 3, "Receptionist", arm="receptionist")}
    for pid in ids.values():              # the board lists what the AI read and liked (ad_reviews verdict 'show')
        conn.execute("INSERT INTO ad_reviews(posting_id, content_hash, prompt_version, model, text_source, verdict, fit, reason, "
                     "reviewed_at) VALUES(?, ?, 2, 'test/model', 'full', 'show', 70, 'A clear office job.', ?)",
                     (pid, f"c{pid}", dbm.ts()))
    conn.commit()
    conn.close()
    c = TestClient(create_app(config), base_url="http://localhost", headers=OK, raise_server_exceptions=True)
    c.ids, c.tmp = ids, tmp_path
    return c


def test_pages_render(client):
    pid = client.ids["a"]
    for path in ("/", "/app", "/inbox", "/sources", "/insights", "/table", "/applications", f"/job/{pid}",
                 f"/job/{pid}/pane", "/api/board?scope=all", "/api/board?st=new", "/api/table", "/api/applications",
                 "/api/inbox", "/api/sources", "/api/insights", f"/api/job/{pid}", "/healthz"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:200])
    assert "Receptionist" in client.get("/api/board?q=receptionist").text
    assert "Customer Service Officer" not in client.get("/api/board?q=receptionist").text


def test_root_serves_the_app_and_old_pages_redirect_into_it(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200 and "/static/v3/" in r.text
    assert "'self'" in r.headers["content-security-policy"].split("font-src ")[1].split(";")[0]
    pid = client.ids["a"]
    for old, new in (("/classic", "/"), ("/table", "/#table"), ("/applications", "/#applications"),
                     (f"/job/{pid}", f"/#job/{pid}"), (f"/job/{pid}/pane", f"/#job/{pid}")):
        r = client.get(old, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == new, old
    assert client.get("/pebble", follow_redirects=False).status_code == 308


def test_unknown_job_is_404(client):
    assert client.get("/api/job/99999").status_code == 404


def test_host_header_guard(client):
    assert client.get("/healthz", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/healthz", headers={"host": "jobs.example.com"}).status_code == 200


def test_post_needs_same_origin(client):
    pid = client.ids["a"]
    url = f"/api/job/{pid}/save"
    anon = TestClient(client.app, base_url="http://localhost", headers={"host": "localhost"})   # no default Origin
    assert anon.post(url).status_code == 403                                                    # no Origin
    assert anon.post(url, headers={"origin": "https://evil.example"}).status_code == 403
    assert anon.post(url, headers={"origin": "null"}).status_code == 403
    assert anon.post(url, headers={"referer": "http://localhost/"}).status_code == 200         # Referer is accepted
    assert client.post(url).status_code == 200


def test_actions_write_through_the_ledger(client):
    pid = client.ids["a"]
    st = lambda: conn.execute("SELECT status FROM applications WHERE posting_id=?", (pid,)).fetchone()[0]
    assert client.post(f"/api/job/{pid}/save").status_code == 200
    conn = dbm.connect(client.tmp / "data" / "jobwatch.db")
    assert st() == "interested"
    assert client.post(f"/api/job/{pid}/hide").status_code == 200
    assert st() == "skipped"
    assert client.post(f"/api/job/{pid}/status", json={"status": "applied"}).status_code == 200
    assert st() == "applied"
    r = client.post(f"/api/job/{pid}/status", json={"status": "hired"})        # never settable
    assert r.status_code == 400 and st() == "applied"
    assert client.post(f"/api/job/{pid}/notes", json={"notes": "call Tuesday"}).status_code == 200
    assert conn.execute("SELECT notes FROM applications WHERE posting_id=?", (pid,)).fetchone()[0] == "call Tuesday"
    assert client.post(f"/api/job/{pid}/nonsense").status_code == 404
    r = client.post(f"/api/job/{pid}/hide")                                     # applied jobs cannot be hidden
    assert r.status_code == 400 and "Already applied" in r.text and st() == "applied"
    assert (client.tmp / "data" / "ledger" / "applications.jsonl").exists()
    assert "Customer Service Officer" in client.get("/api/applications").text


def test_csv_is_safe(client):
    body = client.get("/table.csv").text
    assert "'=HYPERLINK(1)" in body and ",=HYPERLINK(1)" not in body


def test_security_headers(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<script>" not in re.sub(r'<script src="[^"]+" defer></script>', "", r.text)      # no inline scripts


def test_draft_files_only_whitelisted_and_inside_root(client):
    root = client.tmp / "data" / "drafts" / "1" / "v1"
    root.mkdir(parents=True)
    (root / "cv.pdf").write_bytes(b"%PDF-1.4 test")
    (root / "secret.txt").write_text("nope")
    assert client.get("/files/drafts/1/v1/cv.pdf").status_code == 200
    assert client.get("/files/drafts/1/v1/secret.txt").status_code == 404
    assert client.get("/files/drafts/../jobwatch.db").status_code == 404
    assert client.get("/files/drafts/%2e%2e/jobwatch.db").status_code == 404


def test_saved_search_roundtrip(client):
    r = client.post("/api/searches", json={"name": "Reception", "qs": "q=receptionist"})
    assert r.status_code == 200
    r = client.get("/s/1", follow_redirects=False)
    assert r.status_code == 303 and "q=receptionist" in r.headers["location"]


def test_cross_site_subrequests_blocked_but_navigation_allowed(client):
    assert client.get("/", headers={"sec-fetch-site": "cross-site", "sec-fetch-mode": "no-cors"}).status_code == 403
    assert client.get("/", headers={"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate"}).status_code == 200
    assert client.get("/", headers={"sec-fetch-site": "same-origin", "sec-fetch-mode": "cors"}).status_code == 200


def test_javascript_urls_never_become_links(client):
    conn = dbm.connect(client.tmp / "data" / "jobwatch.db")
    pid = seed(conn, 9, "Bad Link Clerk")
    conn.execute("UPDATE postings SET url='javascript:alert(1)' WHERE id=?", (pid,))
    conn.commit()
    js = (Path(__file__).resolve().parents[2] / "jobwatch/web/static/app/app.js").read_text()
    assert js.count("javascript:") == 0 and js.count('test(j.url || "")') >= 2   # the app only links http(s) ad urls
