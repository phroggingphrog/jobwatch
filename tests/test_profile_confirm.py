"""`jobwatch profile confirm` is the person's own approval step, and it refuses a scope it cannot honour."""
import io
import types

import pytest

from jobwatch import users
from jobwatch.candidate import intake
from jobwatch.commands import profile as profile_cmd


def _proposal(monkeypatch, tmp_path, *, with_location=True):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    pdir = tmp_path / "profile"
    pdir.mkdir(exist_ok=True)
    (pdir / "cv.md").write_text("Synthetic CV")
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(pdir))
    person = users.current()
    facts = [intake.ProfileFact(id="f" * 16, section="career_focus", value="accounts and payroll",
                                basis=intake.Basis.EVIDENCE)]
    if with_location:
        facts.append(intake.ProfileFact(id="g" * 16, section="location", value="Melbourne VIC",
                                        basis=intake.Basis.EVIDENCE))
    proposal = intake.Proposal(id="a" * 16, revision=1, base_version=None, uploads=(),
                               facts=tuple(facts), questions=(), status="draft")
    intake.save_proposal(person, proposal)
    return person, proposal


def _args(proposal_id, yes):
    return types.SimpleNamespace(cmd="profile", action="confirm", proposal_id=proposal_id, yes=yes)


def test_an_unusable_scope_is_refused_before_anything_is_written(monkeypatch, tmp_path, capsys):
    person, proposal = _proposal(monkeypatch, tmp_path, with_location=False)
    assert profile_cmd.handle(_args(proposal.id, True)) == 1
    assert "refused" in capsys.readouterr().err
    assert intake.current_version(person) is None


def test_a_typed_no_changes_nothing(monkeypatch, tmp_path, capsys):
    person, proposal = _proposal(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("no\n"))
    assert profile_cmd.handle(_args(proposal.id, False)) == 1
    assert intake.current_version(person) is None
    assert intake.discovery_scope(person) is None


def test_adopt_then_confirm_opens_discovery(monkeypatch, tmp_path, capsys):
    """The real chain: adopt the existing files as version 1, then confirm the proposal as version 2."""
    person, proposal = _proposal(monkeypatch, tmp_path)
    (tmp_path / "profile" / "profile.yaml").write_text("candidate: {}")
    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 0
    assert intake.current_version(person)["version"] == 1
    assert intake.discovery_scope(person) is None            # adopt alone authorises nothing

    proposal = intake.Proposal(id=proposal.id, revision=1, base_version=1, uploads=(),
                               facts=proposal.facts, questions=(), status="draft")
    intake.save_proposal(person, proposal)
    assert profile_cmd.handle(_args(proposal.id, True)) == 0
    assert "discovery scope is now open" in capsys.readouterr().out
    live = intake.discovery_scope(person)
    assert live is not None and live.locations == ("Melbourne VIC",)


def test_confirm_refuses_before_adopt(monkeypatch, tmp_path, capsys):
    """Confirming a proposal before any version exists must name the missing step, not fail obscurely."""
    person, proposal = _proposal(monkeypatch, tmp_path)
    assert profile_cmd.handle(_args(proposal.id, True)) == 1
    assert "adopt_first" in capsys.readouterr().err
    assert intake.current_version(person) is None


def test_confirm_without_an_id_prints_usage(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    assert profile_cmd.handle(_args(None, True)) == 1
    assert "usage: jobwatch profile confirm" in capsys.readouterr().err


def test_drifted_annotations_do_not_block_adoption(monkeypatch, tmp_path):
    """A person's curated annotations must never block adoption, and their file is never rewritten."""
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    pdir = tmp_path / "profile"
    pdir.mkdir()
    (pdir / "master_resume.md").write_text("Synthetic CV. Reconciled ledgers with MYOB.")
    (pdir / "cv.md").write_text("Synthetic CV. Reconciled ledgers with MYOB.")
    (pdir / "profile.yaml").write_text("candidate: {}\n")
    drifted = pdir / "evidence.yaml"
    drifted.write_text('schema_version: 1\nitems:\n  - id: deadbeefdeadbeef\n')
    before = drifted.read_bytes()
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(pdir))
    person = users.current()

    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 0

    approved = intake.current_version(person)
    assert approved["version"] == 1
    assert approved["evidence_excluded"]["reason"] == "annotation_invalid"
    assert approved["evidence_bundle_hash"] is None
    assert drifted.read_bytes() == before                   # the person's file is untouched


