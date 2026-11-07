"""Synthetic regressions for native API polling as history grows."""
from pipeline.agentic.api_store import APIStore


def test_queue_and_status_queries_do_not_scan_history():
    with APIStore('owner') as store:
        thread = store.create_thread('synthetic')['id']
        with store.conn:
            store.conn.executemany(
                'INSERT INTO api_runs(id,thread_id,state,request_key,input_hash,input_json,created,updated) '
                "VALUES(?,?,'completed',?,'hash','{}',?,0)",
                [(str(i), thread, str(i), i) for i in range(5000)])
            store.conn.executemany(
                'INSERT INTO api_interactions(id,run_id,position,payload,expires) VALUES(?,?,0,?,0)',
                [(str(i), str(i), '{"type":"question"}') for i in range(5000)])
        ident = store.enqueue(thread, {'message': 'Synthetic'}, 'next')
        steps = 0

        def progress():
            nonlocal steps
            steps += 1
            return 0

        store.conn.set_progress_handler(progress, 1)
        assert store.claim_next()['id'] == ident
        assert store.public_run(ident)['interactions'] == []
        store.conn.set_progress_handler(None, 0)
        assert steps < 1000, f'Queue/status used {steps} SQLite VM steps'


def test_sse_database_wait_does_not_block_event_loop(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from pipeline.agentic.api import Principal, create_api

    key = 'synthetic-' + 's' * 40
    with APIStore('owner') as store:
        thread = store.create_thread('synthetic')['id']
        ident = store.enqueue(thread, {'message': 'Synthetic'}, 'stream')
        store.finish(ident, {'answer': 'Finished'})
    entered, release = threading.Event(), threading.Event()
    original = APIStore.events

    def blocked(self, *args, **kwargs):
        entered.set()
        release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(APIStore, 'events', blocked)
    app = create_api(credentials={key: Principal('owner')}, config={}, dispatcher=lambda **kw: {})
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        stream = pool.submit(client.get, f'/api/agent/runs/{ident}/events',
                             headers={'Authorization': 'Bearer ' + key})
        try:
            assert entered.wait(2)
            health = pool.submit(client.get, '/health')
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert 'event: completed' in stream.result(timeout=3).text
