from __future__ import annotations

import math

from .contracts import (
    AnalysisResult,
    ArchetypeProposal,
    CandidateError,
    EvidenceBundle,
    Mapping,
    Occupation,
    OccupationFit,
    ReferenceBundle,
    TargetPolicy,
    digest,
)
from .evidence import verify_evidence_snapshot
from .mapping import validate_mappings
from .reference import verify_reference_snapshot


STRUCTURAL_VERSION = "structural-confirmed-policy-v2"


def _error(code: str) -> CandidateError:
    return CandidateError(code)


def _cosine(candidate: dict[str, float], target: dict[str, float]) -> float:
    denominator = math.sqrt(sum(v * v for v in candidate.values()) * sum(v * v for v in target.values()))
    if not denominator:
        return 0.0
    return max(0.0, min(1.0, sum(v * target.get(k, 0.0) for k, v in candidate.items()) / denominator))


def _clusters(fits: tuple[OccupationFit, ...], occupations: dict[str, Occupation], supported_gwas: set[str]) -> tuple[ArchetypeProposal, ...]:
    proposals: list[ArchetypeProposal] = []
    for status in ("candidate_path", "diagnostic"):
        selected = [
            fit for fit in fits
            if fit.proximity > 0.0
            and ((fit.recommendation_status == "candidate_path") if status == "candidate_path"
                 else (fit.recommendation_status != "candidate_path"))
        ]
        # The cap applies globally to each policy partition, before grouping.
        selected.sort(key=lambda fit: (-fit.proximity, fit.code))
        seeds_by_prefix: dict[str, list[OccupationFit]] = {}
        for fit in selected[:30]:
            seeds_by_prefix.setdefault(fit.code[:3], []).append(fit)
        for seeds in seeds_by_prefix.values():
            remaining = list(seeds)
            while remaining:
                cluster = [remaining.pop(0)]
                common = {
                    gwa for gwa, rating in occupations[cluster[0].code].gwa_ratings.items()
                    if rating >= 3.5 and gwa in supported_gwas
                }
                while common:
                    addition = next((
                        fit for fit in remaining
                        if common & {gwa for gwa, rating in occupations[fit.code].gwa_ratings.items() if rating >= 3.5}
                    ), None)
                    if addition is None:
                        break
                    cluster.append(addition)
                    remaining.remove(addition)
                    common &= {
                        gwa for gwa, rating in occupations[addition.code].gwa_ratings.items()
                        if rating >= 3.5 and gwa in supported_gwas
                    }
                if common:
                    proposals.append(ArchetypeProposal(
                        codes=tuple(sorted(f.code for f in cluster)),
                        evidence_ids=tuple(sorted({i for f in cluster for i in f.evidence_ids})),
                        shared_gwa_ids=tuple(sorted(common)),
                        policy_status="candidate_path" if status == "candidate_path" else "diagnostic",
                    ))
    return tuple(sorted(proposals, key=lambda p: (p.policy_status, p.codes)))


