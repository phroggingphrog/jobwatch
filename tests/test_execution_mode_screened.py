from jobwatch.execution_mode import effective_mode


def test_screened_is_an_allowed_mode():
    assert effective_mode({'pipeline': {'execution_mode': 'screened'}}) == 'screened'


def test_legacy_agentic_flag_now_means_screened():
    assert effective_mode({'pipeline': {'agentic': {'enabled': True}}}) == 'screened'
