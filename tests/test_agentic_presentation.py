from pipeline.agentic.presentation import guidance


def test_presentation_guidance_defaults_to_markdown(monkeypatch):
    monkeypatch.delenv('JOBWATCH_UI_FORMAT', raising=False)
    text = guidance()
    assert 'GFM table' in text and 'mermaid' in text
    assert ':::artifact' not in text
    assert 'approves an operation' in text


def test_artifact_guidance_is_opt_in_and_has_no_authority(monkeypatch):
    monkeypatch.setenv('JOBWATCH_UI_FORMAT', 'artifacts')
    text = guidance()
    assert ':::artifact' in text
    assert '```html' in text and '<!doctype html>' in text
    assert 'No external resources, network requests, imports or credentials.' in text
    assert 'No fake upload controls, host messages,' in text
    assert 'approval buttons or Submit buttons.' in text
    assert 'Never put personal facts in one' in text
    assert 'no authority over Jobwatch state' in text
