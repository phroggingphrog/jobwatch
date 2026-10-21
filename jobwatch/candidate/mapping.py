from __future__ import annotations

from .contracts import CandidateError, EvidenceBundle, Mapping, ReferenceBundle
from .evidence import verify_evidence_snapshot
from .reference import verify_reference_snapshot


def _error(code: str = "mapping_invalid") -> CandidateError:
    return CandidateError(code)


def validate_mappings(
    bundle: EvidenceBundle,
    reference: ReferenceBundle,
    mappings: tuple[Mapping, ...],
) -> tuple[Mapping, ...]:
    invalid = False
    duplicate = False
    validated: tuple[Mapping, ...] = ()
    try:
        verify_evidence_snapshot(bundle)
        verify_reference_snapshot(reference)
        if type(mappings) is not tuple or any(not isinstance(m, Mapping) for m in mappings):
            raise ValueError
        mappings = tuple(Mapping.model_validate(m.model_dump(mode="python")) for m in mappings)
        pairs = [(m.evidence_id, m.dwa_id) for m in mappings]
        if len(set(pairs)) != len(pairs):
            duplicate = True
            raise ValueError
        items = {item.id: item for item in bundle.items}
        dwas = {dwa.id for dwa in reference.dwas}
        per_evidence: dict[str, int] = {}
        for mapping in mappings:
            item = items.get(mapping.evidence_id)
            if item is None or mapping.dwa_id not in dwas:
                raise ValueError
            if mapping.source_hash != item.source_hash or mapping.reference_hash != reference.reference_hash:
                raise ValueError
            per_evidence[mapping.evidence_id] = per_evidence.get(mapping.evidence_id, 0) + 1
            if per_evidence[mapping.evidence_id] > 3:
                raise ValueError
        validated = tuple(sorted(mappings, key=lambda m: (m.evidence_id, m.dwa_id, m.method, m.state)))
    except Exception:
        invalid = True
    if invalid:
        raise _error("mapping_duplicate" if duplicate else "mapping_invalid")
    return validated
