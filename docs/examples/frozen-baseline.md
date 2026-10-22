# Frozen baseline: command walk-through

A worked example of `jobwatch baseline` (freeze, list, show, label). The contract is in
[CHAT.md](../../pipeline/agentic/CHAT.md) ("Backup, release and undo") and the reason for it in
[MATCHING.md](../../pipeline/agentic/MATCHING.md) ("Remaining experiment before policy promotion").
Every command and output below was captured by running the end-to-end test
`tests/test_cli_baseline.py::test_cli_end_to_end` with `JOBWATCH_PRINT_TRANSCRIPT=1`. The test
builds a scratch database and a scratch profile from invented postings and an invented candidate.
Nothing here is a real person's record, and no model was called: a freeze only reads stored rows.

Conventions:

- 64-character digests are shortened to eight characters and an ellipsis (`b76dfaea…`). Baseline
  ids (`bl-<time>-<8 hex>`) and case ids (`c-<posting id>-<8 hex>`) are already short and are
  shown in full.
- The test runs as a single scratch person, so the commands are printed without the global
  `--user <name>` flag. On a real install put it first: `jobwatch --user <name> baseline freeze`.
- Lines marked `... omitted here` are shortened. Everything else is as printed, with one
  exception: the `implementation_version` value names the retrieval stack the run used and is
  replaced by `"... omitted here"`.
- The test terminal is simulated so `label` can run. Without a terminal, `label` prints
  `human_required` and writes nothing, so an agent running shell commands cannot label.

## When to freeze

Freeze before the revised decision policy (Plan 2) is deployed. That is the recommended point:
the stored evaluations then still come from the gate as it stands today, so a later comparison
runs the old and the new gate over identical inputs. Freezing earlier or later is allowed; the
baseline records which gate it was frozen under (`gate_state` below), so it can never be mistaken
for the other.

A freeze never calls a model and writes no database row. It opens the database read-only, reads
the newest evaluated run of each posting, and writes files into the person's own folder.

## 1. Freeze

Takes the newest evaluated runs, up to `--limit` postings (default 500), or exactly the postings
named with `--posting-id`. A posting that cannot be frozen is skipped and counted, with its reason.

```bash
jobwatch baseline freeze --limit 2
```

```text
froze bl-20261021T154735Z-b76dfaea: 2 cases, 0 skipped
```

## 2. List

One line per baseline, oldest first: id, creation time, case count, the profile version it was
frozen under, and the gate state.

```bash
jobwatch baseline list
```

```text
bl-20261021T154735Z-b76dfaea  2026-10-21T15:47:35+00:00  cases=2  profile_version=2  gate=pre_revision
```

## 3. Show, with cases

`show` prints the record and counts only. It never prints candidate text. `--cases` adds one line
per case after the record.

```bash
jobwatch baseline show bl-20261021T154735Z-b76dfaea --cases
```

```json
{
  "approved_sha256": "8501fd14…",
  "baseline_id": "bl-20261021T154735Z-b76dfaea",
  "case_ids": [
    "c-43-416f0828",
    "c-44-0fd3161d"
  ],
  "content_sha256": "b76dfaea…",
  "created_at": "2026-10-21T15:47:35+00:00",
  "decision_policy_sha256": null,
  "evidence_bundle_hash": "e6955150…",
  "gate_changed_since_freeze": false,
  "gate_dependencies": {
    "jobwatch.candidate.contracts": "5a6e038b…",
    "jobwatch.candidate.person": "5a8ba3fa…",
    "jobwatch.candidate.policy": "21db2fd3…",
    "jobwatch.reader": "b4d5cf2c…",
    "pipeline.agentic.gate": "4ecb1d24…",
    "pipeline.agentic.location": "e1b9b0f5…",
    "pipeline.agentic/data/metro-localities.json": "58b56b9d…",
    "pipeline.agentic/data/vic-geo.json": "ef5f8c44…"
  },
  "gate_state": "pre_revision",
  "gate_version": "9b11d024…",
  "git_commit": "a0cfdf86b7bd07c56ffd5342f835b51754f50fad",
  "implementation_version": "... omitted here",
  "labels": {
    "labelled": 0,
    "unlabelled": 2
  },
  "matching_version": "requirement-evidence-v3",
  "missing_tags": [
    "transferable_skills",
    "unknown_facts",
    "misleading_title",
    "stretch",
    "explicit_exclusion"
  ],
  "person": "owner",
  "policy": {
    "allowed_families": [
      "accounting",
      "finance_clerical",
      "back_office_admin",
      "data_analyst",
      "... 17 more families omitted here"
    ],
    "excluded_codes": [
      "431111",
      "541211"
    ],
    "version": "owner-targets-v1"
  },
  "profile_files_sha256": {
    "career_ops_profile.md": "4bb5d0e1…",
    "cv.md": "f39dc3af…",
    "interests_and_criteria.yaml": "b9cf6b82…",
    "master_resume.md": "d53016d4…",
    "profile.yaml": "2bff5614…"
  },
  "profile_version": 2,
  "runtime_config_sha256": "5c39469d…",
  "summary": {
    "cases": 2,
    "decision_errors": 0,
    "evidence_mismatch": 0,
    "groups": 2,
    "largest_group": 1,
    "routes": {
      "archive": 1,
      "draft": 1,
      "error": 0,
      "hold": 0
    },
    "skipped": {},
    "tags": {
      "explicit_exclusion": 0,
      "misleading_title": 0,
      "previously_rejected": 1,
      "stretch": 0,
      "transferable_skills": 0,
      "unknown_facts": 0
    }
  }
}
c-43-416f0828 43 draft/eligible -
c-44-0fd3161d 44 archive/score_below_threshold previously_rejected
```

