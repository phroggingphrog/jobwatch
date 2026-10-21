"""Local requirement-directed retrieval over approved canonical evidence only.

BM25 proposes records; the bounded evaluator interprets and reranks them. Model
query expansion helps with different wording, but this is not dense retrieval.
Scores are retrieval relevance, never candidate suitability or proof of absence.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from pydantic import Field

from jobwatch.candidate.assessment import evidence_records
from pipeline.agentic.contracts import AgenticError, StrictFrozen

MATCHING_VERSION = "requirement-evidence-v1"
BASELINE_COMMIT = "ce160598d49a0464e30380a057dd0a677980de3c"
_STOP = frozenset("a an and are as at be by for from in is it of on or that the this to with you your".split())


def _terms(text):
    return [word for word in re.findall(r"[\w+#]+", text.casefold()) if word not in _STOP]


class EvidenceSearch(StrictFrozen):
    requirement_id: str = Field(min_length=1, max_length=64)
    related_terms: tuple[str, ...] = Field(default=(), max_length=8,
        description="Optional task/skill paraphrases for retrieval only; never candidate facts.")
    limit: int = Field(default=6, ge=1, le=12)


class RequirementEvidenceSearch:
    """Ephemeral index scoped to the already verified immutable job snapshot."""

    def __init__(self, bundle, requirements):
        self.bundle = bundle
        self.requirements = {r.id: r for r in requirements.requirements}
        self.items = []
        seen = set()
        for item in bundle.items:
            key = (item.source_file, item.source_hash, item.quote)
            if key not in seen:
                self.items.append(item)
                seen.add(key)
        self.documents = [Counter(_terms(item.quote)) for item in self.items]
        self.lengths = [sum(doc.values()) for doc in self.documents]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 1
        self.frequency = Counter(term for doc in self.documents for term in doc)
        self.accessed: set[str] = set()
        self.searches: list[dict] = []

    def _rank(self, requirement_id, related_terms, limit):
        if requirement_id not in self.requirements:
            raise AgenticError("unknown_requirement")
        if any(len(term) > 160 for term in related_terms):
            raise AgenticError("invalid_search")
        query = set(_terms(self.requirements[requirement_id].text + " " + " ".join(related_terms)))
        ranked = []
        count = len(self.documents)
        for item, doc, length in zip(self.items, self.documents, self.lengths):
            score = 0.0
            for term in query & doc.keys():
                df, tf = self.frequency[term], doc[term]
                idf = math.log(1 + (count - df + .5) / (df + .5))
                score += idf * tf * 2.5 / (tf + 1.5 * (.25 + .75 * length / (self.average_length or 1)))
            if score > 0:
                ranked.append((score, item.id))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return [{"evidence_id": identifier, "relevance": round(score, 6)}
                for score, identifier in ranked[:limit]]

    def initial_candidates(self):
        # IDs only: search/read tools expose exact records and record actual access.
        return {identifier: self._rank(identifier, (), 4) for identifier in self.requirements}

    def read(self, identifiers):
        records = evidence_records(self.bundle, identifiers)
        self.accessed.update(record["id"] for record in records)
        return {"items": records}

    def search(self, args):
        hits = self._rank(args.requirement_id, args.related_terms, args.limit)
        identifiers = tuple(hit["evidence_id"] for hit in hits)
        self.searches.append({"requirement_id": args.requirement_id,
            "related_terms": list(args.related_terms), "limit": args.limit, "hits": hits})
        return {"method": "bm25_with_model_query_expansion", "hits": hits,
            "items": self.read(identifiers)["items"],
            "boundary": "Bounded relevance shortlist, not exhaustive proof. No hit means unknown, not inability. Read other inventory records when useful."}

    def diagnostics(self, model):
        return {"version": MATCHING_VERSION, "baseline_commit": BASELINE_COMMIT,
            "model": model, "retrieval": "bm25_with_model_query_expansion",
            "dense_retrieval": "not_configured", "judgment_stage": "separate_before_summary",
            "calibration": "not_measured", "summary": "career_ops_holistic_1_to_5",
            "eligibility_policy": "unchanged", "evidence_hash": self.bundle.bundle_hash,
            "initial_candidates": self.initial_candidates(), "searches": list(self.searches),
            "accessed_evidence_ids": sorted(self.accessed)}
