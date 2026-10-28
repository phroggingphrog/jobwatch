"""Current local statistical view; never calls a language model or writes data."""
from .analysis import analyse_candidate
from .inputs import load_inputs
from .policy import default_policy


def statistical_view(bundle, config):
    reference, mappings = load_inputs(bundle, config)
    analysis = analyse_candidate(bundle, reference, mappings, default_policy())
    titles = {o.code: o.title for o in reference.occupations} if reference else {}
    target_families = set(default_policy().allowed_families)
    fits = [f for f in (*analysis.recommendations, *analysis.diagnostics)
            if f.family in target_families and f.recommendation_status != 'excluded' and f.proximity > 0]
    fits.sort(key=lambda f: (-f.proximity, f.code))
    evidence = {item.id: item for item in bundle.items}
    dwas = {d.id: d for d in reference.dwas} if reference else {}
    return {'status': analysis.status, 'run_key': analysis.run_key,
            'reference_version': reference.version if reference else None,
            'reference_hash': analysis.reference_hash,
            'evidence_count': len(bundle.items), 'mapped_evidence_count': len({m.evidence_id for m in mappings}),
            'confirmed_count': sum(m.state == 'confirmed' for m in mappings),
            'suggested_count': sum(m.state == 'suggested' for m in mappings),
            'fits': [dict(f.model_dump(mode='json'), title=titles[f.code]) for f in fits],
            'links': [{'evidence': evidence[m.evidence_id].quote, 'activity': dwas[m.dwa_id].title,
                       'state': m.state, 'method': m.method} for m in mappings]}
