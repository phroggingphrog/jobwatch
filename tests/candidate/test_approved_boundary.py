import json

import pytest

from jobwatch import reader, users
from jobwatch.candidate import approved, intake, person, policy, projection
from jobwatch.candidate.contracts import CandidateError
from jobwatch.candidate.evidence import snapshot_evidence
from pipeline.agentic import service


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path / 'profile'))
    who = users.current()
    root = intake._versions_root(who) / '1'
    (root / 'evidence').mkdir(parents=True)
    (root / 'evidence' / 'master_resume.md').write_text('Synthetic accounts clerk. Policy: part-time only.\n')
    record = {'version': 1, 'facts': [], 'evidence_bundle_hash': snapshot_evidence(root / 'evidence').bundle_hash}
    (root / 'approved.json').write_text(json.dumps(record))
    for name, text in projection.project(record).items():
        (root / name).write_text(text)
    live = tmp_path / 'profile'
    live.mkdir()
    (live / 'master_resume.md').write_text('Unapproved replacement')
    return who, root, live


def test_evidence_uses_approved_policy_not_live_input(published):
    who, root, live = published
    before = (live / 'master_resume.md').read_bytes()
    bundle = service._approved_evidence(who)
    assert b'Policy: part-time only.' in bundle.contents['master_resume.md']
    assert (live / 'master_resume.md').read_bytes() == before


def test_no_approval_never_falls_back_to_live_input(tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('JOBWATCH_PROFILE_DIR', str(tmp_path / 'profile'))
    (tmp_path / 'profile').mkdir()
    (tmp_path / 'profile' / 'cv.md').write_text('Unapproved CV')
    with pytest.raises(CandidateError, match='no_profile_version'):
        service._approved_evidence(users.current())


@pytest.mark.parametrize('damage', ['missing', 'changed', 'invalid_annotation'])
def test_evidence_damage_blocks_assessment(published, damage):
    who, root, _ = published
    source = root / 'evidence' / 'master_resume.md'
    if damage == 'missing':
        source.unlink()
    elif damage == 'changed':
        source.write_text('Changed after approval')
    else:
        (root / 'evidence' / 'evidence.yaml').write_text('items: [invalid annotation]\n')
    with pytest.raises(CandidateError):
        service._approved_evidence(who)


@pytest.mark.parametrize('name', ['profile.yaml', 'interests_and_criteria.yaml'])
@pytest.mark.parametrize('damage,reason', [('missing', 'missing'), ('corrupt', 'invalid'), ('changed', 'changed')])
def test_restriction_damage_never_becomes_neutral(published, name, damage, reason):
    who, root, live = published
    path = root / name
    (live / name).write_text('candidate: {}\n')
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text('[' if damage == 'corrupt' else 'candidate: {}\n')
    with pytest.raises(CandidateError, match='approved_restrictions_' + reason):
        person._yaml(name)
    if name == 'interests_and_criteria.yaml':
        with pytest.raises(CandidateError, match='approved_restrictions_' + reason):
            reader._interests()


def test_corrupt_approval_blocks_readers(published):
    who, root, _ = published
    (root / 'approved.json').write_text('{')
    with pytest.raises(CandidateError, match='approved_profile_invalid'):
        approved.evidence(who)
    with pytest.raises(CandidateError, match='approved_profile_invalid'):
        policy.policy_for(who)
