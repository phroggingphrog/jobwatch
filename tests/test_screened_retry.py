"""Only transport dead letters older than 6 h are put back."""
from datetime import UTC, datetime, timedelta

from jobwatch import db as dbm
from jobwatch.dedupe import ingest as ingest_posting
from jobwatch.models import Posting
from pipeline import screened, store
from pipeline.schemas import Stage
from conftest import make_config


def dead(conn, title, error, age_h):
    pid, _ = ingest_posting(conn, Posting(source="ats_pageup", source_id=title, url=f"https://example.com/{title}",
                                          title=title, company="Acme", location="Melbourne VIC", description="x"))
    store.admit(conn, pid, f"h{pid}", {}, Stage.EXTRACTED)
    store.dead_letter(conn, pid, "evaluate", Stage.EXTRACTED, 3, error)
    at = (datetime.now(UTC) - timedelta(hours=age_h)).isoformat(timespec="seconds")
    conn.execute("UPDATE pipeline_dlq SET created_at=? WHERE posting_id=?", (at, pid))
    conn.commit()
    return pid


def test_only_old_transport_failures_are_requeued(tmp_path):
    conn = dbm.connect(make_config(tmp_path=tmp_path).db_path)
    store.ensure(conn)
    old_transport = dead(conn, "a", "ConnectionError: refused", 7)
    new_transport = dead(conn, "b", "Timeout waiting for model", 1)
    old_validation = dead(conn, "c", "validation error: missing field", 7)
    assert screened.retry_transport(conn) == 1
    assert store.get(conn, old_transport)["stage"] == "extracted"
    assert store.get(conn, new_transport)["stage"] == "dlq" and store.get(conn, old_validation)["stage"] == "dlq"
