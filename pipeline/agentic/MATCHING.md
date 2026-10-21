# Requirement evidence matching

Shared collection and API operations call `evaluate_job`. The current sequence is:

1. Extract requirements/facts from the complete ad without candidate evidence.
2. Retrieve and judge primary evidence against each frozen requirement.
3. Summarize the frozen evidence judgments with preferences and model context.
4. Apply the existing deterministic eligibility and holistic-score policy.

## Retrieval and focused judgments

`matching.RequirementEvidenceSearch` creates an ephemeral local BM25 index over
the current person's verified canonical evidence bundle. It deduplicates exact
source/quote copies. Initial requirement shortlists contain IDs; search/read tools
return exact primary records and record access. The evaluator can supply bounded
skill/task paraphrases for query expansion and inspect other inventory records.
It interprets and reranks the records in the focused matching pass. No raw
career-master source or unapproved mapping is used.

Without an embedding setting, retrieval stays lexical with model query expansion.
The optional `pipeline.agentic.embedding_model` setting enables dense retrieval via
`PaidGatewayEmbeddings`, using LangChain's
[`Embeddings` interface](https://docs.langchain.com/oss/python/integrations/embeddings/).
The adapter uses the existing server-bound gateway, explicit selected credential,
and shared durable job/API reservations. No retry, provider/credential fallback,
hosted tracing, or legacy public-ad transport is used.

The owner selected **Qwen** on 2026-10-21. Source configuration now selects
`openrouter/qwen/qwen3-embedding-8b`, advertised by the existing OmniRoute model
catalog and [listed as paid by OpenRouter](https://openrouter.ai/qwen/qwen3-embedding-8b).
This exact model is allowed only for embedding operations, not chat. The counted
adapter applies Qwen's query-only `Instruct: ...\nQuery:...` format, leaving evidence
documents plain, following the [official model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B).
This changes the source release configuration, not the live service.

Dense indexing covers exact overlapping spans of every canonical record and the
frozen requirement texts. Vectors stay in memory for this job. Cosine and BM25
rankings are combined with equal-weight reciprocal rank fusion (offset 60), then
interpreted by the focused model. This is a retrieval heuristic, not a learned
job-fit formula or separately validated cross-encoder. Relevance scores are not
fit probabilities, and a shortlist is not exhaustive evidence.

Configured dense retrieval fails visibly when unavailable; source tails are not
silently dropped. An index beyond 2,048 chunks holds. The source release selects
Qwen; live route inference, retrieval quality and deployment remain unverified.

New evaluations require a judgment per requirement, with a rationale, reviewed
evidence IDs and a question when a gap remains. Exact candidate quotes must resolve
to retrieved canonical records. The ad citation stays on the frozen requirement.

| Judgment | Compatibility match | Meaning |
|---|---|---|
| demonstrated | strong | Primary evidence supports the requirement. |
| partial | partial | Relevant proof exists; an explicit gap remains. |
| unknown | missing | The reviewed evidence does not establish the fact. |
| contradicted | missing | A separate primary quote explicitly conflicts with the requirement. |
| not_applicable | not_applicable | Does not apply; prohibited for essential requirements. |

Model relevance or confidence cannot establish proof. An absent skill is not
contradiction. A related title is not demonstration. Current study is not a
completed credential. Questions are saved for review; they do not modify profiles,
create approval, or automatically become employer screening questions.

The holistic summary receives the frozen matches and cannot replace them. Ability
is assessed before preferences, company context, occupation similarity or callback
history. Typed output and exact quotes establish traceability, not semantic truth.
There is no claim of calibrated confidence or hiring probability.

## Storage and compatibility

The existing private `evaluation` artifact stores judgments and
`matching_diagnostics`: matcher version, configured model, baseline commit,
retrieval shortlists/searches, accessed IDs and explicit unmeasured calibration.
These are private records; do not copy them to telemetry or hosted tracing.

Historical evaluations omit the additive fields on serialization, preserving their
old payload shape and hashes. Missing historical judgments stay absent. The source
implementation version changes run identity so new code does not silently reuse
an old evaluation/package. No database migration or evidence rewrite is required.

The previous matcher is frozen in source at
`ce160598d49a0464e30380a057dd0a677980de3c`. This is a source reference, **not a
recorded benchmark**. The 1–5 summary and existing score/eligibility thresholds
remain unchanged; new prompts can still change decisions. An automatic paid shadow
runner is not implemented, and this branch is not promoted or deployed.

Both extraction, focused judgments and summary share the existing evaluator
turn/token/deadline budget and paid gateway checks. The added pass costs model
work; limits were not increased. Exhaustion holds the job through existing recovery.

## Remaining experiment before policy promotion

Keep comparison inputs and owner labels private. Include archived jobs as well as
eligible/READY jobs, transferable duties, paraphrased skills, credentials in
progress, absent facts, conflicting evidence and misleading titles. Group duplicate
ad variants and companies together when splitting examples. Have the owner review
examples without seeing which matcher produced a judgment; AI show/hide history
and synthetic practice data are not independent suitability labels.

Compare the frozen and revised matcher on the same evidence/ad snapshots. Record
missed suitable jobs, unsupported strong matches, unknown versus contradiction
errors, useful top-ranked jobs, latency and actual/budgeted usage. Review uncertainty
and disagreement examples directly. Keep owner preference prediction and matured
callback observations as separate measures. Pending applications are not negative
outcome labels. Do not tune exclusion thresholds from model self-grades.

## Offline comparison tools

The native CLI compares already captured outputs without dispatching paid work:

```
jobwatch-agent --person PERSON --matching-comparison /absolute/private/comparison.json
jobwatch-agent --person PERSON --matching-comparison /absolute/private/comparison.json --blind-output-dir /absolute/private/new-review-dir
```

Both paths must be inside that person's private runtime directory. Export refuses
an existing directory and creates mode-0600 files in a mode-0700 directory.
`packet.json` contains normalized anonymized A/B outputs in shuffled order, without
model names, holistic scores or routes. Keep `private-arm-key.json` hidden during
review. Review complete canonical sources matching the packet's evidence hash;
the prediction quotes are not a complete candidate record.

Input is a list of `MatchingCase` records (schema available from that class):

- `case_id`, `group_id` (company/ad variants), `split` (`development` or `holdout`).
- `predictions`, keyed by two to four arm/version names, each containing a full
  `evaluation`, matching gate `decision`, `latency_seconds`, `charged_tokens`, and
  `actual_tokens` (null if unknown).
- Optional `review`: `actor: owner`, independent `suitable` boolean, and complete
  `requirement_status` labels. Omit until blind review is complete.

Arms must share posting, ad, evidence and frozen requirement identities. Every arm
must appear on every case. The tool rejects duplicate cases and groups crossing
splits, and reports development/holdout counts separately. It measures false
exclusions, suitable held cases, unsuitable drafts, unsupported strong claims,
status disagreements, unknown/contradiction errors, latency and usage. It does not
score ranking usefulness, authenticate imported owner attribution or prove label
independence. Aggregate output has no candidate quotes. Missing held-out labels
returns `owner_holdout_labels_required`, never PASS.

## Preferences and observed outcomes

Choice features v2 add missingness/source metadata and snapshot commute rings
(<5 km, 5–10 km inclusive, >10 km), using straight-line distance, not travel time.
Remote-accessible evaluations use no commute ring. Full-work-rights wording is an
ad feature, not a candidate visa fact. Unknown seniority stays missing; historical
evaluations without uncertainty metadata do not gain invented certainty. Pay,
candidate years, flexibility, automation and visa-welcoming features stay missing
until supported. Old fits become stale through versioned context; no training or
synthetic owner labels are generated.

Callback and readiness calculations share one observation classifier. Unsubmitted
rejected drafts are excluded; submitted cases without an explicit callback or
rejection remain pending. Callback history survives later rejection. The Beta
posterior denominator is **explicitly resolved submissions**, with pending counts
separate. This is a descriptive, selection-biased resolved subset, not an unbiased
eventual callback probability or qualification score. No arbitrary time cutoff
turns silence into failure. A calibrated time-to-event model with an explicit
observation horizon remains future work.

A separately approved Jev/local comparison, blind owner labels and a job-domain
benchmark remain tracked in issue #6. No legacy candidate-bearing Jev/vector calls
were re-enabled. The native synthetic acceptance path now exercises both lexical
and Qwen-configured retrieval through actual graphs, human approval/resume,
focused judgments, company brief, writer, reviewer, saved PDFs, downloads and
idempotent reuse. Model responses in that path are deterministic fixtures; it
proves backend mechanics, not real-model writing or matching accuracy.

One separately authorized real Qwen gateway request used three synthetic passages:
it returned three 4,096-dimensional vectors, with related cosine 0.7136 versus
unrelated cosine 0.1847. No real candidate records were sent. This establishes that
the selected embedding endpoint answered, not job-domain retrieval accuracy.

## Automated verification

`.github/workflows/backend.yml` runs the native pipeline, graph/runtime, evidence
matcher, contract/gate, preference and censored-outcome checks on pushes and pull
requests. Manual `workflow_dispatch` is supported; outdated runs for the same
branch/PR are cancelled. CI uses synthetic data and injected transports, with no
gateway secrets, employer requests or private artifacts uploaded.

The end-to-end check also guards the dispatch regression where the optional
embedding model was incorrectly validated as a chat model. Both unset embeddings
and the explicitly approved Qwen route must reach a complete saved package.
Focused checks cover Qwen instructions/paid-route isolation, invalid vectors and
retained charges, blinded packets, absent labels, snapshot mismatches and split
leakage. Historical evaluator fixtures now target the focused judgment stage for
bounded corrections instead of accidentally sending a summary to that stage.

Automation does not merge or deploy on a synthetic green result. Full release
regression, independent acceptance audit, reviewed matching examples and a real
quality comparison remain release evidence. Missing human labels stays explicit;
no automated model answer is recorded as an owner's label or approval.

Undo: revert the evidence-matching source commit and retain private artifacts.
Restore a matching code/skills release for old conversations. Do not delete history.
