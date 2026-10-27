"""A person-bound Evaluation combo does not replace candidate understanding."""
import sqlite3
import hashlib
from pathlib import Path

import pytest

from jobwatch import model_choice as mc
from jobwatch import users
from pipeline.agentic import service
from pipeline.agentic import autonomous
from pipeline.agentic.autonomous import evaluate_autonomous
from test_agentic_evaluate import build_case, budget
from test_autonomous_evaluation import native_choices, transport
from test_agentic_service import world

COMBO = 'jobwatch-assessment-deepseek'


def profile(revision=None):
    revision = revision or hashlib.sha256((Path(autonomous.__file__).with_name('prompts') /
        'native-assessment-protocol.txt').read_bytes()).hexdigest()
    return {'native_tools': True, 'json_mode': False, 'min_output_tokens': 16000,
            'assessment_combo': COMBO, 'assessment_prompt_hash': revision}


def test_combo_routes_actual_native_requests_without_changing_role_picks(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'person'))
    before = mc.chosen()
    mc.set_gateway_profile('deepseek-flash', profile())
    mc.set_gateway_profile(COMBO, {'native_tools': True, 'json_mode': False, 'min_output_tokens': 16000})
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport(native_choices(roles))
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        result = evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
            screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert all(body['model'] == COMBO and 'response_format' not in body for body in seen)
    assert all('You are the dedicated Evaluation agent' in body['messages'][0]['content'] for body in seen)
    assert all(body['messages'][0]['content'].count('You are serving Jobwatch') == 1 for body in seen)
    assert result.matching_diagnostics['model'] == COMBO
    assert mc.chosen() == before


def test_unpublished_prompt_revision_cannot_dispatch(tmp_path, monkeypatch):
    from pipeline.agentic.runtime import RuntimeErrorSafe
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path / 'person'))
    mc.set_gateway_profile('deepseek-flash', profile('0' * 64))
    bundle, ad, key, roles = build_case(tmp_path / 'evidence')
    llm, seen = transport(native_choices(roles))
    with sqlite3.connect(':memory:', check_same_thread=False) as conn:
        with pytest.raises(RuntimeErrorSafe, match='invalid_configuration'):
            evaluate_autonomous(key, ad, budget(key), llm, conn=conn, posting={},
                screen={'outcome': 'admit'}, evidence_bundle=bundle, model='deepseek-flash')
    assert seen == []


def test_combo_prompt_changes_job_identity_but_not_current_digest(world, monkeypatch):
    from test_candidate_digest import inputs, transport as digest_transport, budget as digest_budget
    from pipeline.agentic import candidate_digest as cd
    conn, config, bundle, add = world
    config.settings['pipeline']['agentic']['autonomous_evaluation'] = True
    conn, args = inputs(world)
    calls = digest_transport(monkeypatch, bundle)
    ready = cd.ensure_digest(conn, **args, budget=digest_budget(), llm=object())
    add(42)
    first = service.snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)
    base = args['cfg']['evaluator_model']
    mc.set_gateway_profile(base, profile())
    changed = service.snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)
    assert changed[0]['run_key'] != first[0]['run_key']
    assert cd.current_digest(conn, **args).identity == ready.identity
    mc.set_gateway_profile(base, profile('2' * 64))
    rotated = service.snapshot_inventory(conn, config, posting_ids=[42], evidence_bundle=bundle)
    assert rotated[0]['run_key'] != changed[0]['run_key']
    assert cd.current_digest(conn, **args).identity == ready.identity
    assert len(calls) == 2
    with users.use('synthetic-other'):
        assert mc.native_assessment_route(base) == {'model': base, 'prompt_hash': None}


@pytest.mark.parametrize('invalid', [
    {'assessment_combo': COMBO},
    {'assessment_prompt_hash': '1' * 64},
    {'assessment_combo': '../bad', 'assessment_prompt_hash': '1' * 64},
    {'assessment_combo': COMBO, 'assessment_prompt_hash': 'bad'},
])
def test_incomplete_or_invalid_combo_binding_is_rejected_before_write(tmp_path, monkeypatch, invalid):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    with pytest.raises(mc.ModelRefused):
        mc.set_gateway_profile('deepseek-flash', invalid)
    assert not (users.user_dir() / 'config' / 'model_profiles.json').exists()
