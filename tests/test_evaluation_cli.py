import json
import sys
from jobwatch import cli
from pipeline.agentic import baseline,eval_data
from tests.baseline_support import world,frozen  # noqa:F401


def test_cli_freeze_split_replay_monitor_report(frozen,monkeypatch,capsys):
    monkeypatch.setenv('JOBWATCH_DB',str(frozen.config.db_path))
    monkeypatch.setattr('jobwatch.config.load_config',lambda *a,**k:frozen.config)
    assert cli.main(['evaluate','cases'])==0
    bid=json.loads(capsys.readouterr().out)['baseline_id']
    assert cli.main(['evaluate','split',bid])==0
    split=json.loads(capsys.readouterr().out)
    assert split['holdout'] and split['development']
    assert cli.main(['evaluate','replay',bid])==0
    result=json.loads(capsys.readouterr().out)
    assert result['usage']['model_calls']==0
    assert cli.main(['evaluate','report',bid,result['result_id']])==0
    out=capsys.readouterr().out
    assert 'json_path' in out and 'Synthetic' not in out
    monkeypatch.setattr(baseline,'read_labels',lambda *a:(_ for _ in ()).throw(AssertionError('monitor read labels')))
    assert cli.main(['evaluate','monitor',bid])==0
    assert json.loads(capsys.readouterr().out)['usage']['model_calls']==0
    assert cli.main(['evaluate','monitor',bid,'--limit','501'])==1
    assert 'monitor_limits_exceeded' in capsys.readouterr().err


def test_terminal_labels_and_explicit_holdout(frozen,monkeypatch,capsys):
    r=eval_data.freeze_cases(frozen.ro,frozen.config);split=eval_data.create_split(r.baseline_id)
    cid=split['holdout'][0]
    args=['evaluate','label',r.baseline_id,cid,'--suitable','yes']
    monkeypatch.setattr(sys.stdin,'isatty',lambda:False)
    assert cli.main(args)==1
    assert 'human_required' in capsys.readouterr().err
    monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
    assert cli.main(args)==1
    assert 'holdout_approval_required' in capsys.readouterr().err
    assert baseline.read_labels(r.baseline_id)==[]
    assert cli.main(args+['--allow-holdout'])==0
    assert baseline.read_labels(r.baseline_id)[0].suitable is True
