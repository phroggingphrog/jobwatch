"""Human rule amendments preserve approved evidence and version history."""
import copy
import pytest
from jobwatch import users
from jobwatch.candidate import intake, rules
from jobwatch.candidate.contracts import digest
from jobwatch.candidate.policy import policy_for
from tests.baseline_support import world


def test_add_withdraw_retry_and_immutable_history(world):
    _, config, _, _ = world
    person = users.current()
    original = copy.deepcopy(intake.current_version(person))
    shown = rules.propose(config, kind='employer', value='Example Employer', request_id='add-one', actor='person')
    assert intake.current_version(person) == original
    result = rules.confirm(config, shown['id'], rule_digest=shown['digest'], actor='person')
    current = intake.current_version(person)
    assert result['version'] == original['version'] + 1
    assert digest(current) != digest(original)
    assert current['evidence_bundle_hash'] == original['evidence_bundle_hash']
    assert current['scope'] == original['scope']
    from jobwatch.candidate.approved import settings
    from pipeline.agentic.service import _approved_evidence
    assert settings(person, 'profile.yaml')
    assert 'Example Employer' in settings(person, 'interests_and_criteria.yaml')['target_roles']['not_wanted']
    assert _approved_evidence(person).bundle_hash == original['evidence_bundle_hash']
    assert intake._approved(person, original['version']) == original
    assert rules.confirm(config, shown['id'], rule_digest=shown['digest'], actor='person') == result
    rule = next(r for r in policy_for(person).exclusions if r.value == 'Example Employer')
    withdraw = rules.propose(config, op='withdraw', rule_id=rule.rule_id, request_id='withdraw-one', actor='person')
    rules.confirm(config, withdraw['id'], rule_digest=withdraw['digest'], actor='person')
    assert not any(r.value == 'Example Employer' for r in policy_for(person).exclusions)
    assert intake.discovery_scope(person) is not None


def test_digest_races_payload_conflicts_and_identity(world):
    _, config, _, _ = world
    a = rules.propose(config, kind='location', value='Sydney', request_id='a', actor='person')
    b = rules.propose(config, kind='title_term', value='Manager', request_id='b', actor='person')
    with pytest.raises(rules.RuleError, match='rule_changed'):
        rules.confirm(config, a['id'], rule_digest='wrong', actor='person')
    with pytest.raises(rules.RuleError, match='idempotency_conflict'):
        rules.propose(config, kind='location', value='Perth', request_id='a', actor='person')
    with pytest.raises(rules.RuleError, match='person_required'):
        rules.confirm(config, a['id'], rule_digest=a['digest'], actor='model')
    with users.use('other-person'):
        with pytest.raises(rules.RuleError, match='not_found'):
            rules.confirm(config, a['id'], rule_digest=a['digest'], actor='person')
    rules.confirm(config, a['id'], rule_digest=a['digest'], actor='person')
    with pytest.raises(rules.RuleError, match='profile_changed'):
        rules.confirm(config, b['id'], rule_digest=b['digest'], actor='person')


@pytest.mark.parametrize('kind,value', [('family','invented'), ('work_type','sometimes'), ('bad','x'), ('employer','')])
def test_invalid_rule_is_not_a_draft(world, kind, value):
    with pytest.raises(rules.RuleError, match='invalid_rule'):
        rules.propose(world[1], kind=kind, value=value, request_id='invalid', actor='person')


def test_active_rules_survive_later_full_profile_confirmation(world):
    _, config, _, _ = world
    person = users.current()
    shown = rules.propose(config, kind='work_type', value='Casual', request_id='rule', actor='person')
    rules.confirm(config, shown['id'], rule_digest=shown['digest'], actor='person')
    old = intake.current_version(person)
    facts = [intake.ProfileFact.model_validate(f, strict=False) for f in old['facts'] if f['section'] != 'exclusion']
    draft = intake.Proposal(id='abcdef1234567890',revision=1,base_version=old['version'],uploads=(),
                            facts=tuple(facts),questions=(),status='draft')
    intake.save_proposal(person,draft)
    confirmation = intake.confirmation(person,draft.id,config)
    intake.confirm(person,draft.id,proposal_digest=confirmation['proposal_digest'],
                   scope_digest=confirmation['scope_digest'],actor='person',config=config)
    assert any(r.kind == 'work_type' and r.value == 'casual' for r in policy_for(person).exclusions)


def test_confirmation_recovers_projection_without_minting_another_version(world, monkeypatch):
    _, config, _, _ = world
    person = users.current()
    shown = rules.propose(config,kind='employer',value='Example',request_id='crash',actor='person')
    rename = intake.os.rename
    state = {'failed': False}
    def publish_then_crash(source, dest):
        rename(source, dest)
        if not state['failed']:
            state['failed'] = True
            raise OSError('synthetic crash after version publication')
    monkeypatch.setattr(intake.os, 'rename', publish_then_crash)
    with pytest.raises(OSError):
        rules.confirm(config,shown['id'],rule_digest=shown['digest'],actor='person')
    version = intake.current_version(person)['version']
    monkeypatch.setattr(intake.os, 'rename', rename)
    assert rules.confirm(config,shown['id'],rule_digest=shown['digest'],actor='person')['version'] == version
    assert intake.discovery_scope(person) is not None
