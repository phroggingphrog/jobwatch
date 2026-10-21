"""Local TF-IDF retrieval of possible activity links; never confirms a skill.

These are diagnostic suggestions, not decisions, qualifications or learned labels.
The version and all outputs participate in the assessment identity.
"""
import math
import re
from collections import Counter
from .contracts import Mapping
from .mapping import validate_mappings

VERSION = 'activity-retrieval-v1'
STOP = frozenset('a an and are as at be by for from in into is it of on or that the their to using with work activities information related other'.split())


def terms(text):
    words = re.findall(r'[a-z]{3,}', text.lower())
    return {word for word in words if word not in STOP}


def suggest_mappings(bundle, reference):
    documents = [(dwa, terms(dwa.title)) for dwa in reference.dwas]
    df = Counter(term for _, tokens in documents for term in tokens)
    weights = {term: math.log((len(documents) + 1) / (count + 1)) + 1 for term,count in df.items()}
    results = []
    for item in bundle.items:
        # Titles, study and certificates alone are never demonstrated tasks.
        if item.kind not in {'skill', 'achievement'}:
            continue
        query = terms(item.quote)
        qnorm = math.sqrt(sum(weights[t]**2 for t in query if t in weights))
        if not qnorm: continue
        scores = []
        for dwa, tokens in documents:
            overlap = tokens & query
            if len(overlap) < 2: continue
            norm = math.sqrt(sum(weights[t]**2 for t in tokens))
            score = sum(weights[t]**2 for t in overlap) / (qnorm * norm) if norm else 0
            if score >= .3: scores.append((score, dwa.id))
        for _, ident in sorted(scores, key=lambda pair: (-pair[0], pair[1]))[:3]:
            results.append(Mapping(evidence_id=item.id, source_hash=item.source_hash,
                reference_hash=reference.reference_hash, dwa_id=ident, method=VERSION, state='suggested'))
    return validate_mappings(bundle, reference, tuple(results))
