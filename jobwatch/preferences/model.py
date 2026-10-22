"""Bounded local R/JAGS fitting and fail-closed posterior prediction."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import uuid
from .features import (NAMES, PRIOR_MEANS, FAMILIES, PreferenceError, digest, canonical,
                       versions, family_index, validate_alternatives)
from .store import MIN_TRAIN, MIN_HOLDOUT

RHAT_MAX = 1.01
ESS_MIN = 10000
MCSE_RATIO_MAX = .01

def parameter_names():
    return ([f'beta[{i}]' for i in range(1,len(NAMES)*2+1)] +
            [f'{kind}[{i}]' for kind in ('alpha','alpha_raw') for i in range(1,len(FAMILIES)+1)] + ['mu_alpha','tau'])

def evaluate_fit(summary):
    reasons=[]
    if not isinstance(summary,dict):
        return {'accepted':False,'reasons':['invalid_summary']}
    parameters=summary.get('parameters',{})
    if type(parameters) is not dict or set(parameters)!=set(parameter_names()):
        reasons.append('missing_parameters')
        parameters={}
    for name,p in parameters.items():
        keys=('rhat','ess','mcse','mcse_ratio','sd','mean','mode','hdi_low','hdi_high')
        if type(p) is not dict or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in keys):
            reasons.append('nonfinite_parameter:'+name)
            continue
        if p['rhat']>RHAT_MAX or p['rhat']<=0 or p['ess']<ESS_MIN or p['sd']<=0 or p['mcse']<0 or p['mcse_ratio']>MCSE_RATIO_MAX or p['mcse_ratio']<0:
            reasons.append('diagnostics:'+name)
        if p['sd']<=0 or p['ess']<=0:
            continue
        if p['mcse']/p['sd']>MCSE_RATIO_MAX or abs(p['mcse_ratio']-1/math.sqrt(p['ess']))>1e-8 or abs(p['mcse']-p['sd']/math.sqrt(p['ess']))>1e-8:
            reasons.append('inconsistent_mcse:'+name)
        if p['hdi_low']>p['hdi_high']:
            reasons.append('invalid_interval:'+name)
    if summary.get('chains')!=4 or summary.get('seeds')!=[1103,2207,3301,4409]:
        reasons.append('invalid_chains')
    for key,minimum in (('n_train',MIN_TRAIN),('n_holdout',MIN_HOLDOUT)):
        if type(summary.get(key)) is not int or summary[key]<minimum:
            reasons.append('insufficient_data')
    scores=[summary.get('holdout_log_score'),summary.get('prior_log_score')]
    if any(type(x) not in (int,float) or not math.isfinite(x) or x>0 for x in scores) or scores[0]<=scores[1]:
        reasons.append('heldout_not_better_than_prior')
    return {'accepted':not reasons,'reasons':reasons}

def prepare_data(sets):
    """Training medians only. Missing values get a distinct indicator, never an observed zero."""
    if len({a['profile_hash'] for s in sets for a in s['alternatives']})>1:
        raise PreferenceError('mixed_profiles')
    train=[s for s in sets if not s['holdout']]
    test=[s for s in sets if s['holdout']]
    if len(train)<MIN_TRAIN or len(test)<MIN_HOLDOUT:
        raise PreferenceError('insufficient_data')
    if {a['posting_id'] for s in train for a in s['alternatives']} & {a['posting_id'] for s in test for a in s['alternatives']}:
        raise PreferenceError('split_overlap')
    centers=[]; scales=[]; missing_rates=[]
    for name in NAMES:
        values=[a['features'][name] for s in train for a in s['alternatives'] if a['features'][name] is not None]
        centers.append(statistics.median(values) if values else 0.)
        missing_rates.append(1-len(values)/(3*len(train)))
        # Pay preserves original $5/hour unit; remaining features preserve their documented units.
        scales.append(5. if name in ('pay_low_c','pay_high_c') else 1.)
    transform={'centers':centers,'scales':scales,'names':list(NAMES),'missing_indicators':True,'missing_rates':missing_rates}
    payload={'names':list(NAMES)+[n+'_missing' for n in NAMES], 'families':list(FAMILIES),
             'prior_means':list(PRIOR_MEANS)+[0.]*len(NAMES),'sets':[],'preprocessing':transform}
    for s in sets:
        alternatives=validate_alternatives(s['alternatives'])
        ids=[a['posting_id'] for a in alternatives]
        payload['sets'].append({'id':s['id'],'holdout':s['holdout'],
            'y':4 if s['selected'] is None else ids.index(s['selected'])+1,
            'x':[transform_features(a['features'],transform) for a in alternatives],
            'family':[family_index(a['family']) for a in alternatives],
            'missing':[[a['features'][name] is None for name in NAMES] for a in alternatives]})
    return payload

def transform_features(features,transform):
    values=[features[n] for n in NAMES]
    # Centre pay only; missing non-pay features use train median and a missingness term.
    numeric=[((transform['centers'][i] if v is None else v) - (transform['centers'][i] if NAMES[i] in ('pay_low_c','pay_high_c') else 0))/transform['scales'][i] for i,v in enumerate(values)]
    return numeric+[int(v is None)-transform['missing_rates'][i] for i,v in enumerate(values)]

def fit_store(store, out_dir, context_hash, *, iterations=30000, timeout=600):
    if type(iterations) is not int or not 1000<=iterations<=100000 or type(timeout) not in (int,float) or not 1<=timeout<=3600:
        raise PreferenceError('invalid_fit_limits')
    sets=store.dataset(context_hash)
    payload=prepare_data(sets)
    root=Path(out_dir).resolve()
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    run=root/uuid.uuid4().hex
    run.mkdir(mode=0o700)
    source=Path(__file__).parent
    provenance={'id':run.name,'context_hash':context_hash,'dataset_hash':digest(sets),'versions':versions(),
                'preprocessing':payload['preprocessing'],'origin':store.origin,
                'profile_hash':sets[0]['alternatives'][0]['profile_hash']}
    path=run/'input.json'; output=run/'summary.json'
    path.write_text(canonical({**payload,'provenance':provenance}))
    path.chmod(0o600)
    try:
        # No shell, no network, no prompts/credentials passed through the environment.
        completed=subprocess.run(['Rscript','--vanilla',str(source/'fit_choice_model.R'),str(path),str(output),str(source/'choice_model.jags'),str(iterations)],
            capture_output=True,timeout=timeout,check=False,env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8'})
        if completed.returncode or not output.exists():
            raise PreferenceError('local_fit_failed')
        summary=json.loads(output.read_text())
    except subprocess.TimeoutExpired:
        raise PreferenceError('local_fit_timeout') from None
    except (OSError,ValueError):
        raise PreferenceError('local_fit_failed') from None
    summary.update(provenance)
    summary['gate']=evaluate_fit(summary)
    # Concurrent choices invalidate activation rather than silently entering the fit.
    if store.dataset_hash(context_hash)!=provenance['dataset_hash']:
        summary['gate']={'accepted':False,'reasons':['dataset_changed']}
    output.write_text(canonical(summary)); output.chmod(0o600)
    store.save_fit(summary)
    return summary

def interval(values):
    ordered=sorted(values); count=len(ordered); width=max(1,int(.95*count))
    i=min(range(count-width),key=lambda i:ordered[i+width]-ordered[i]) if count>width else 0
    return {'mean':statistics.mean(values),'hdi_low':ordered[i],'hdi_high':ordered[min(i+width,count-1)]}

def predict_set(store, alternatives, context_hash):
    alternatives=validate_alternatives(alternatives)
    status=store.status(context_hash)
    if status['status']!='valid':
        raise PreferenceError('valid_current_fit_required')
    fit=status['fit']
    if fit.get('origin')!='owner' or fit.get('context_hash')!=context_hash or fit.get('profile_hash')!=alternatives[0]['profile_hash']:
        raise PreferenceError('invalid_fit_provenance')
    draws=fit.get('draws',{}); beta=draws.get('beta',[]); alpha=draws.get('alpha',[])
    if not beta or len(beta)!=len(alpha) or any(len(b)!=len(NAMES)*2 for b in beta) or any(len(a)!=len(FAMILIES) for a in alpha) or any(not math.isfinite(v) for row in beta+alpha for v in row):
        raise PreferenceError('invalid_posterior')
    x=[transform_features(a['features'],fit['preprocessing']) for a in alternatives]
    probabilities=[[] for _ in range(4)]; utilities=[[] for _ in range(3)]
    contributions=[[[] for _ in range(len(NAMES)*2)] for _ in range(3)]
    intercepts=[[] for _ in range(3)]
    for b,a in zip(beta,alpha):
        u=[]
        for j,alt in enumerate(alternatives):
            intercept=a[family_index(alt['family'])-1]; intercepts[j].append(intercept)
            parts=[b[k]*v for k,v in enumerate(x[j])]
            for k,part in enumerate(parts): contributions[j][k].append(part)
            utility=intercept+sum(parts); utilities[j].append(utility); u.append(utility)
        u.append(0.); largest=max(u); exp=[math.exp(v-largest) for v in u]; total=sum(exp)
        for j,v in enumerate(exp): probabilities[j].append(v/total)
    labels=list(NAMES)+[n+'_missing' for n in NAMES]
    predictions=[{'posting_id':alt['posting_id'],'choice_probability':interval(probabilities[j]),
         'utility':interval(utilities[j]),'family_intercept':interval(intercepts[j]),
         'contributions':{name:interval(contributions[j][k]) for k,name in enumerate(labels)},
         'missing_features':[name for name in NAMES if alt['features'][name] is None]} for j,alt in enumerate(alternatives)]
    return {'fit_id':fit['id'],'context_hash':context_hash,'alternatives':predictions,
            'ranking':[p['posting_id'] for p in sorted(predictions,key=lambda p:p['choice_probability']['mean'],reverse=True)],
            'none_probability':interval(probabilities[3]),'meaning':'Probability of an owner choice within this displayed set; not hiring or eligibility probability.'}
