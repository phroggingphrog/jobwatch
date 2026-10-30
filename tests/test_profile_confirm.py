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
