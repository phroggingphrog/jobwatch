"""Chat page + push to the notification channels (owner 2026-10-12)."""
import sqlite3
import time
from types import SimpleNamespace

from jobwatch.util import model_choice as model_choice
from jobwatch import notify as nt
from jobwatch.web import chat_routes
from tests.notify_support import FakeChannel, use_fake_channel


def test_tests_and_other_databases_never_text_the_owner(monkeypatch):
    conn = sqlite3.connect(":memory:")
    use_fake_channel(monkeypatch, lambda lines: (_ for _ in ()).throw(AssertionError("pushed")))
    nt.notify(conn, "Ready for you: Synthetic Alpha")
    nt.alert(conn, "AI step crashed", "ai_step_crash")
    assert nt.unread(conn) == 1 and conn.execute("SELECT MAX(push) FROM chat_messages").fetchone()[0] == 0


def test_notify_saves_then_pushes_and_retries_a_failed_delivery(monkeypatch):
    real_time = time.time
    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(nt, "is_live", lambda c: True)
    sent = []
    use_fake_channel(monkeypatch, lambda lines: False)
    nt.notify(conn, "Ready for you: Graduate Accountant")          # news: Chat page only
    nt.alert(conn, "model cut off", "model_truncated_response")
    assert nt.unread(conn) == 1 and sent == []
    FakeChannel.sender = staticmethod(lambda lines: sent.extend(lines) or True)
    monkeypatch.setattr(time, "time", lambda: real_time() + 120)      # the failed delivery waits one backoff step
    assert nt.flush(conn) == 1 and sent == ["Jobwatch: Error: model cut off [model_truncated_response]"]
    assert nt.flush(conn) == 0                      # pushed once only
    assert nt.alert(conn, "model cut off again", "model_truncated_response") is None   # once a day per kind


def test_answer_sends_history_and_snapshot_to_sonnet(monkeypatch):
    conn = sqlite3.connect(":memory:")
    nt.add(conn, "owner", "any READY jobs?")
    monkeypatch.setattr(chat_routes, "snapshot", lambda c, question="": "READY jobs: none yet.")
    seen = {}

    class FakeLLM:
        def chat(self, model, messages, **kw):
            seen.update(model=model, messages=messages, json=kw.get("json_mode"))
            return SimpleNamespace(text="None yet.")
    assert chat_routes.answer(conn, FakeLLM()) == "None yet."
    assert seen["model"] == model_choice.DEFAULT_MODEL and seen["json"] is False
    assert "READY jobs: none yet." in seen["messages"][0]["content"] and seen["messages"][-1]["role"] == "user"


def test_pipeline_errors_stay_out_of_chat(monkeypatch):
    conn = sqlite3.connect(":memory:")
    nt.add(conn, "jobwatch", "Error: old row")
    nt.alert(conn, "AI step crashed", "ai_step_crash")
    nt.add(conn, "owner", "hi")
    assert [r[0] for r in conn.execute("SELECT text FROM chat_messages WHERE " + nt.CHAT_VISIBLE)] == ["hi"]
    assert nt.unread(conn) == 0 and [m["text"] for m in chat_routes.chat_history(conn)] == ["hi"]
