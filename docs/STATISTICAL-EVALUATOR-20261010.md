# Statistical evaluator integration

Owner words (verbatim): “my profile is already there I want you to convert it into data and verify”; “how about the statistical model evaluator”; “fix it then”. Work belongs to BUI-288. This is an isolated build, not a live cutover.

## Implemented

The actual agentic service now loads the shipped occupation reference and a source-bound mapping snapshot before calculating the run identity. Inventory, candidate assessment, cached/resumed assessment validation and pre-finalization freshness use those same inputs. Changed profile evidence, reference bytes, mappings or policy invalidate old results. Immutable private artifacts retain the reference and mappings alongside the assessment. Restored candidate numerical results are recomputed and compared, not trusted solely because an artifact exists.

The offline reference builder uses seven official public downloads recorded in `jobwatch/candidate/data/source-manifest.json`. The shipped reference validates 1,074 Australian occupations, 2,087 work activities and 922 O*NET crosswalk records. Attribution, exact editions, equations and limitations are in `jobwatch/candidate/data/ATTRIBUTION.md`. ANZSCO 2022 is pinned for compatibility, not presented as the latest Australian classification. No candidate data is included in the public export.

If no reviewed mapping file is configured, local retrieval supplies diagnostic suggestions only. At most three activities are linked per primary skill/achievement. Study, certificates, role titles, preferences and saved answers are not treated as demonstrated tasks by retrieval. Confirmed links can be supplied with `pipeline.agentic.occupation_mappings_path`; every link must match the exact primary-source and reference hashes. An optional `occupation_reference_path` overrides the bundled reference; missing or invalid explicitly configured inputs fail closed. No silent fallback after malformed input.

The candidate page computes the current numerical view locally, without a language-model call or data write. It shows activity coverage, cosine similarity, the existing fixed 60/40 blend, evidence counts, source edition, mapping state and inspectable evidence/activity links. Only current AI assessments are displayed. Agents receive a bounded overview and can request complete occupation fits, instead of receiving all diagnostic gap lists in one tool response.

The outcome panel counts submitted applications, historical callbacks, resolved rejections and pending cases separately. Pending responses are not labelled failures; a locally rejected draft without submission evidence is not a trial. Zero resolved observations produces `untrained` with no prediction. With observations, an explicitly conditional descriptive Beta(1,15) posterior includes its 95% interval and selection caveat; it is not a calibrated per-job prediction.

## Real local verification

A source-verified snapshot of 239 primary evidence records produced 62 suggested links involving 36 records and 15 positive target-family diagnostic fits. There were zero confirmed links and zero confirmed career recommendations. These counts demonstrate the data connection, not semantic accuracy of the retrieval suggestions. Private mappings and analysis remain outside git and the delivery packet. No model calls or profile transmissions occurred.

Read-only live outcome inventory: zero submitted applications and zero observed outcomes. A synthetic page was rendered through the actual FastAPI route and Chromium, with no external requests; no live services were changed.

## Acceptance boundaries

The disconnected reference/mapping path is repaired. Semantic validation of suggested mappings remains necessary before calling them confirmed. Archived preference learning, Heckman selection correction and conformal outcome selection have not been restored or validated by this change. Valid instruments, explicit owner choice labels, observed outcomes and held-out calibration cannot be invented from profile text. The existing remaining-concept ledger stays in force; this change does not claim completion of the whole archived statistical research programme.

The separate private paid real-profile acceptance remains pending explicit payload/destination/budget approval. Real application walkthrough and live cutover also remain outstanding. Automatic approval review rejected the optional external Fable source-code consultation; local inspection and tests were used, and no external advisor review is claimed.

## Undo

Revert this integration commit in the isolated branch, or restore the previous deployment candidate. Live code/config/data were not modified. After a later approved deployment, preserve immutable application artifacts and outcomes when rolling back code; never restore an old database over new application history.
