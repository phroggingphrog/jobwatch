# ADR 0009: Frozen evaluation and development monitoring

Date: 2026-10-23

Status: Accepted owner direction and Phase 7 implementation in review; full local checks and review are pending. This records the boundary and intended source behavior, not release completion.

## Context

Phase 7 (#22) adds a reproducible comparison of the canonical Jobwatch gate and provisional ranking over frozen inputs. The comparison needs human judgments, a held-out group split, and monitoring without turning an offline diagnostic into a live model run or a claim of recommendation quality. Phase 6 was merged in PR #24; Phase 7 review and the required full checks remain outstanding.

## Decision

1. **Freeze inputs and configuration.** `jobwatch evaluate cases` captures stored cases, approved evidence context, runtime and discovery configuration, policy, and eligible genuine owner-choice records into the current person's private baseline area. Freezing reads the database read-only and calls no model. The baseline and its input hashes pin the context used by later replay. A baseline's source gate provenance remains visible; a baseline does not become a pre-revision baseline merely because it is replayed later.
2. **Split by related-ad and employer groups.** `jobwatch evaluate split` derives groups from explicit historical keys and current posting/ad identity, assigns whole groups deterministically using a seed (default `1729`), and allocates `ceil(30% of groups)` to holdout while leaving at least one group for development. The sealed split is written once. A repeat with the same seed returns it; a different seed conflicts. Duplicate or related groups cannot cross the boundary.
3. **Replay the canonical decision path.** `replay`, `run`, and `monitor` use frozen evidence and policy with the current canonical eligibility gate and provisional ranking rules. They do not write production runs, profile state, shortlist state, or packages. Default replay is offline and makes zero model calls. Bounded defaults are 500 cases and 300 seconds. `monitor` is development-only, capped at 500 cases and 300 seconds, and does not read human labels. A paid replay requires both `--paid` and a positive `--budget-tokens`; it is an explicit evaluation call, not a default. Results preserve baseline route and advisory score ordering for comparison.
4. **Keep holdout access explicit and audited.** Development replay, fit, and monitor do not open holdout cases. A holdout replay or report requires `--allow-holdout`, and access is appended to the person's private holdout audit log with operation and data, split, source, and person provenance. Holdout labels also require explicit audited access. The authorization is per operation; it does not promote holdout into development data.
5. **Use genuine labels and state their limits.** Metrics use only applicable owner labels on cases replayed by both arms. Suitable, relevance (0–3), and explicit-exclusion judgments have separate denominators. Each label-based metric needs at least ten applicable judgments; below that it reports `missing_labels`, the applicable count and minimum, and a null value. Ordering metrics are precision and nDCG at 5 and 10 over the condensed human-labelled ordering; unlabelled cases do not become negative judgments. A bounded replay reports `partial_replay`, which prevents comparative quality claims. Pending outcomes remain censored, and no propensity correction is inferred without recorded propensities.
6. **Keep diagnostics bounded.** Missed-suitable comparisons and exclusion violations remain separate from deterministic gate and citation indicators. Citation checks only test citation integrity; they are not an independent judgment that a candidate is qualified. Unknowns, contradictions, unresolved questions, uncertainty disclosure, and missing usage/latency are reported as diagnostics. Latency with no recorded measurement is `not_measured`. Exposure and selection bias, the frozen sample, condensed labels, absent propensities, and the provisional ranking are disclosed. None of these measures qualifies a person or establishes real-world recommendation quality.
7. **Write private, deterministic reports.** Reports contain IDs, closed status/route/label enums, numeric counts and metrics, and hashes/version provenance. They exclude candidate or advertisement text, owner notes, arbitrary reasons and errors, and raw owner labels. JSON and Markdown are deterministic for the same inputs; content-addressed files are written once under private directories (directories mode `0700`, files mode `0600`). A content conflict fails rather than overwriting prior evidence.
8. **Constrain optional fitting.** `--fit` is an optional local fit over frozen, genuine owner choices in development cases only. It uses the canonical sampler and unchanged acceptance gates. It does not manufacture choices from suitability labels, access holdout choices, update the active preference fit, or activate a production model. Eligibility and acceptance remain distinct from activation.

The CLI shape is `jobwatch --user <person> evaluate ...`. The baseline and all frozen files are scoped to that selected person. Run one person's command at a time; `--user all` is not appropriate for these operations.

## Consequences

Evaluation is reproducible against pinned inputs, but the current gate and ordering are still provisional. A split protects related cases from leakage; it does not make the frozen sample representative. Sparse or partial labels remain visibly insufficient. Evaluation reports can be shared for review without exporting the underlying text, but IDs and hashes still identify a private artifact and remain in the person's protected area.

Phase 7 source implementation is under review. No real-person baseline has been frozen, no holdout has been accessed, no paid replay or fit has been run, and no production fit, service, timer, or deployment has been activated. Source and synthetic checks alone do not establish runtime behavior or recommendation quality.

## Release and undo

Complete Phase 7 only after the required local checks and independent review pass. Hosted CI is disabled and is not a completion gate. Undo source behavior through a reviewed revert while preserving frozen baselines, labels, split and holdout-access history, replay results, fits, and reports. Do not delete or rewrite evaluation records as a rollback step.

## References

- [Jobwatch intent](../../INTENT.md)
- [Backend contract](../../pipeline/agentic/CHAT.md)
- [Frozen evaluation and monitoring example](../examples/evaluation-monitoring.md)
- [Phase 7 plan and issue #22](../superpowers/plans/2026-10-23-finish-backend-roadmap.md)
- `pipeline/agentic/eval_data.py`
- `pipeline/agentic/evaluate_runs.py`
- `pipeline/agentic/eval_metrics.py`
- `pipeline/agentic/eval_fit.py`
- `jobwatch/evaluation_cli.py`
- `jobwatch/reports/evaluation.py`
