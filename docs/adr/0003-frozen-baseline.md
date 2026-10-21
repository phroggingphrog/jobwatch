# ADR 0003: Frozen baseline

Date: 2026-10-21

Status: Accepted owner direction (backend brief of 2026-10-21); delivery has its own acceptance criteria.

## Context

The agreed backend brief asks for the revised matching system to be compared with
the current one on identical frozen inputs, covering previously rejected jobs,
transferable skills, unknown facts, misleading titles, stretch opportunities and
explicit exclusions. It also asks that duplicate advertisements and related
employer cases never leak across evaluation splits, that missing independent
labels stay explicit, and that the inherited holistic 1-5 score be preserved as a
comparison baseline while the replacement policy is validated.

Today the stored artifacts alone do not reproduce the current system. The gate
route is not stored, and `decide()` reads the live profile files, so a stored
evaluation can silently produce a different route after the profile or the gate
source changes. A comparison made against live state would measure that drift and
not the system under test.

## Decision

- A frozen baseline is an immutable per-person folder under
  `<person>/baselines/<baseline_id>/`. It is created only by `freeze_baseline` and
  is never edited afterwards. Only `labels.jsonl` grows.
- Inputs and outputs come from the stored `snapshot`, `structural_inputs`,
  `evaluation`, `candidate` and `model_insights` artifacts of the newest run per
  posting that has both a snapshot and an evaluation. No model is called and no
  database row is written.
- The gate route is not stored today and `decide()` reads the live profile, so the
  route is recomputed offline at freeze time under a pinned copy of the profile
  files. `GATE_VERSION` is recorded with it. It is a sha256 over `gate.py`,
  `location.py`, `person.py`, `reader.py` (which holds the work-rights regexes),
  `candidate/contracts.py`, `candidate/policy.py` and the data files
  `vic-geo.json` and `metro-localities.json`, and each file's hash is also listed
  in `Baseline.gate_dependencies`. Live routes are not stored today, so the version
  is recorded once per baseline, where all routes are recomputed together. Replays
  must use `pinned_profile`.
- The approved profile version is frozen too. `approved.json` is a copy of
  `intake.current_version(person)`. When the profile policy path is active (the
  Plan 2 flag `pipeline.agentic.decision_policy: profile`), `decision_policy.json`
  holds the `DecisionPolicy` built from it. A replay rebuilds the policy with
  `policy_for(person, approved=frozen_approved(baseline_id))`, never from the live
  version.
- Pinning the profile through an environment variable was rejected, because
  `profile_dir()` ignores `JOBWATCH_PROFILE_DIR` for every person but the default
  one. The baseline instead carries its own copy of the profile files and a pinned
  profile directory is applied while a replay runs.
- Each case has a `group_id`. It unions cases that share `content:<ad hash>`,
  `dedupe:<postings.dedupe_key>` or `employer:<normalised company>`. An empty
  employer never merges. Plan 6b uses the group to keep related cases on one side
  of a split.
- Six tags mark the categories the brief requires. They are heuristics that help
  cover those categories; they are not judgments about a job. The status of a
  requirement match is its `judgment.status`, or for a historical match without
  `judgment`: `strong` is demonstrated, `partial` is partial and `missing` is
  unknown.
  - `previously_rejected`: the gate route is `archive`, or the stored run status is
    `archived`, or the stored application status is `skipped`.
  - `transferable_skills`: some match is partial and has at least one evidence
    citation.
  - `unknown_facts`: some match is unknown, or the ad uncertainties in the matching
    diagnostics are not empty, or the location fit is `unknown`.
  - `misleading_title`: the title reads junior (entry-level, junior, graduate,
    intern, trainee, cadet) while the facts say mid or senior seniority or a
    minimum of two or more years; or the title reads senior (senior, lead,
    principal, head of, director) while the facts say entry or junior seniority and
    the minimum years are absent or below two.
  - `stretch`: no match is contradicted, at least one is demonstrated, and some
    critical or high requirement is partial or unknown.
  - `explicit_exclusion`: the gate reason is `policy_excluded`.

  No stored exclusion other than a family rule exists yet, so `explicit_exclusion`
  is `policy_excluded` only until Plans 2 and 5. The owner adds tags of their own
  through labels.
- Owner labels carry `actor='owner'` and are written only by a human CLI command,
  which refuses to run without a terminal, through `write_label`. They are
  append-only: the latest line per case wins (`latest_labels`), the full history is
  kept (`read_labels`), and nothing is imputed for a case the owner has not
  labelled. A model never produces a label.

### What this does not establish

A baseline says nothing about matching quality. It records what the current
pipeline stored and what its gate decides for those inputs under a pinned profile;
it is an input to Plan 6b, which needs the owner's labels before it can report any
quality figure. Tags, groups and synthetic checks do not stand in for those labels.

## Consequences

- Disk use is a few MB per baseline, because large shared artifacts are stored
  once as blobs and referenced from each case.
- Any edit to a gate file changes `GATE_VERSION`. A freeze made after the gate was
  revised is flagged by `gate_state: revised`, so a baseline of the old behaviour
  cannot be confused with one of the new behaviour.
- A baseline holds candidate-bearing copies inside the person's folder, is
  isolated per person and is covered by the normal folder backups.
- Replays that skip `pinned_profile` read the live profile and are not reproducible.
- Accepted design is not deployed behaviour; a merge or passing checks does not
  establish a running backend, and no real baseline exists until the owner freezes
  one.

## Alternatives rejected

- Pinning the profile with an environment variable: `profile_dir()` ignores
  `JOBWATCH_PROFILE_DIR` for every person but the default one.
- Reading the live profile and gate at comparison time: it measures drift in the
  profile and the gate instead of the system under test.
- Imputing or model-generating labels: missing independent labels must stay
  explicit.

## References

- Backend brief 3 (the inherited holistic score is kept as a comparison baseline
  while the replacement policy is validated) and brief 5 (identical frozen inputs,
  required categories, no leakage across splits, explicit missing labels, no claim
  without evidence).
- [INTENT.md](../../INTENT.md), "Preserve the inherited holistic score as a
  comparison baseline".
- The code map, section 1, in
  [the codemap](../superpowers/plans/reference/2026-10-21-codemap.md).
- [ADR 0002](0002-profile-intake-and-approval.md) and
  [the backend contract](../../pipeline/agentic/CHAT.md).
