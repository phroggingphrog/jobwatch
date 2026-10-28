from datetime import UTC, datetime, timedelta

from test_web import client, OK
from jobwatch import db


def test_followup_controls_record_confirmed_history_and_preserve_submission(client):
    pid=client.ids['a']
    client.post(f'/api/job/{pid}/status',json={'status':'applied'},headers=OK)
    at=(datetime.now(UTC)-timedelta(days=10)).isoformat()
    data={'action':'applied_confirmed','operation_id':'actual-date','owner_confirmed':'true','occurred_at':at}
    response=client.post(f'/api/applications/{pid}/followup',json=data,headers=OK)
    assert response.status_code==200 and response.json()['toast']=='Follow-up saved'
    data={'action':'sent','operation_id':'sent-one','owner_confirmed':'true','occurred_at':(datetime.now(UTC)-timedelta(days=1)).isoformat(),'channel':'email'}
    assert client.post(f'/api/applications/{pid}/followup',json=data,headers=OK).status_code==200
    assert client.post(f'/api/applications/{pid}/followup',json=data,headers=OK).status_code==200
    with db.connect(client.tmp / 'data/jobwatch.db') as conn:
        assert conn.execute('select status from applications where posting_id=?',(pid,)).fetchone()[0]=='applied'


def test_followup_endpoint_requires_confirmation_and_same_origin(client):
    pid=client.ids['a']
    client.post(f'/api/job/{pid}/status',json={'status':'applied'},headers=OK)
    data={'action':'sent','operation_id':'no-confirm','occurred_at':datetime.now(UTC).isoformat(),'channel':'email'}
    assert client.post(f'/api/applications/{pid}/followup',json=data,headers=OK).status_code==422
    data['owner_confirmed']='true'
    assert client.post(f'/api/applications/{pid}/followup',json=data,headers={'host':'localhost','origin':'https://outside.example'}).status_code==403
    with db.connect(client.tmp / "data/jobwatch.db") as conn:
        assert conn.execute("select count(*) from application_events where kind='followup_sent'").fetchone()[0]==0
