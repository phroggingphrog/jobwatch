"""Optional local fit on frozen genuine choices confined to development cases.

Never creates choices from suitability labels and never activates a production fit.
The canonical sampler and all acceptance thresholds remain unchanged.
"""
from __future__ import annotations

from jobwatch import users
from jobwatch.candidate.contracts import digest
from jobwatch.preferences.features import context_hash,validate_alternatives,versions,PreferenceError
from jobwatch.preferences.store import MIN_TRAIN,MIN_HOLDOUT
from pipeline.agentic import baseline,eval_data,service


class FrozenChoices:
    origin='owner'

    def __init__(self,sets,identity):
        self.sets=sets
        self.identity=identity
        self.fits=[]

    def dataset(self,identity):
        if identity!=self.identity:
            raise PreferenceError('invalid_context')
        return self.sets

    def dataset_hash(self,identity):
        return digest(self.dataset(identity))

    def save_fit(self,summary):
        self.fits.append(summary)  # evaluation result only; never PreferenceStore.save_fit


def eligible_choices(baseline_id,cases,inputs):
    split=eval_data.load_split(baseline_id)
    if not {c.case_id for c in cases}<=set(split['development']):
        raise PreferenceError('development_fit_only')
    record=eval_data.record_for(baseline_id)
    approved=baseline.frozen_approved(baseline_id)
    by_posting={case.posting_id:case for case in cases}
    folder=baseline._baseline_dir(baseline_id)
    sets=[];identities=set()
    import json
    for key,index in sorted(inputs.get('choice_index',{}).items()):
        if not set(index['posting_ids'])<=set(by_posting):
            continue  # do not open a choice containing any holdout or unprocessed alternative
        raw=baseline._read_verified(folder/'choices'/f'{key}.json',index['sha256'])
        choice=json.loads(raw)
        if choice.get('origin')!='owner' or not choice.get('answered') or choice.get('versions')!=versions():
            continue
        alternatives=validate_alternatives(choice['alternatives'])
        valid=True;expected=set()
        for alt in alternatives:
            case=by_posting[alt['posting_id']]
            candidate=case.candidate
            structural=candidate.get('structural_analysis',candidate) if isinstance(candidate,dict) else None
            if structural is None:
                valid=False;break
            expected.add(context_hash(users.current(),case.evaluation['run_key']['evidence_hash'],record.policy,
                inputs['runtime'],structural['run_key'],service.RUBRIC_VERSION,service.IMPLEMENTATION_VERSION,digest(approved)))
            provenance=alt.get('source_provenance',{})
            if (alt['run_key']!=case.run_key or alt['evaluation_hash']!=digest(case.evaluation)
                    or alt['ad_hash']!=case.evaluation['run_key']['ad_hash']
                    or alt['profile_hash']!=case.evaluation['run_key']['evidence_hash']
                    or provenance.get('approved_hash')!=digest(approved)):
                valid=False;break
        if not valid or expected!={choice['context_hash']}:
            continue
        if choice.get('selected') is not None and choice['selected'] not in {a['posting_id'] for a in alternatives}:
            continue
        sets.append(choice);identities.add(choice['context_hash'])
    if len(identities)>1:
        raise PreferenceError('mixed_profiles')
    return sets,next(iter(identities),None)


def fit_development(baseline_id,cases,inputs,*,seconds):
    from jobwatch.preferences.model import fit_store,prepare_data
    sets,identity=eligible_choices(baseline_id,cases,inputs)
    counts=dict(n_train=sum(not s['holdout'] for s in sets),n_holdout=sum(s['holdout'] for s in sets))
    if counts['n_train']<MIN_TRAIN or counts['n_holdout']<MIN_HOLDOUT:
        return dict(status='insufficient_data',**counts)
    if seconds<1:
        return dict(status='deadline',**counts)
    store=FrozenChoices(sets,identity)
    prepare_data(sets)  # canonical train/holdout separation and missing-value preparation
    out=eval_data.private_dir(baseline._baseline_dir(baseline_id)/'evaluation'/'fits')
    try:
        summary=fit_store(store,out,identity,timeout=min(600,seconds))
    except PreferenceError as exc:
        return dict(status='timeout' if str(exc)=='local_fit_timeout' else 'fit_unavailable',**counts)
    return dict(status='accepted' if summary['gate']['accepted'] else 'rejected',**counts,
                dataset_hash=digest(sets),fit_id=summary['id'],activation='evaluation_only')
