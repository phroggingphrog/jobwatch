"""Private evaluation tools. All model work is an explicit, budgeted opt-in."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def register(sub):
    parser=sub.add_parser('evaluate',help='frozen, private evaluation tools (--user <person>)')
    actions=parser.add_subparsers(dest='evaluation_action',required=True)
    cases=actions.add_parser('cases',help='freeze read-only stored cases, or list baselines')
    cases.add_argument('--list',action='store_true')
    cases.add_argument('--limit',type=int,default=500)
    cases.add_argument('--posting-id',type=int,action='append')
    label=actions.add_parser('label',help='record a genuine terminal human judgment')
    label.add_argument('baseline_id');label.add_argument('case_id')
    from jobwatch.baseline_cli import _YES_NO_UNSURE,LABEL_HELP
    label.description=LABEL_HELP
    label.add_argument('--suitable',choices=list(_YES_NO_UNSURE))
    label.add_argument('--relevance',type=int)
    label.add_argument('--exclusion-violation',choices=list(_YES_NO_UNSURE))
    label.add_argument('--note',default='');label.add_argument('--tag',action='append',default=[])
    label.add_argument('--allow-holdout',action='store_true')
    split=actions.add_parser('split',help='write-once grouped 30% holdout')
    split.add_argument('baseline_id');split.add_argument('--seed',type=int,default=1729)
    for name in ('replay','run','monitor'):
        p=actions.add_parser(name,help='bounded development monitor' if name=='monitor' else 'frozen canonical replay')
        p.add_argument('baseline_id');p.add_argument('--limit',type=int,default=500)
        p.add_argument('--seconds',type=float,default=300)
        p.add_argument('--paid',action='store_true');p.add_argument('--budget-tokens',type=int)
        p.add_argument('--fit',action='store_true')
        if name!='monitor':
            p.add_argument('--partition',choices=('development','holdout'),default='development')
            p.add_argument('--allow-holdout',action='store_true')
    report=actions.add_parser('report',help='export a stored result to private JSON and Markdown')
    report.add_argument('baseline_id');report.add_argument('result_id')
    report.add_argument('--allow-holdout',action='store_true')


def handle(args):
    if getattr(args,'cmd',None)!='evaluate':
        return None
    from pipeline.agentic.contracts import AgenticError
    try:
        return _handle(args)
    except AgenticError as exc:
        print(exc.code,file=sys.stderr)
        return 1
    except (ValueError,OSError,sqlite3.Error):
        print('evaluation_operation_unavailable',file=sys.stderr)
        return 1


def _handle(args):
    from pipeline.agentic import baseline,eval_data,evaluate_runs
    action=args.evaluation_action
    if action=='cases':
        if args.list:
            print(json.dumps([dict(baseline_id=r.baseline_id,cases=len(r.case_ids),profile_version=r.profile_version)
                              for r in baseline.list_baselines()],sort_keys=True))
            return 0
        from jobwatch.config import load_config
        config=load_config(args.config_dir)
        conn=sqlite3.connect(f'file:{config.db_path}?mode=ro',uri=True)
        conn.row_factory=sqlite3.Row
        try:
            record=eval_data.freeze_cases(conn,config,posting_ids=args.posting_id,limit=args.limit)
        finally:
            conn.close()
        print(json.dumps(dict(baseline_id=record.baseline_id,cases=len(record.case_ids)),sort_keys=True))
    elif action=='label':
        from jobwatch.baseline_cli import _label
        return _label(args)
    elif action=='split':
        value=eval_data.create_split(args.baseline_id,seed=args.seed)
        print(json.dumps({key:value[key] for key in ('baseline_id','split_hash','seed','development','holdout')},sort_keys=True))
    elif action in ('replay','run','monitor'):
        monitor=action=='monitor'
        if monitor and (args.limit>500 or args.seconds>300):
            from pipeline.agentic.contracts import AgenticError
            raise AgenticError('monitor_limits_exceeded')
        result=evaluate_runs.replay(args.baseline_id,partition=getattr(args,'partition','development'),
            allow_holdout=getattr(args,'allow_holdout',False),limit=args.limit,seconds=args.seconds,
            paid=args.paid,budget_tokens=args.budget_tokens,fit=args.fit,labels=not monitor)
        print(json.dumps(dict(result_id=result['result_id'],status=result['status'],processed=result['processed'],
            requested=result['requested'],stop_reason=result['stop_reason'],usage=result['usage']),sort_keys=True))
    elif action=='report':
        result=evaluate_runs.load_result(args.baseline_id,args.result_id,allow_holdout=args.allow_holdout)
        from jobwatch.reports.evaluation import write_report
        folder=baseline._baseline_dir(args.baseline_id)/'evaluation'/'reports'
        print(json.dumps(write_report(folder,result,result['metrics']),sort_keys=True))
    return 0
