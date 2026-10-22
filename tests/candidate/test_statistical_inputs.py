import json
from pathlib import Path
import pytest
from jobwatch.candidate.contracts import CandidateError
from jobwatch.candidate.evidence import snapshot_evidence
from jobwatch.candidate.inputs import load_inputs
from jobwatch.candidate.analysis import analyse_candidate, structural_summary
from jobwatch.candidate.policy import default_policy
from jobwatch.candidate.presentation import statistical_view
from tests.candidate.fixtures import fictional_profile, fictional_reference
from pipeline.agentic.service import _config, _run_key


def world(tmp_path):
    bundle = snapshot_evidence(fictional_profile(tmp_path))
    ref = fictional_reference(tmp_path)
    cfg = _config({'agentic': {'occupation_reference_path': str(ref)}})
    return bundle, ref, cfg


def key(bundle, cfg):
    return _run_key(1, ({'title':'Synthetic'}, 'Complete synthetic advert', 'full'), bundle, default_policy(), cfg).value


def test_reference_change_invalidates_runtime_identity(tmp_path):
    bundle, ref, cfg = world(tmp_path)
    before = key(bundle,cfg)
    data = json.loads(ref.read_text()); data['version'] = 'fixture-v2'; ref.write_text(json.dumps(data))
    assert key(bundle,cfg) != before


def test_mapping_state_change_invalidates_identity_and_recommendations(tmp_path):
    bundle, ref, cfg = world(tmp_path)
    reference, _ = load_inputs(bundle,cfg)
    item = bundle.items[0]
    records = [{'evidence_id':item.id, 'source_hash':item.source_hash, 'reference_hash':reference.reference_hash,
                'dwa_id':'test.accounts', 'method':'verified-test', 'state':'suggested'}]
    path=tmp_path/'mappings.json'; path.write_text(json.dumps(records));cfg['occupation_mappings_path']=str(path)
    before=key(bundle,cfg)
    assert not analyse_candidate(bundle,*load_inputs(bundle,cfg),default_policy()).recommendations
    records[0]['state']='confirmed';path.write_text(json.dumps(records))
    assert key(bundle,cfg)!=before
    assert analyse_candidate(bundle,*load_inputs(bundle,cfg),default_policy()).recommendations
    records[0]['source_hash']='0'*64;path.write_text(json.dumps(records))
    with pytest.raises(CandidateError,match='mapping_invalid'):load_inputs(bundle,cfg)


def test_missing_explicit_reference_fails_closed(tmp_path):
    bundle,_,cfg=world(tmp_path);cfg['occupation_reference_path']=str(tmp_path/'absent.json')
    with pytest.raises(CandidateError,match='reference_unavailable'):load_inputs(bundle,cfg)


def test_mapping_file_rejects_duplicates_and_symlinks(tmp_path):
    bundle,_,cfg=world(tmp_path)
    path=tmp_path/'maps.json';path.write_text('[{"state":"confirmed","state":"suggested"}]')
    cfg['occupation_mappings_path']=str(path)
    with pytest.raises(CandidateError,match='mapping_invalid'):load_inputs(bundle,cfg)
    link=tmp_path/'link.json';link.symlink_to(path);cfg['occupation_mappings_path']=str(link)
    with pytest.raises(CandidateError,match='mapping_invalid'):load_inputs(bundle,cfg)


def test_public_reference_suggestions_never_become_confirmed_paths(tmp_path):
    from jobwatch.candidate.contracts import KNOWN_FAMILIES
    root=tmp_path/'profile';root.mkdir()
    (root/'cv.md').write_text('# Synthetic\n\n## Skills\n- Prepare financial reports and reconcile financial accounts\n')
    bundle=snapshot_evidence(root)
    reference,maps=load_inputs(bundle,{})
    assert len(reference.occupations)>1000 and len(reference.dwas)>2000
    assert maps and {m.state for m in maps}=={'suggested'}
    analysis=analyse_candidate(bundle,reference,maps,default_policy())
    assert not analysis.recommendations
    assert len(json.dumps(structural_summary(analysis)))<15000
    view=statistical_view(bundle,{})
    assert view['suggested_count']>0 and view['confirmed_count']==0
    # Reference classification is not an inherited personal exclusion.
    assert all(f['family'] in KNOWN_FAMILIES for f in view['fits'])


def test_reference_policy_does_not_promote_counter_or_delivery_roles():
    from jobwatch.candidate.reference import load_reference
    reference=load_reference(Path('jobwatch/candidate/data/occupation-reference.json'))
    by_code={o.code:o for o in reference.occupations}
    assert by_code['221111'].family=='accounting'
    assert by_code['551311'].family=='finance_clerical'
    assert by_code['561111'].family=='other'
    assert by_code['561211'].family=='other'
    assert by_code['431111'].excluded


def test_details_are_complete_and_unknown_code_rejected(tmp_path):
    from jobwatch.candidate.assessment import occupation_details
    bundle,_,cfg=world(tmp_path)
    analysis=analyse_candidate(bundle,*load_inputs(bundle,cfg),default_policy())
    fit=next(f for f in analysis.diagnostics if f.code=='221111')
    assert occupation_details(analysis,('221111',))['fits']==[fit.model_dump(mode='json')]
    with pytest.raises(Exception,match='unknown_occupation'):occupation_details(analysis,('999999',))
