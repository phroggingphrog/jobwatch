from jobwatch.candidate import evidence


def test_profile_yaml_is_parsed_once_per_extraction(monkeypatch):
    # /candidate took 2-7 s: PyYAML's pure-Python parser ran twice on the same profile text.
    calls = []
    real = evidence._parse_yaml
    monkeypatch.setattr(evidence, '_parse_yaml', lambda t: calls.append(t) or real(t))
    evidence._extract_primary({'cv.md': b'# A\n\n- Did a thing in 2020.\n', 'profile.yaml': b'candidate:\n  name: Test Person\n'})
    assert len(calls) == 1
