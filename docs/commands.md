# Commands and profile workflow

[Project overview](../README.md) · [Current intent](../INTENT.md)

Reference material moved from README; commands describe available source interfaces,
not proof of current service activation or end-to-end acceptance.

## CLI

```bash
jobwatch run --tier fast|slow|all [--dry-run] [--only <collector>] [--limit N]
jobwatch digest [--dry-run]         # weekly Reddit chatter themes + posting/match stats
jobwatch health                     # last status, count, failures and latency per collector
jobwatch init-db                    # create or migrate the DB (idempotent)
jobwatch --user <name> baseline freeze [--limit N] [--posting-id ID]   # freeze stored inputs and outputs (no model call, no DB write)
jobwatch --user <name> baseline list                                    # this person's frozen baselines
jobwatch --user <name> baseline show <baseline_id> [--cases]            # record, label counts, gate state
jobwatch --user <name> baseline label <baseline_id> <case_id> ...       # the owner's label, at a terminal only
```

- `--dry-run` still writes postings and matches, but leaves new matches `queued` (nothing is published), so the next live run publishes them as `board`. For tests, point `JOBWATCH_DB` at a scratch file.
- `--limit N` caps the postings per collector and stops making requests once N are collected.
- `--only` names one collector: `jobspy_src seek ats_greenhouse ats_lever ats_ashby ats_workable
  ats_smartrecruiters ats_workday ats_pageup ats_employmenthero ats_scouttalent ats_oracle
  ats_successfactors ats_phenom ats_atlassian careers_vic jsonld_pages rss reddit`.
- Exit code: 1 when **every** collector in the run errored (systemd marks the unit failed);
  partial failures exit 0 and show up in `jobwatch health` and the Sources page. There is no failure push.
- Environment overrides: `JOBWATCH_DB`, `JOBWATCH_CONFIG_DIR`, `JOBWATCH_EMPLOYERS`.

## Profile workflow

Discovery runs only for a person whose current profile is confirmed, with a confirmed search scope.

1. **Onboard.** Either let the chat agent guide you (it asks for your files and your questions while it reads them in the background) or use the API under `/api/agent/profile`: upload a CV, letter or evidence file, start a proposal, answer the open questions, correct facts. Facts are marked evidence, inference or unknown; a CV gap alone does not establish unemployment.
2. **Confirm.** Review the confirmation (facts, search scope, daily limits). Confirming needs the approve scope, or in chat your own approval of those exact digests, and writes an immutable version under `profile-versions/`.
3. **Discover.** Collection and assessment then run within the confirmed scope and limits.

Existing installs: discovery stays off until a confirmed profile exists. `jobwatch --user <name> profile adopt` turns your current `profile/` files into version 1, which protects them from being overwritten and keeps them in the history; it authorises no discovery. To turn discovery on, onboard on top of that version: let the chat agent guide you (it can read your existing files through `profile_start` with `use_existing_files`) or start a proposal with `base_version` set to the current version, then confirm the scope shown. A scope with nothing to search for is refused (`profile_incomplete`).

Confirmation does not authorise document preparation, employer messages or submission; those keep their own approvals, and Submit stays on the owner-confirmed path. Walk-through with real requests and responses: [docs/examples/profile-intake.md](../docs/examples/profile-intake.md).

### Field and job discovery

Field discovery compares approved profile facts with versioned occupation
references and saves related occupations as search hypotheses, never as proof
of qualification. The public bundled reference is always available; optional
public datasets are hash-verified under `<data>/reference/<dataset>/<version>/`
(`data` is `users.base_dir()`). Per-person hypotheses and the search plan are
stored under `<person>/discovery/`. Embeddings use the approved paid Qwen route
through OmniRoute and count against the confirmed scope's token budget.

Discovery settings live under `pipeline.agentic`. The confirmed profile is the
canonical source for regional admission, eligibility and personal exclusions;
missing or unresolved facts remain unknown. Search plans rotate supported
query/location pairs within each collector's request caps. Relevance can run in
`shadow` mode, which stores judgments without archiving postings, or `on`, which
archives a current `no` judgment; `uncertain` continues. These controls do not
replace canonical eligibility.

Inspect the configured flags and current state with
`python -m pipeline.agentic.discovery status --user <name>`; status is
read-only. After confirming the current profile and scope, explicitly compute
and cache fields and a search plan with
`python -m pipeline.agentic.discovery refresh --user <name>`. The first refresh
can build the shared reference index through the approved embedding route.
`python -m jobwatch.occupations.datasets status` reports reference dataset
availability without network access. The authenticated API also exposes
read-only `GET /api/agent/discovery/fields`, `/plan` and
`/postings/{posting_id}/relevance` routes under the server-bound person.

The thresholds `similar_at: 0.60` and `duplicate_cosine: 0.95` are uncalibrated;
there is no matching-accuracy claim. Relevance uses embeddings and, below the
similarity threshold, a bounded model extraction; there is no lexical hybrid.
Collector scope is bounded by request caps. Nothing here establishes deployment
or live model behaviour.

Undo by removing the discovery keys under `pipeline.agentic` and the
`pipeline.discovery` tuning block (or set `relevance: off` to stop shadow
judging). To restore postings archived by relevance or the exclusion
pre-filter, first run `python -m pipeline.agentic.discovery restore --user <name>`;
this returns those postings to `ingested`. To remove generated state,
delete that person's `<person>/discovery/` directory and the shared
`<data>/reference/` folder; both are rebuilt on demand. The migration tables
`text_embeddings`, `posting_relevance` and `discovery_spend` can remain unused.

### Frozen baseline