def _profile(tmp_path, monkeypatch, *, cv_text="Synthetic CV", symlink=None):
    monkeypatch.setenv("JOBWATCH_DATA_DIR", str(tmp_path))
    pdir = tmp_path / "profile"
    pdir.mkdir()
    (pdir / "master_resume.md").write_text(cv_text)
    (pdir / "profile.yaml").write_text("candidate: {}\n")
    if symlink is not None:
        (pdir / "cv.md").symlink_to(symlink)
    else:
        (pdir / "cv.md").write_text(cv_text)
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(pdir))
    return pdir


def test_scope_state_names_the_reason_instead_of_returning_none(monkeypatch, tmp_path):
    _profile(tmp_path, monkeypatch)
    person = users.current()
    assert intake.scope_state(person) == (None, "no_profile_version")
    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 0
    assert intake.scope_state(person) == (None, "no_confirmed_scope")   # adopted, still not authorised


def test_a_symlink_inside_the_profile_is_adopted(monkeypatch, tmp_path):
    """cv.md -> master_resume.md is a normal layout, not a hand edit."""
    pdir = _profile(tmp_path, monkeypatch, symlink="master_resume.md")
    assert (pdir / "cv.md").is_symlink()
    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 0
    assert intake.current_version(users.current())["adopted_files"]


def test_a_symlink_leaving_the_profile_is_refused(monkeypatch, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("not mine to adopt")
    pdir = _profile(tmp_path, monkeypatch, symlink=str(outside))
    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 1
    assert intake.current_version(users.current()) is None


def test_adopting_again_records_the_next_version(monkeypatch, tmp_path, capsys):
    """A repair must not be stranded: adopt twice, keep both versions."""
    pdir = _profile(tmp_path, monkeypatch)
    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 0
    (pdir / "master_resume.md").write_text("Synthetic CV, repaired")
    assert profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt")) == 0
    assert "version 2" in capsys.readouterr().out
    assert intake.current_version(users.current())["version"] == 2
    assert (tmp_path / "profile-versions" / "1").is_dir()


def test_a_hand_edit_reports_itself_rather_than_looking_unconfirmed(monkeypatch, tmp_path):
    """Once a scope exists, a hand edit must name itself instead of masquerading as an unconfirmed profile."""
    person, proposal = _proposal(monkeypatch, tmp_path)
    pdir = tmp_path / "profile"
    (pdir / "master_resume.md").write_text("Synthetic CV")
    profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt"))
    proposal = intake.Proposal(id=proposal.id, revision=1, base_version=1, uploads=(),
                               facts=proposal.facts, questions=(), status="draft")
    intake.save_proposal(person, proposal)
    assert profile_cmd.handle(_args(proposal.id, True)) == 0
    assert intake.scope_state(person)[1] == "ok"
    (pdir / "master_resume.md").write_text("edited by hand after confirmation")
    assert intake.scope_state(person) == (None, "profile_edited_by_hand")


def test_confirm_never_rewrites_the_resume_or_drops_evidence(monkeypatch, tmp_path):
    """The profile is the gold data: confirming a target change may derive files, never replace source documents."""
    person, proposal = _proposal(monkeypatch, tmp_path)
    pdir = tmp_path / "profile"
    cv = "Synthetic CV written by the person, with detail a parser may miss."
    (pdir / "master_resume.md").write_text(cv)
    evidence = pdir / "evidence.yaml"
    evidence.write_text("schema_version: 1\nitems: []\n")
    profile_cmd.handle(types.SimpleNamespace(cmd="profile", action="adopt"))

    live = intake.current_version(person)
    proposal = intake.Proposal(id=proposal.id, revision=1, base_version=live["version"], uploads=(),
                               facts=proposal.facts, questions=(), status="draft")
    intake.save_proposal(person, proposal)
    assert profile_cmd.handle(_args(proposal.id, True)) == 0

    assert (pdir / "master_resume.md").read_text() == cv      # the person's own words survive
    assert evidence.exists() and evidence.read_text().strip()  # annotations are never deleted
    assert intake.scope_state(person)[1] == "ok"  # unchanged adopted inputs retain discovery scope
    assert intake.current_version(person)["file_sha256"].get("evidence.yaml")
