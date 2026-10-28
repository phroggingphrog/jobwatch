# Candidate Foundation Provenance and Source Attribution

This document records the exact provenance, source identities, licences, and adaptation methodology for the candidate analysis foundation implemented in `jobwatch.candidate`.

Canonical rulebook: `/home/phroggingphrog/apps/jobwatch/INTENT.md`.
Approved spec: `docs/superpowers/specs/2026-10-09-candidate-foundation-design.md`.
Approved plan: `docs/superpowers/plans/2026-10-09-candidate-foundation.md`.
Work item: BUI-258 (Task 1, with Task 4 implementation notes below).

## 1. Upstream and Archived Source Inventory

Exact SHA-256 hashes, file sizes, and paths of source material referenced and adapted:

| Component | Path | Bytes | SHA-256 | Licence Evidence / Uncertainty |
|---|---|---|---|---|
| `candidate_analysis.py` | `/home/phroggingphrog/archive/workspace-20261004/job-tracker-phr485/agent/workspace/skills/fit-evaluation/candidate_analysis.py` | 17,655 | `7ce7671bea2afdfb10ff8ed375405e27a276eed4ca46c41f60e70fd7e7514bdb` | Internal archived module. No standalone LICENSE file present in `job-tracker-phr485` directory; uncertainty recorded. |
| `occupation_reference.py` | `/home/phroggingphrog/archive/workspace-20261004/job-tracker-phr485/agent/workspace/skills/fit-evaluation/occupation_reference.py` | 3,717 | `e972a736d59dd25f834419936809727d205a55d492fc119ea3ad77e9a0a6a83e` | Internal archived module. No standalone LICENSE file present; uncertainty recorded. |
| `evidence_dwa_map.py` | `/home/phroggingphrog/archive/workspace-20261004/job-tracker-phr485/agent/workspace/skills/fit-evaluation/evidence_dwa_map.py` | 4,709 | `e249f961fb36bc54cb8df83abb56cc5812bec0e03ab5ff7566e43efa43796c26` | Internal archived module. No standalone LICENSE file present; uncertainty recorded. |
| `evidence.py` | `/home/phroggingphrog/workspace/builder/jobwatch-agentic/jobwatch/apply/evidence.py` | 10,908 | `ff247b1214bc8122f3f5d7204ea5b1ab68161002e4d9b32261b2318cea0e43d8` | Current jobwatch repository module. Current project licensing applies. |

Additional reference context:
- `/home/phroggingphrog/archive/workspace-20261004/career-ops/LICENSE` (1,090 bytes, SHA-256 `51989d2589b2aa87ca6cbb253391bcb476a21cbafdc71eea4410548538510870`): MIT License (c) 2026 Santiago Fernández de Valderrama.

## 2. Adaptation and Methodology Limits

1. **No Broken Git HEAD Assertion**:
   Archived workspace trees (`workspace-20261004`) lack verified, unbroken git metadata. Provenance is anchored to cryptographic content digests (SHA-256) of specific verified files rather than untracked git HEAD states.

2. **Schema Definition, IP Limits, and Math Status**:
   - *IP & Clean-Room Boundaries:* Re-implementation of concepts from mathematical specifications or archived source by the same worker who inspected the source text does not constitute legally independent clean-room segregation. Standalone licensing for fragments within `job-tracker-phr485` could not be established, and current project licensing is not established as blanket permission. No source code was copied verbatim; Task 4 implements the bounded mathematical method documented below.

3. **Privacy, Quotes, and Safe Validation**:
   - *Quotes in Private Dumps:* Quotes on `EvidenceItem` and `EducationStatusEvidence` suppress string representation (`repr=False`), but quotes are intentionally retained in private model serialization (`model_dump(mode='json')`) to allow deterministic bundle hashing (`compute_bundle_hash`), annotation validation, and downstream matching. They are not globally excluded.
   - *Acquisition Bytes Excluded:* Raw acquisition byte contents (`EvidenceBundle.contents`) are suppressed in repr (`repr=False`) and explicitly excluded from serialization (`exclude=True`).
   - *Public Analysis Result:* Public output (`AnalysisResult`) strictly excludes raw evidence quotes and unvetted candidate text.
   - *Safe Validator Messages:* Custom validators use static, non-interpolating error messages to ensure private markers, paths, and IDs cannot leak via validation exceptions. Pydantic models use `hide_input_in_errors=True`.
   - *Policy Safeguards:* Immutable tuples (`EXCLUDED_FAMILIES`, `MINIMUM_EXCLUDED_CODES`) strictly prevent weakening owner target exclusions.

## 3. Task 4 Structural Analysis

Task 4 adds `jobwatch.candidate.policy` and `jobwatch.candidate.analysis`. The implementation follows the bounded structural method specified in the approved Task 4 brief: weighted DWA coverage, distinct-evidence-ID GWA vectors, cosine similarity, and a 0.6/0.4 proximity blend. This is an adaptation of the documented analysis concepts, not a copied runtime; the source inventory and licensing uncertainty above remain applicable. No archived runtime, database, model inference, provider, or private candidate data was used.

The target-policy status projection, exact confirmed-evidence contribution requirement, and deterministic cluster construction are Task 4-specific safeguards. Structural similarity is not qualification, eligibility, hire probability, or CAP-2 completion. Diagnostics can include excluded and non-target occupations; only `candidate_path` records are recommendations. `analysis_metadata` exposes digests, status, and aggregate counts only.