How to read it:

- **`gate_state`** is `pre_revision` when `gate_version` equals the version of the gate as it
  stood before the revisions (`PRE_REVISION_GATE_VERSION`), and `revised` otherwise. A baseline
  frozen as `pre_revision` is the old gate's record; one frozen as `revised` is not (the freeze
  prints a warning on stderr in that case). `gate_version` hashes the gate sources listed in
  `gate_dependencies`, so a change to any of them changes it.
- **`gate_changed_since_freeze`** is `false` while the code now on disk hashes to the frozen
  `gate_version`, and `true` once any gate source has changed since.
- **`labels`** counts the owner's labels. Labels are absent until the owner adds them, so
  `unlabelled` equals `cases` at first.
- **`missing_tags`** names the heuristic categories that no case in this baseline has. An empty
  category is a gap in coverage, not evidence that such cases are absent from the real data.
- **`summary.groups`** counts duplicate-advert and related-employer groups (`group_id`); a
  comparison must keep a whole group on one side of a split. **`routes`** counts the gate route
  recomputed from the frozen inputs. **`decision_errors`** is the number of cases whose
  recomputation ended in `error`, and **`evidence_mismatch`** the number whose stored run used an
  evidence bundle other than the one the baseline records.
- **Each case line** is `case_id posting_id route/reason tags`. The tags are the heuristic tags
  (and the owner's label tags, once there are any); `-` means none.

## 4. Label

Only the owner labels, at a terminal. A label needs at least one of `--suitable`, `--relevance`
(0 to 3), `--exclusion-violation` or `--tag`; a note alone is refused as `empty_label`. A label
is appended to `labels.jsonl`; earlier lines are never rewritten, and the newest line for a case
wins. Labelling does not change the baseline's frozen content.

```bash
jobwatch baseline label bl-20261021T154735Z-b76dfaea c-43-416f0828 --suitable yes --relevance 3 --tag stretch
```

```text
labelled c-43-416f0828
```

## 5. Show again

The record is unchanged except that `labels` now counts the new label. The owner's `stretch` tag
is a label, not a heuristic, so `summary.tags` and `missing_tags` still describe the heuristics.

```bash
jobwatch baseline show bl-20261021T154735Z-b76dfaea
```

```json
{
  "... every field before labels: identical to step 3, omitted here",
  "labels": {
    "labelled": 1,
    "unlabelled": 1
  },
  "... every field after labels: identical to step 3, omitted here"
}
```

## Undo

A baseline is a private historical folder. Phase 7 replay, grouped splits and reports
read it, so source rollback must preserve it together with labels, split and access
history, results, fits and reports. Revert source through the normal reviewed release
path; do not delete baseline folders or downgrade schema metadata as a rollback step.

Freezing does not change a production posting, run, preference set or approved profile.
A freeze that fails part-way removes its staging folder before anything is published.
After a baseline has been split, full `baseline show` inspection requires
`--allow-holdout` and records audited access; use development-only monitoring for
routine checks. See [the evaluation example](evaluation-monitoring.md).

## Limits and what is not verified

- The freeze has never been run on a real person's data. This page runs on invented data only.
- The jobs database uses WAL journal mode (`jobwatch/db.py`, `connect`), and the freeze opens it
  read-only (`mode=ro`). That combination has not been tested against a live WAL database. The
  owner's first real freeze must confirm that it opens; if it does not, nothing has been written
  and the error is the whole result.
- Labels are absent: no baseline contains an owner label until the owner adds one.
- Tags are heuristics derived from stored fields, not judgments. A tag that is missing
  (`missing_tags`) means no case matched the heuristic.
- `explicit_exclusion` is limited to the family rules until Plans 2 and 5; it does not yet cover
  the owner's wider exclusions.
- A replay of the old gate needs the baseline's `pinned_profile`, the copy of the profile files
  frozen with it. Replaying against the live profile would not reproduce the frozen decision.
