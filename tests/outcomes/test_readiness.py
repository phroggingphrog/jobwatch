import sqlite3
import pytest
from jobwatch.outcomes.readiness import outcome_readiness


def db():
    c=sqlite3.connect(':memory:')
    c.executescript('CREATE TABLE applications(id,status,applied_at); CREATE TABLE application_events(application_id,to_status,kind);')
    return c


def test_no_outcomes_is_untrained_not_prior_prediction():
    r=outcome_readiness(db())
    assert r['status']=='untrained' and r['resolved_posterior'] is None and not r['prediction_available']


def test_pending_not_failure_and_draft_rejected_not_trial():
    c=db();c.executemany('INSERT INTO applications VALUES(?,?,?)',[(1,'applied','date'),(2,'rejected',None)])
    r=outcome_readiness(c)
    assert (r['applied'],r['pending'],r['resolved'])==(1,1,0)
    assert r['status']=='untrained'


def test_historical_callback_preserved_after_rejection():
    c=db();c.executemany('INSERT INTO applications VALUES(?,?,?)',[(1,'rejected','date'),(2,'rejected','date'),(3,'applied','date')])
    c.execute("INSERT INTO application_events VALUES(1,'interview','status')")
    r=outcome_readiness(c)
    assert (r['callbacks'],r['resolved_without_callback'],r['pending'])==(1,1,1)
    assert r['resolved_posterior']['mean']==pytest.approx(2/18)
    assert not r['prediction_available']
