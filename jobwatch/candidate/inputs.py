"""One bounded, immutable input snapshot for runtime, cache identity and UI."""
from __future__ import annotations

import json
from pathlib import Path

from ._private_io import read_regular_file
from .contracts import CandidateError, Mapping
from .mapping import validate_mappings
from .suggestions import suggest_mappings
from .reference import load_reference, _unique_object


def load_inputs(bundle, config: dict):
    reference_path = config.get('occupation_reference_path')
    mapping_path = config.get('occupation_mappings_path')
    if reference_path is None:
        reference_path = str(Path(__file__).with_name('data') / 'occupation-reference.json')
    if type(reference_path) is not str or not reference_path.strip():
        raise CandidateError('reference_invalid')
    reference = load_reference(Path(reference_path))
    if reference is None:
        if config.get('occupation_reference_path') is not None or mapping_path is not None:
            raise CandidateError('reference_unavailable')
        return None, ()
    if mapping_path is None:
        return reference, suggest_mappings(bundle, reference)
    failed = False
    try:
        if type(mapping_path) is not str or not mapping_path.strip():
            raise ValueError
        raw = read_regular_file(Path(mapping_path), 4 * 1024 * 1024)
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        if type(data) is not list:
            raise ValueError
        mappings = tuple(Mapping.model_validate(record) for record in data)
        return reference, validate_mappings(bundle, reference, mappings)
    except Exception:
        failed = True
    if failed:
        raise CandidateError('mapping_invalid') from None
