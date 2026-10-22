# ADR 0005: Field and job discovery

Date: 2026-10-22

Status: Accepted owner direction (backend brief of 2026-10-21); deployment and matching quality have their own acceptance criteria.

## Context

The agreed backend brief of 2026-10-21 calls for discovering suitable
occupational fields from approved candidate evidence, then finding and assessing
actual postings. Existing retrieval for individual advertisements is not enough
to identify related fields. The owner's direction was: “it should use semanntic
reasoning/extraction to filter out how about that”. Title keywords may help find
postings, but they cannot decide personal fit. This ADR records the
implementation of that already approved brief. It does not establish deployment
or improved matching accuracy.

## Decision

- **Fields.** Approved facts in `experience`, `education`, `skill`,
  `transferable_skill` and `career_focus`, with basis `evidence` or `inference`
  (never `unknown`), are embedded as `field_from_evidence` queries and compared
  with occupation documents containing titles, descriptions, tasks and skills.
  An occupation score is the mean of its three highest fact similarities. The
  output is a `FieldHypothesis` list. `is_qualification_proof` is always
  `False`: a related occupation is a search hypothesis, never qualification
  proof.
- **Strategy.** `DecisionPolicy.strategy` shapes the hypothesis list:
  `employment_first` ranks by evidence across all permitted fields;
  `career_focus` gives two thirds of the slots, rounded up, to the focus ranking
  and the remainder to evidence; `balanced` alternates. Explicit exclusions
  always remove hypotheses. The bundled `Occupation.excluded` flag and
  `MINIMUM_EXCLUDED_CODES` are local annotations and are not used.
