import sqlite3
from jobwatch.outcomes.readiness import response_time_readiness


def history():
    conn=sqlite3.connect(':memory:')
    conn.executescript('CREATE TABLE applications(id INTEGER,status TEXT,applied_at TEXT); CREATE TABLE application_events(application_id INTEGER,kind TEXT,to_status TEXT,at TEXT);')
    return conn


def test_missing_history_is_insufficient_and_never_predictive():
    result=response_time_readiness(sqlite3.connect(':memory:'))
    assert result['status']=='insufficient_history' and result['model']=='none'


def test_pending_is_censored_and_preapplication_events_are_ignored():
    conn=history()
    conn.executemany('INSERT INTO applications VALUES(?,?,?)',[(1,'applied','2026-01-02'),(2,'applied','2026-01-02'),(3,'draft',None)])
    conn.execute("INSERT INTO application_events VALUES(1,'status','interview','2026-01-01')")
    result=response_time_readiness(conn)
    assert result['responses']==0 and result['censored']==2 and 'rate' not in result


def test_thirty_timed_replies_permit_only_later_investigation():
    conn=history()
    conn.executemany('INSERT INTO applications VALUES(?,?,?)',[(i,'rejected','2026-01-02') for i in range(30)])
    conn.executemany('INSERT INTO application_events VALUES(?,?,?,?)',[(i,'status','rejected','2026-01-04') for i in range(30)])
    result=response_time_readiness(conn)
    assert result['responses']==30 and result['censored']==0
    assert result['status']=='investigate' and result['model']=='none'