`jobwatch --user <name> baseline freeze` records the stored inputs and outputs of the newest evaluated run of each posting, the gate version, and the approved profile and profile files as they stand at freeze time (`summary.evidence_mismatch` counts runs made on other evidence), so a later matcher or gate can be compared on identical inputs. The recommended point to freeze is before Plan 2 (the revised decision policy) is deployed. A freeze never calls a model, writes no database row and opens the database read-only. Its files live under `<user_dir>/baselines/<baseline_id>/`, private to that person. Duplicate adverts and related employers share a `group_id`, so a comparison can keep them on one side of a split. `list` and `show` print the record and counts, never candidate text; `show` reports `gate_state` (`pre_revision` or `revised`) and whether the gate has changed since the freeze. `label` records the owner's own judgment and works only at a terminal; an agent running shell commands is refused. No numbers in MATCHING.md changed.

Undo: `rm -rf <user_dir>/baselines/<baseline_id>` removes one baseline (`rm -rf <user_dir>/baselines` removes all). Nothing else reads them and nothing else was changed.

Not verified or not available yet:

- The freeze has never been run on a real person's data.
- The database uses WAL journal mode (`jobwatch/db.py`) and the freeze opens it read-only (`mode=ro`). That has not been tested against a live WAL database; the owner's first real freeze must confirm that it opens.
- Labels are absent until the owner adds them.
- Tags are heuristics, not judgments.
- `explicit_exclusion` is limited to the family rules until Plans 2 and 5.
- Replays of the old gate need the baseline's `pinned_profile`.

Walk-through with real output (invented data, no model called): [docs/examples/frozen-baseline.md](../docs/examples/frozen-baseline.md).

### Decision policy

The canonical gate reads the person's confirmed profile. A historical `legacy`
setting is treated as `profile`; no fixed personal-policy fallback is active.
The flag is not part of a run key, so policy changes do not trigger paid model
work. Current source keeps holistic scores as advisory comparison data; they do
not exclude a job. Stored evaluations are re-decided through canonical policy
before downstream use.

With `profile`, the gate reads only the approved facts of the confirmed version:

- **Strategy.** A stated career focus gives `career_focus`. Unemployed with no contrary status gives `employment_first`. Anything else is `balanced`. Strategy guides explanations and ranking; it does not turn missing information into a personal preference.
- **Exclusions are rules only when structured.** An exclusion becomes a rule only as a `{kind, value}` fact, with kind `family`, `employer`, `title_term`, `location` or `work_type`. Free text is never a rule. It stays prompt text and is listed as the open question `exclusion:<fact_id>` until the person gives it a kind.
- **Work rights, hours, level and commute** are read from the approved facts by a documented deterministic grammar. The grammar asks only about missing sections and about locations and exclusions it cannot read. A work-rights, hours, level or commute statement it cannot read is ignored without a question and appears only in the policy JSON. A commute limit with no recognised home is not applied.
- **Missing facts** that change a decision are open questions (for example `location`). An ad whose location cannot be resolved holds rather than archives.

To see the policy and its open questions: `GET /api/agent/profile/policy` (scope `read`) returns `policy`, `mode`, `enabled`, `open_questions` (each `{code, question, why}`) and `reason` when there is no policy. The chat agent's read-only `profile_policy` tool returns the same. Neither writes anything.

Limits: distance uses place data for Victoria only. Other states resolve by state name, state code or capital city, and an unresolved location holds. The product remains Australia-only. Confirmed policy and canonical eligibility are shared across the active and retained assessment paths.

Undo source behavior by reverting the relevant source change; do not treat the historical `legacy` alias as a rollback switch. Profile decisions and records remain per person. Walk-through with invented output (no model called): [docs/examples/decision-policy.md](../docs/examples/decision-policy.md).

### Ranking and explained shortlist

Phase 5 implements importance-weighted evidence coverage,
three explanation labels, deterministic provisional ordering, and optional
within-label personalised ordering from valid owner-choice fits. Unknown facts
remain questions; transferable evidence requires a frozen evidence-matched fact,
not word overlap alone. Priors are neutral, and historical choices move only
through an explicit migration that preserves originals and split assignments.
The design is recorded in [ADR 0007](../docs/adr/0007-ranking-and-explained-shortlist.md)
and [ranking rules](../docs/ranking-rules.md). Phases 1–5 are merged. The historical
[Phase 5 verification](../docs/archive/audits/2026-10-22-shortlist-release.md) retains its
browser failure; the subsequent [browser repair](../docs/archive/audits/2026-10-23-browser-popup.md)
records the merged fix and passing release suite. Deployment remains separate.

Phase 6 (merged in PR #24) adds reversible posting feedback, confirmed exclusion amendments,
bounded genuine-choice prompts and durable selected-job preparation. Native API
and chat use the same domain services and exact human approvals. See the
[worked example](../docs/examples/feedback-selection.md),
[backend contract](../pipeline/agentic/CHAT.md#feedback-and-selected-preparation-phase-6)
and [remaining-roadmap plan](../docs/archive/superpowers/plans/2026-10-23-finish-backend-roadmap.md).

Phase 7 provides private frozen replay, write-once grouped holdout splits, human
labels, missing-label-aware metrics and bounded development monitoring through
`jobwatch evaluate`. Default replay makes zero model calls and uses provisional
ordering. Paid evaluation and local fitting require explicit flags and remain
separate from activation. See [the command example](../docs/examples/evaluation-monitoring.md)
and [backend contract](../pipeline/agentic/CHAT.md#frozen-evaluation-and-bounded-monitoring-phase-7).
The [Phase 7 verification](../docs/archive/audits/2026-10-23-evaluation-monitoring.md) records
3804 passed, 11 skipped, resolved independent review, real synthetic sampler checks
and the installed-database access incident. Source delivery is PR #25; no real
blind-quality study or deployment is claimed.
