# Candidate foundation (synthetic callable slice)

`jobwatch.candidate` exposes explicit-root, read-only primitives for taking a primary-source snapshot, loading a caller-supplied reference export, validating hash-bound mappings, and computing deterministic structural diagnostics. It is a tool foundation, not the agentic career-ops runtime: it does not implement whole-ad CAP-2 evaluation, CAP-3 drafting, CAP-5 form preparation, or CAP-2 acceptance. No provider, model, browser, database, timer, service, or real-profile default is used.

## Explicit invocation

The following is a test-shaped example. Supply only a deliberately selected source directory and reference-export path; do not substitute a live profile path in demonstrations. A fictional reference export can be generated in tests with `candidate.fixtures.fictional_reference(tmp_path)` and a fictional CV with `candidate.fixtures.fictional_profile(tmp_path)`.

```python
from pathlib import Path
from jobwatch.candidate import (
    Mapping, analyse_candidate, analysis_metadata, default_policy,
    load_reference, snapshot_evidence, validate_mappings,
)

source_root = Path("/explicit/fictional/source-root")
reference_path = Path("/explicit/reference-export.json")
evidence = snapshot_evidence(source_root)
reference = load_reference(reference_path)  # None means genuinely missing/unavailable
if reference is None:
    result = analyse_candidate(evidence, None, (), default_policy())
else:
    item = next(item for item in evidence.items if item.quote == "Reconciled ledgers")
    mapping = Mapping(
        evidence_id=item.id,
        source_hash=item.source_hash,
        reference_hash=reference.reference_hash,
        dwa_id="test.accounts",
        method="human-reviewed-fixture",
        state="confirmed",
    )
    checked = validate_mappings(evidence, reference, (mapping,))
    result = analyse_candidate(evidence, reference, checked, default_policy())
public_metadata = analysis_metadata(result)
```

Mappings assert a relationship between an independently extracted primary quote and a reference DWA. The `method` string identifies provenance only; it is not proof that the semantic mapping is true. Suggestions remain diagnostic, not confirmed evidence. Callers should keep source-bearing `EvidenceBundle` data private and pass only the safe projection to public/status surfaces.

## Input formats and binding

### Primary evidence

`snapshot_evidence(root: Path)` reads only supported files under the explicit root: `cv.md` (preferred over the legacy `master_resume.md` name), optional `profile.yaml`, and optional strict annotation envelopes `evidence.yaml` or `transferable_skills_taxonomy.yaml`. The CV example accepted by the synthetic builder is:

```text
# Fictional

## Skills
- Reconciled ledgers
```

Annotations use exactly this YAML envelope shape, with serialized `EvidenceItem` fields for each independently verified primary quote:

```yaml
schema_version: 1
items:
  - id: cv.L4
    kind: skill
    source_file: cv.md
    source_hash: <64 lowercase hex SHA-256 of exact cv.md bytes>
    line: 4
    end_line: 4
    quote: Reconciled ledgers
    education_status: not_applicable
    status_evidence: null
```

This is a schema illustration, not a claim that the literal placeholder is valid input. Annotation content must match an independently extracted primary item, including its source hash, quote, kind and span. A taxonomy/annotation cannot create a fact by asserting it. `profile.yaml` education status may explicitly say `completed` or `current`; status is bound to the primary YAML source and its hash/line. Missing or unsupported status stays unknown. Current education is not mastery, and even a completed credential alone cannot establish DWA skill mastery.

### Reference JSON

`load_reference(path: Path)` expects an explicit JSON export with duplicate keys rejected and no caller-supplied `reference_hash`. Minimal fixture-shaped content is:

```json
{
  "schema_version": 1,
  "version": "fixture-v1",
  "sources": {"fictional": "fixture-v1"},
  "licenses": {"fictional": "test-only"},
  "families": ["accounting", "hospitality"],
  "dwas": [{"id": "test.accounts", "title": "Reconcile accounts", "gwa_id": "test.gwa"}],
  "occupations": [
    {"code": "221111", "title": "Accountant", "family": "accounting", "excluded": false,
     "dwa_weights": {"test.accounts": 1.0}, "gwa_ratings": {"test.gwa": 4.0}},
    {"code": "431111", "title": "Barista", "family": "hospitality", "excluded": true,
     "dwa_weights": {"test.accounts": 1.0}, "gwa_ratings": {"test.gwa": 4.0}}
  ],
  "crosswalks": [{"soc": "13-2011", "anzsco_codes": ["221111"]}]
}
```

