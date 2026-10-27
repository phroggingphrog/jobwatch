from types import SimpleNamespace

from jobwatch import profile_check


def test_confirmed_region_does_not_require_an_invented_home_location(tmp_path, monkeypatch):
    (tmp_path / 'profile.yaml').write_text('candidate:\n  location: ""\n  work_rights:\n    citizen_or_pr: false\n')
    monkeypatch.setattr('jobwatch.apply.paths.profile_dir', lambda: tmp_path)
    monkeypatch.setattr('jobwatch.candidate.policy.policy_for', lambda _: SimpleNamespace(regions=('VIC',)))
    assert not any('candidate.location' in p for p in profile_check.check())
    # An explicitly checked standalone profile cannot inherit another person's policy.
    assert any('candidate.location' in p for p in profile_check.check(profile_dir=tmp_path))
