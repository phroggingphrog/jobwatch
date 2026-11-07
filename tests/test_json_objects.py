"""Behavior shared by reference, mapping and checkpoint JSON readers."""
import json

import pytest

from jobwatch.util.json_objects import unique_object as _unique_object


@pytest.mark.parametrize('payload, expected', [
    ('{}', {}),
    ('{"a": 1, "b": {"a": 2}}', {'a': 1, 'b': {'a': 2}}),
    ('[{"a": 1}, {"a": 2}]', [{'a': 1}, {'a': 2}]),
])
def test_unique_objects_preserve_values_and_independent_key_scopes(payload, expected):
    assert json.loads(payload, object_pairs_hook=_unique_object) == expected


@pytest.mark.parametrize('payload', [
    '{"a": 1, "a": 2}',
    '{"outer": {"a": 1, "a": 2}}',
    '[{"a": 1, "a": 2}]',
    '{"a": 1, "\\u0061": 2}',
])
def test_unique_objects_reject_duplicate_keys_at_every_depth(payload):
    with pytest.raises(ValueError, match='^duplicate key$'):
        json.loads(payload, object_pairs_hook=_unique_object)


def test_reference_parser_rejects_duplicates_before_model_validation():
    from jobwatch.candidate.reference import _parse_reference

    with pytest.raises(ValueError, match='^duplicate key$'):
        _parse_reference(b'{"version":"a","version":"b"}', 'a' * 64)


def test_reference_parser_still_rejects_nonfinite_constants():
    from jobwatch.candidate.reference import _parse_reference

    with pytest.raises(ValueError):
        _parse_reference(b'{"version":NaN}', 'a' * 64)