The loader hashes the exact bytes it read and keeps that private raw receipt bound to the validated export. `sources` and `licenses` are required non-empty maps with matching keys and non-empty values; the example's `test-only` marker is synthetic test metadata, not a real licence grant. A valid-looking SHA-256 string supplied as a field cannot authenticate bytes that were never supplied. No official production reference dataset has been recovered or loaded by this foundation; do not infer one from the schema example.

`Mapping` has exactly `evidence_id`, `source_hash`, `reference_hash`, `dwa_id`, `method` (non-empty, bounded string), and `state` (`suggested` or `confirmed`). The source and reference hashes must bind the current snapshot and exact loaded export. `validate_mappings` rejects dangling IDs, stale hashes, duplicate evidence/DWA pairs, invalid methods/states, and more than three DWA mappings per evidence. A many-to-many crosswalk remains a tuple of all codes; the helper does not guess a winner.

## Policy and output semantics

The default policy has a version, allowed families and immutable exclusions. Family canonicalization case-folds and maps whitespace, hyphens and underscores to `_`; for example `Customer Service` and `customer-service` normalize to `customer_service`, an immutable excluded family. Reference-declared excluded flags and the immutable excluded code floor also win over a relabelled allowed family. The minimum code set is not claimed to be a complete production taxonomy.

`AnalysisResult` status is `available`, `reference_unavailable`, or `unmapped`. A missing reference with no mappings returns an explicit empty `reference_unavailable` result. Mappings without that reference fail safely with `mapping_unresolved`. A loaded reference and zero mappings returns `unmapped` with no recommendations. Every occupation that is not a `candidate_path` is diagnostic:

- `candidate_path`: positive structural support in an allowed family, including a confirmed mapping from non-education primary evidence that contributes DWA coverage.
- `suggested_path`: structural support without confirmed non-education DWA evidence; this includes suggestion-only and GWA-only overlap.
- `education_unverified`: evidence support comes only from education/certification records; no recommendation follows from status or curriculum alone.
- `excluded`: immutable policy family/code or reference exclusion.
- `taxonomy_conflict`: occupation family not declared in the supplied reference taxonomy.
- `not_target`: declared family outside current allowed families.
- `unsupported`: no positive structural support.

`analysis_metadata(result)` revalidates the result and returns only status, bound digests, and aggregate recommendation/diagnostic/archetype/unmapped counts. It does not return quotes, titles, evidence IDs, private bytes, arbitrary caller run keys, or run-key inputs. The `AnalysisResult` and `EvidenceBundle` objects themselves are not a public privacy filter: keep them private; do not publish their unrestricted serialization. Digests demonstrate formatting and input binding, not cryptographic authentication of an absent input.

Structural math is not qualification, credential recognition, mastery, eligibility, hire probability, employer interest, or a hard-gate decision. It does not evaluate the whole advertisement, work rights, location, hours, legitimacy, seniority, program eligibility, or the job-specific career-ops rubric. A proposed path is a candidate-derived possibility inside the owner's policy, not an application recommendation or outcome prediction.

## Errors, provenance, side effects, and limits

Public APIs fail closed with fixed `CandidateError` codes for invalid source/reference/mapping/analysis input; callers should report the code, not exception internals. A missing explicit reference path alone means unavailable. Malformed, unreadable, unsafe, or stale inputs are not treated as missing or silently repaired. Input files are read-only; the candidate calls do not persist snapshots or results, contact services, invoke inference, or modify a database. The synthetic acceptance tests check source bytes, mtimes, and directory file listings around the callable flow. This is a tested no-write behavior for these calls, not an operating-system sandbox or a blanket security boundary; it does not constrain unrelated code or external processes.

The implementation adapts documented structural-analysis concepts and current evidence-extraction behavior; provenance details, source identities and licence uncertainty are recorded in [PROVENANCE.md](PROVENANCE.md). The synthetic `fictional`/`test-only` reference is not an official dataset, production crosswalk, legal licence determination, or recovered historical reference. No actual profile, answer data, private golden set, or real reference data is analyzed here. The foundation does not establish semantic mapping quality or end-to-end product readiness.

Remaining product capabilities include the paid-role-tool/private-evidence boundary, agentic whole-ad evaluation and reasoning, hard-gate checks, private accepted reference and independently judged mapping corpus, CAP-2 acceptance, job-specific CAP-3 drafting, CAP-5 form preparation to the human-submit boundary, and production eligibility/outcome validation. CAP-2, CAP-3, and CAP-5 completion are not claimed. To undo an isolated trial, leave its scoped changes unapplied or revert only the specific candidate-foundation commit(s); do not delete or reset user data.
