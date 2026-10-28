from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ._private_io import PathEscapeError, read_regular_file
from .contracts import CandidateError, ReferenceBundle, content_hash

_MAX_REFERENCE_BYTES = 32 * 1024 * 1024


def _error(code: str = "reference_invalid") -> CandidateError:
    return CandidateError(code)


def _open_reference(path: Path) -> bytes | None:
    raw = None
    missing = False
    invalid = False
    try:
        raw = read_regular_file(path, _MAX_REFERENCE_BYTES)
    except FileNotFoundError:
        missing = True
    except PathEscapeError:
        invalid = True
    except (OSError, ValueError, UnicodeError):
        invalid = True
    if invalid:
        raise _error()
    return None if missing else raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _parse_reference(raw: bytes, reference_hash: str) -> ReferenceBundle:
    parsed = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(parsed) is not dict or "reference_hash" in parsed:
        raise ValueError("invalid export root")
    return ReferenceBundle(**parsed, reference_hash=reference_hash, raw_contents=raw)


def load_reference(path: Path) -> ReferenceBundle | None:
    raw = _open_reference(Path(path))
    if raw is None:
        return None
    bundle = None
    invalid = False
    try:
        bundle = _parse_reference(raw, content_hash(raw))
    except Exception:
        invalid = True
    if invalid:
        raise _error()
    return bundle


def verify_reference_snapshot(reference: ReferenceBundle) -> None:
    invalid = False
    try:
        raw = reference.raw_contents
        if type(raw) is not bytes or content_hash(raw) != reference.reference_hash:
            raise ValueError
        rebuilt = _parse_reference(raw, content_hash(raw))
        if rebuilt.model_dump(mode="json") != reference.model_dump(mode="json"):
            raise ValueError
    except Exception:
        invalid = True
    if invalid:
        raise _error()


def crosswalk_codes(reference: ReferenceBundle, soc: str) -> tuple[str, ...]:
    verify_reference_snapshot(reference)
    if type(soc) is not str:
        raise _error()
    matches = [code for crosswalk in reference.crosswalks if crosswalk.soc == soc for code in crosswalk.anzsco_codes]
    return tuple(sorted(set(matches)))
