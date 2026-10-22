# Frozen evaluation and monitoring — illustrative command walkthrough

This walkthrough documents the Phase 7 CLI shape and privacy boundary. IDs, case counts, hashes, labels, and output snippets are invented examples; they are not captured command output and contain no candidate or advertisement data. Phase 6 is merged in PR #24. Phase 7 review and required full local checks are pending. No live baseline, holdout access, paid replay, or fit is represented here.

Use the selected person's runtime files and existing frozen records. Do not copy candidate facts, preferences, job ads, or label notes into this repository. Use the owner's normal approved model route only for a separately authorized paid evaluation, with a token budget in the command.

The commands below use `<person>`, `<baseline-id>`, `<case-id>`, `<result-id>`, and `<tokens>` as placeholders. Replace them with that person's IDs and an intentional positive token ceiling. Run the commands one person at a time.

## 1. Freeze stored cases

```bash
jobwatch --user <person> evaluate cases --limit 500
```

The operation reads the Jobwatch database read-only, freezes stored evaluated cases and their relevant context into that person's private baseline, and makes no model call. Use repeated `--posting-id ID` arguments to limit the freeze to selected postings. The baseline captures its gate provenance, approved evidence hash, runtime/discovery configuration and eligible owner choices; later changes do not silently replace that context.

List existing frozen baselines without printing candidate or posting text:

```bash
jobwatch --user <person> evaluate cases --list
```

## 2. Create the grouped split

```bash
jobwatch --user <person> evaluate split <baseline-id>
```

The default seed is `1729`. The command groups duplicate ads and related employers, then writes a sealed, write-once split with `ceil(30% of groups)` in holdout and at least one group in development. The split command prints identifiers, hashes and case IDs. Repeating it with the same seed reads the same split; requesting another seed conflicts rather than moving cases after results can exist.

## 3. Label only genuine human judgments

At an owner's interactive terminal, record a specific judgment. A note alone does not count as a metric label.

```bash
jobwatch --user <person> evaluate label <baseline-id> <case-id> \
  --suitable yes --relevance 3 --exclusion-violation no
```

The owner can use `--suitable yes|no|unsure`, `--relevance 0..3`, `--exclusion-violation yes|no|unsure`, and optional tags or notes. The terminal check prevents an agent shell from asserting that a human made the judgment. Labels are append-only, and the latest owner label for a case is used. A holdout label additionally requires `--allow-holdout`; that access is audited. Do not label from model output or treat a missing label as a negative judgment.

## 4. Replay the development partition

```bash
jobwatch --user <person> evaluate replay <baseline-id> --partition development \
  --limit 500 --seconds 300
```

This bounded default replay makes zero model calls. It recomputes the frozen cases through the canonical eligibility gate and provisional ranking, records routes, ranks, coverage, uncertainty, citation checks and measured usage, then saves an immutable result under that person's evaluation directory. It writes no production run, package, profile, shortlist or active fit. The output prints a result ID and summary counts; it does not print case text.

To access holdout, make the intent explicit for each operation:

```bash
jobwatch --user <person> evaluate replay <baseline-id> --partition holdout \
  --allow-holdout --limit 500 --seconds 300
```

The holdout access log records the operation and provenance before cases are returned. Holdout is not used by development monitoring or optional fitting.

A paid evaluation is a separate explicit action. It requires both flags and uses configured approved routes and budgets:

```bash
jobwatch --user <person> evaluate run <baseline-id> --partition development \
  --paid --budget-tokens <tokens> --limit 500 --seconds 300
```

Without both `--paid` and a positive `--budget-tokens`, paid replay is refused. Inspect the frozen inputs and intended case scope before making this call. Paid evaluation outputs remain diagnostics and do not activate a model or submit an application.

## 5. Run development monitoring

```bash
jobwatch --user <person> evaluate monitor <baseline-id> --limit 500 --seconds 300
```

Monitoring is development-only, has hard caps of 500 cases and 300 seconds, and never reads the label log. Its replay is offline by default. A monitoring run does not provide a labelled quality estimate. The optional fit path can run only in the development partition and only over genuine, frozen owner choices:

```bash
jobwatch --user <person> evaluate run <baseline-id> --partition development \
  --fit --limit 500 --seconds 300
```

Fit eligibility and fit acceptance are reported as evaluation outcomes. The accepted model is not activated, and suitability labels never create training choices.

## 6. Read a private report

Use the exact stored result ID from a replay or run:

```bash
jobwatch --user <person> evaluate report <baseline-id> <result-id>
```

For a holdout result, explicitly authorize the report read and audit it:

```bash
jobwatch --user <person> evaluate report <baseline-id> <result-id> --allow-holdout
```

The command returns the private JSON and Markdown paths. Report files are deterministic for identical inputs, content-addressed, written once, and stored with private directory/file modes. They include IDs, route/status enums, ranks, numeric metric fields, counts, hashes and version provenance. They omit candidate and ad text, owner notes and raw owner labels, free-form reasons, and error strings.

## Reading the metrics

Every label-based metric reports `missing_labels` until it has at least ten applicable owner judgments; its value stays null below that threshold. Suitability, relevance and exclusion labels have separate applicable counts. Precision and nDCG at 5 and 10 use a condensed human-labelled ordering: relevance 2 or 3 is positive, while a suitability-only judgment maps to grade 1 or 0. The metric states its basis and coverage. Cases without applicable labels are not assumed irrelevant.

A partial or bounded replay is explicitly `partial_replay`; it cannot support a comparative quality claim. Missed suitable jobs, exclusion violations, citation indicators, unknown and contradicted evidence, unresolved questions, disclosure, tokens and latency are distinct fields. A citation failure means a citation integrity check failed; it does not independently decide qualification. Missing latency is `not_measured`. No metric corrects for exposure or selection bias: propensities are not recorded, and pending outcomes remain censored. The sample is frozen historical data, and the ranking is provisional.

## Undo and limits

Undo a source release by reverting its reviewed source changes. Preserve baseline inputs, labels, split, holdout access log, replay results, fits and reports as historical evidence. Do not erase them as part of source rollback.

This example describes CLI source behavior, not a completed Phase 7 release. Required full checks and independent review are pending; no live records or operations have been used. Synthetic examples demonstrate shapes only, not recommendation quality or deployment.
