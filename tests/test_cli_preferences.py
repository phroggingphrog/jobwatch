"""Migration is explicit and never opens a database before owner confirmation."""
import argparse
import json
from types import SimpleNamespace


def test_migrate_needs_confirm_before_loading_config_or_opening_db(monkeypatch,capsys):
    from jobwatch.commands import preference as preference_cli
    def forbidden(*a,**kw): raise AssertionError('access before confirmation')
    monkeypatch.setattr(preference_cli,'load_config',forbidden)
    monkeypatch.setattr(preference_cli.sqlite3,'connect',forbidden)
    args=SimpleNamespace(cmd='preferences',action='migrate',confirm_owner=False)
    assert preference_cli.handle(args)==2
    assert json.loads(capsys.readouterr().out)=={'error':'confirm_owner_required'}


def test_register_migrate_flag():
    from jobwatch.commands import preference as preference_cli
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest='cmd')
    preference_cli.register(sub)
    args=parser.parse_args(['preferences','migrate','--confirm-owner'])
    assert args.action=='migrate' and args.confirm_owner is True


def test_explicit_migrate_uses_rw_and_does_not_fit(monkeypatch,capsys):
    from jobwatch.commands import preference as preference_cli
    from jobwatch.preferences import migration
    opened=[];called=[]
    class Conn:
        def close(self): called.append('closed')
    monkeypatch.setattr(preference_cli,'load_config',lambda *a:SimpleNamespace(db_path='/synthetic/jobs.db'))
    monkeypatch.setattr(preference_cli.sqlite3,'connect',lambda path,**kw:opened.append((path,kw)) or Conn())
    monkeypatch.setattr(migration,'refeaturise',lambda conn,cfg,*,actor:called.append(actor) or {'migrated':0})
    monkeypatch.setattr(preference_cli,'fit_store',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('unexpected fit')))
    args=SimpleNamespace(cmd='preferences',action='migrate',confirm_owner=True,config_dir=None)
    assert preference_cli.handle(args)==0
    assert opened==[('file:/synthetic/jobs.db?mode=rw',{'uri':True})]
    assert called==['owner','closed']
    assert json.loads(capsys.readouterr().out)=={'migrated':0}


def test_explicit_migrate_missing_database_returns_safe_error(monkeypatch,capsys,tmp_path):
    from jobwatch.commands import preference as preference_cli
    missing=tmp_path/'does-not-exist.sqlite'
    monkeypatch.setattr(preference_cli,'load_config',lambda *a:SimpleNamespace(db_path=missing))
    args=SimpleNamespace(cmd='preferences',action='migrate',confirm_owner=True,config_dir=None)
    assert preference_cli.handle(args)==1
    assert json.loads(capsys.readouterr().out)=={'error':'preference_operation_unavailable'}
    assert not missing.exists()