def analyse_candidate(
    bundle: EvidenceBundle,
    reference: ReferenceBundle | None,
    mappings: tuple[Mapping, ...],
    policy: TargetPolicy,
) -> AnalysisResult:
    """Build deterministic structural fits after revalidating all bound inputs."""
    try:
        verify_evidence_snapshot(bundle)
        evidence = EvidenceBundle.model_validate(bundle.model_dump(mode="python") | {"contents": dict(bundle.contents)})
        safe_policy = TargetPolicy.model_validate(policy.model_dump(mode="python"))
        if reference is None:
            if type(mappings) is not tuple or mappings:
                raise _error("mapping_unresolved")
            mapping_records: tuple[Mapping, ...] = ()
            ref_hash = None
            occupations: tuple[Occupation, ...] = ()
            status = "reference_unavailable"
        else:
            verify_reference_snapshot(reference)
            safe_reference = ReferenceBundle.model_validate(reference.model_dump(mode="python") | {"raw_contents": reference.raw_contents})
            if type(mappings) is not tuple:
                raise _error("mapping_invalid")
            mapping_records = validate_mappings(evidence, safe_reference, mappings)
            ref_hash = safe_reference.reference_hash
            occupations = safe_reference.occupations
            status = "available" if mapping_records else "unmapped"
    except CandidateError:
        raise
    except Exception:
        invalid = True
    else:
        invalid = False

    if invalid:
        raise _error("candidate_invalid")

    if reference is None:
        eh = evidence.bundle_hash
        ph = digest(safe_policy.model_dump(mode="json"))
        mh = digest([])
        run = digest({"implementation": STRUCTURAL_VERSION, "evidence": eh, "reference": None, "mappings": mh, "policy": ph, "clusters": []})
        return AnalysisResult(
            archetypes=(), run_key=run, evidence_hash=eh, reference_hash=None,
            policy_hash=ph, mapping_hash=mh, status=status,
            recommendations=(), diagnostics=(), unmapped_evidence_ids=(),
        )

    item_by_id = {item.id: item for item in evidence.items}
    dwa_to_gwa = {d.id: d.gwa_id for d in safe_reference.dwas}
    mapped_ids = {m.evidence_id for m in mapping_records}
    unmapped_ids = tuple(sorted(set(item_by_id) - mapped_ids))
    mapped_dwas: set[str] = set()
    confirmed_non_education: set[str] = set()
    states_by_dwa: dict[str, set[str]] = {}
    ids_by_dwa: dict[str, set[str]] = {}
    gwa_evidence: dict[str, set[str]] = {}
    for mapping in mapping_records:
        item = item_by_id[mapping.evidence_id]
        mapped_dwas.add(mapping.dwa_id)
        ids_by_dwa.setdefault(mapping.dwa_id, set()).add(item.id)
        states_by_dwa.setdefault(mapping.dwa_id, set()).add(mapping.state)
        gwa_evidence.setdefault(dwa_to_gwa[mapping.dwa_id], set()).add(item.id)
        if mapping.state == "confirmed" and item.kind not in ("education", "cert"):
            confirmed_non_education.add(mapping.dwa_id)
    candidate_gwas = {key: float(len(value)) for key, value in gwa_evidence.items()}
    supported_gwas = set(candidate_gwas)
    occupation_by_code = {o.code: o for o in occupations}
    fits: list[OccupationFit] = []
    for occupation in occupations:
        total = sum(occupation.dwa_weights.values())
        coverage = (sum(weight for dwa, weight in occupation.dwa_weights.items() if dwa in mapped_dwas) / total) if total else 0.0
        similarity = _cosine(candidate_gwas, occupation.gwa_ratings)
        proximity = max(0.0, min(1.0, .6 * coverage + .4 * similarity))
        contrib = set(occupation.dwa_weights) & mapped_dwas
        evidence_ids = tuple(sorted({i for dwa in contrib for i in ids_by_dwa.get(dwa, ())}))
        states = tuple(sorted({s for dwa in contrib for s in states_by_dwa.get(dwa, ())}))
        gaps = tuple(sorted(set(occupation.dwa_weights) - mapped_dwas))
        if occupation.code in safe_policy.excluded_codes:
            recommendation_status = "excluded"
        elif occupation.family not in reference.families:
            recommendation_status = "taxonomy_conflict"
        elif occupation.family not in safe_policy.allowed_families:
            recommendation_status = "not_target"
        elif proximity <= 0.0:
            recommendation_status = "unsupported"
        elif not (contrib & confirmed_non_education) and any(
            item_by_id[evidence_id].kind in ("education", "cert")
            for dwa in contrib for evidence_id in ids_by_dwa.get(dwa, ())
        ) and not any(
            item_by_id[evidence_id].kind not in ("education", "cert")
            for dwa in contrib for evidence_id in ids_by_dwa.get(dwa, ())
        ):
            recommendation_status = "education_unverified"
        elif not (contrib & confirmed_non_education):
            recommendation_status = "suggested_path"
        else:
            recommendation_status = "candidate_path"
        fits.append(OccupationFit(
            code=occupation.code, family=occupation.family,
            dwa_coverage=coverage, gwa_similarity=similarity, proximity=proximity,
            evidence_ids=evidence_ids, gap_dwa_ids=gaps, mapping_states=states,
            recommendation_status=recommendation_status,
        ))
    recommendations = tuple(sorted((f for f in fits if f.recommendation_status == "candidate_path"), key=lambda f: (-f.proximity, f.code)))
    diagnostics = tuple(sorted((f for f in fits if f.recommendation_status != "candidate_path"), key=lambda f: (-f.proximity, f.code)))
    archetypes = _clusters(tuple(fits), occupation_by_code, supported_gwas)
    eh = evidence.bundle_hash
    ph = digest(safe_policy.model_dump(mode="json"))
    mh = digest([m.model_dump(mode="json") for m in mapping_records])
    rh = ref_hash
    run = digest({
        "implementation": STRUCTURAL_VERSION,
        "evidence": eh, "reference": rh, "mappings": mh, "policy": ph,
        "clusters": [p.model_dump(mode="json") for p in archetypes],
    })
    return AnalysisResult(
        archetypes=archetypes, run_key=run, evidence_hash=eh, reference_hash=rh,
        policy_hash=ph, mapping_hash=mh, status=status,
        recommendations=recommendations, diagnostics=diagnostics,
        unmapped_evidence_ids=unmapped_ids,
    )


def analysis_metadata(result: AnalysisResult) -> dict[str, object]:
    """Return only validated digests, aggregate counts, and status."""
    try:
        safe_result = AnalysisResult.model_validate(result.model_dump(mode="python"))
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise _error("analysis_invalid")
    return {
        "status": safe_result.status,
        "run_key": safe_result.run_key,
        "evidence_hash": safe_result.evidence_hash,
        "reference_hash": safe_result.reference_hash,
        "policy_hash": safe_result.policy_hash,
        "mapping_hash": safe_result.mapping_hash,
        "recommendation_count": len(safe_result.recommendations),
        "diagnostic_count": len(safe_result.diagnostics),
        "archetype_count": len(safe_result.archetypes),
        "unmapped_count": len(safe_result.unmapped_evidence_ids),
    }


def structural_summary(result: AnalysisResult) -> dict:
    """Bounded overview; exact complete fits remain available through code lookup."""
    selected = sorted((f for f in (*result.recommendations, *result.diagnostics)
                       if f.recommendation_status in {'candidate_path', 'suggested_path'}),
                      key=lambda f: (-f.proximity, f.code))[:10]
    return {'status': result.status, 'run_key': result.run_key,
            'reference_hash': result.reference_hash, 'mapping_hash': result.mapping_hash,
            'recommendation_count': len(result.recommendations), 'diagnostic_count': len(result.diagnostics),
            'unmapped_evidence_count': len(result.unmapped_evidence_ids),
            'meaning': 'Structural activity similarity, not hiring probability or qualification. Suggested links are unverified.',
            'top_paths': [dict(f.model_dump(mode='json', exclude={'gap_dwa_ids', 'evidence_ids'}),
                               evidence_count=len(f.evidence_ids), gap_count=len(f.gap_dwa_ids)) for f in selected],
            'detail_tool': 'read_occupation_fits'}
