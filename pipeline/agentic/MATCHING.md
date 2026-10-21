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
It interprets and reranks the records in the focused matching pass. No new provider,
embedding endpoint, raw career-master source or unapproved mapping is used.

This is lexical retrieval with model query expansion and interpretation, **not
dense semantic retrieval**. Different wording can still be missed. Relevance
scores are not fit probabilities, and a shortlist is not exhaustive evidence.

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
remain unchanged; new prompts can still change decisions. Shadow comparison is
not implemented, and this branch is not promoted or deployed.

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

Dense retrieval, a separately approved Jev/local decision-model comparison,
preference-feature completion and callback observation-window corrections remain
tracked in issue #6. No candidate-bearing legacy Jev/vector calls were re-enabled.
No application tests, job-domain benchmark or live-model experiment has been run
for this change; focused runtime and budget checks remain necessary before release.

Undo: revert the evidence-matching source commit and retain private artifacts.
Restore a matching code/skills release for old conversations. Do not delete history.