- **Reference data.** Public, versioned, hash-verified datasets live under
  `<data>/reference/<dataset>/<version>/`, where `<data>` is `users.base_dir()`;
  downloaded datasets are never committed. The bundled
  `jobwatch/candidate/data/occupation-reference.json` (ANZSCO 2022 occupations
  with O*NET activity weights) is always available. O*NET tasks and skills,
  ESCO and OSCA are optional, each with a `PINNED` specification. The current
  dataset investigation is recorded in
  [Reference dataset investigation](#reference-dataset-investigation).
- **Search plan.** `SearchPlan` queries come from hypothesis titles and
  `policy.focus`; locations come from `policy.home` and the confirmed scope.
  With `pipeline.agentic.search_plan: true`, Seek, Jora and JobSpy read a
  derived overlay of `searches.yaml` instead of the owner's lists.
  `searches.yaml` remains the fallback.
- **Relevance.** Title keywords are a recall pre-screen and can only add
  postings for detail fetching. Relevance is decided from the full ad, using
  similarity between ad passages and hypothesis reference vectors. At or above
  `similar_at`, the answer is `yes`; below it, one candidate-free model
  extraction returns `yes`, `no` or `uncertain`, with verbatim quotes. A `no`
  requires at least one quote verified against the title or ad; otherwise the
  result is `uncertain`. Similarity alone never archives. `no` archives with
  reason `not_relevant` only when `pipeline.agentic.relevance: on`; the default
  `shadow` mode stores the judgment without archiving. `uncertain` proceeds.
- **Exclusion pre-filter.** Employer, title-term, location and work-type rules
  from `DecisionPolicy.exclusions` archive an ingested posting as
  `excluded_by_rule` before any paid call; family rules remain in the gate.
  These rules take effect only with `pipeline.agentic.decision_policy: profile`,
  regardless of relevance mode. With `legacy`, the pre-filter does nothing.
- **Semantic duplicates.** Two live postings from different sources describe
  the same vacancy when the cosine of their mean passage vectors is at least
  `duplicate_cosine`, normalized company names are equal or one name's tokens
  contain the other, title Jaccard similarity is at least `0.6`, and the cities
  match (or both postings are remote). The newer, non-READY copy is archived as
  `duplicate_of:<id>`. If any condition fails, they are treated as different
  vacancies.
- **Embedding path.** `dedupe: semantic` and
  `ordering: hypotheses` replace `_near_duplicates` and `_target_first` behind
  flags; both defaults remain `legacy`, and the legacy code stays available.
  Embeddings use the approved `PaidGatewayEmbeddings` route and configured
  embedding model, with route checks and the confirmed scope's token budget.
- **Cost and versioning.** Discovery does not change the run key. Judgments are
  stored in `posting_relevance` per `(posting, ad_hash, plan_hash)` and exposed
  through `discovery.latest_judgment(conn, posting_id)`. Vectors are keyed by
  text hash and model. Discovery flags are
  `pipeline.agentic.search_plan` (default `false`),
  `pipeline.agentic.relevance` (`off | shadow | on`, default `shadow`),
  `pipeline.agentic.dedupe` (`legacy | semantic`, default `legacy`), and
  `pipeline.agentic.ordering` (`legacy | hypotheses`, default `legacy`).
- **Not claimed.** `similar_at` (`0.60`) and `duplicate_cosine` (`0.95`, the
  value `_near_duplicates` already uses) are uncalibrated design choices. No
  matching-accuracy claim is made; calibration needs owner labels (Plan 6b).
  Title keywords alone were rejected as a fit decision; an LLM call for every
  posting was rejected on cost grounds; a trained classifier was rejected for
  lack of labels. BM25 hybrid retrieval remains future work.

## Reference dataset investigation

Official sources and public file bytes were inspected on **2026-10-22**. No
reference files were put in Git or a person's runtime. Exact file URLs, sizes,
SHA-256 hashes, attribution and worksheet maps are recorded in
`jobwatch/occupations/datasets.py`; normal reads never download anything.

| Reference | Verified state | Decision |
|---|---|---|
| [O*NET database](https://www.onetcenter.org/database.html), [release archive](https://www.onetcenter.org/db_releases.html) | 31.0, August 2026; 1,016 occupations. Occupation, task, essential-skill and transferable-skill CSVs downloaded and hashed. CC BY 4.0; credit USDOL/ETA, identify modifications, link licence, no endorsement. | Pinned, available after explicit fetch. 31.0 splits the former skills file; both new tables supply importance ratings. Real public-file loader smoke produced 1,016 records. |
| [ESCO 1.2.1 announcement](https://esco.ec.europa.eu/en/news/esco-v121-live), [download flow](https://esco.ec.europa.eu/en/use-esco/download), [dataset structure](https://esco.ec.europa.eu/en/structure-esco-downloadable-datasets) | Announcement 22 December 2025; footer separately says last update 10 December 2025. Current downloads require an email-delivered link. No email was supplied. No stable CSV URLs, current package hashes or exact real headers were verified. Commission general reuse policy is CC BY 4.0; package notices remain unreviewed. | Disabled with no guessed download links. Synthetic loader handles occupations, essential skill relations and numeric-code-to-URI crosswalk resolution. Owner must acquire the package, review its licence/schema and pin actual URLs/hashes before enabling. |
| [ABS ANZSCO 2022](https://www.abs.gov.au/statistics/classifications/anzsco-australian-and-new-zealand-standard-classification-occupations/2022) | Released 22 November 2022, corrected 27 June 2023. Inherited structure and correspondence downloads still match the bundled manifest hashes. | Bundled 1,074 occupations remain primary, including locally annotated excluded occupations; personal exclusion policy applies separately. |
| [ABS OSCA 2024 v1.0](https://www.abs.gov.au/statistics/classifications/osca-occupation-standard-classification-australia/2024-version-1-0/data-downloads) | Released 6 December 2024. Category Descriptions workbook: 493,401 bytes, contents revision 28 July 2025; sheet 2 A/B/D gives identifier/title/lead statement. Correspondence v2: 641,062 bytes; sheet 6 A/C maps ANZSCO to OSCA, carrying merged ANZSCO codes forward. Both downloaded and hashed. | Pinned and available after explicit fetch. Real public-file smoke produced 1,156 records and 1,348 raw correspondence rows. Category descriptions provide text absent from the separate structure workbook. All links are conservatively broad. |
| [JSA Australian Skills Classification](https://www.jobsandskills.gov.au/legacy/AustralianSkillsClassification) | Decommissioned December 2023; removed January 2025. Research access now requires a separate agreement. Historical report licences do not establish availability of the withdrawn data. | Not loaded; no access request or contact was made. |

[ABS copyright terms](https://www.abs.gov.au/website-privacy-copyright-and-disclaimer)
permit reuse of public statistical text under CC BY 4.0, with stated exceptions
including branding/artwork and third-party content. The loader imports statistical
text only. Attribution names ABS, the version and modifications. ESCO's software
EUPL licence is not treated as the classification-data licence; the relevant
[Commission legal notice](https://commission.europa.eu/legal-notice_en) is only a
general reuse reference until the actual package is reviewed.

The [official O*NET ESCO crosswalk](https://www.onetcenter.org/crosswalks.html)
was downloaded and its existing hash verified. Its workbook has numeric ESCO/ISCO
codes in A and O*NET-SOC codes in C, rather than ESCO URIs. URI links are resolved
only when the ESCO occupation code table is also loaded. Bundled O*NET/ANZSCO
links, ESCO/O*NET links and ANZSCO/OSCA links are many-to-many search aids, never
qualification equivalence. Dangling endpoints are removed. No file download was
blocked; ESCO is unavailable through an unauthenticated stable-file workflow,
not a proxy error.

## Implementation rulings

- Follow verified O*NET 31.0 skills filenames and the OSCA category-description
  workbook. Add a `file` key to the worksheet maps to distinguish the two ABS
  workbooks. Cost if wrong: revise pins/parser; downloaded data stays optional.
- Accept fetch URLs only on the configured source host, including redirects.
  A foreign file host cannot authorize itself. Cost if wrong: a future official
  CDN needs an explicitly reviewed allowlist extension.
- Under semantic dedupe, bypass the old company/text hash archive so different
  cities and same-source requisitions reach the conservative structured guards.
  Also defer cross-source company/title/city key merges to description comparison;
  exact URL and source-ID identity still deduplicate immediately. Legacy mode is
  unchanged. Cost if wrong: more distinct postings are assessed.
- Owner follow-up on 2026-10-22: "pre filter shouldn't be hardcoded" and
  "profile preferences behavior shouldn't be hardcoded". Collection and ingest
  derive regional admission from the current confirmed policy, independently of
  search-plan flags. The canonical location classifier checks the person's
  regions and remote preference; unknown locations remain assessable. The
  previous configuration-based path is retained only when no approved policy
  exists. Full-ad eligibility remains authoritative. Cost if wrong: incorrect
  source metadata can admit extra ads or defer a location decision to assessment.
- Dry collection runs never trigger a paid plan refresh. A stale plan/reference
  cache requires refresh; APIs label a retained stale plan explicitly.
- When semantic context is unavailable, enabled semantic dedupe/ordering skip
  their work instead of silently using the legacy embedding provider. Assessment
  continues with existing gates. Cost if wrong: temporary duplicate work or older
  ordering; no new unapproved route.
- Reconsideration limits restored candidates after examining current rules,
  rather than limiting unchanged excluded rows first, to prevent starvation.

See the [synthetic workflow example](../examples/field-discovery.md) for flags,
read-only API output, verification scope and rollback.

## Consequences

- Field discovery, search planning, relevance, exclusions and duplicate
  detection can be enabled independently under explicit flags.
- Evidence retrieval and posting assessments stay within the approved paid
  routes, confirmed profile scope and per-person isolation rules.
- Similarity, model judgments and related occupations do not establish
  qualification, eligibility or improved matching accuracy.
- This ADR records an accepted design; it does not mean the backend is deployed.

## References

- [Agreed backend brief](../superpowers/specs/2026-10-21-agreed-backend-brief.md)
- [Plan 3: Field and job discovery](../superpowers/plans/2026-10-21-plan-3-discovery.md)
- [Cross-plan contract](../superpowers/plans/2026-10-21-cross-plan-contract.md)
- [INTENT.md](../../INTENT.md)
