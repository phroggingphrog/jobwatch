from jobwatch.execution_mode import effective_mode


def test_screened_is_an_allowed_mode():
    assert effective_mode({'pipeline': {'execution_mode': 'screened'}}) == 'screened'
