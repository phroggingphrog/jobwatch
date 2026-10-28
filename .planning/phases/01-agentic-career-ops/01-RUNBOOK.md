# Phase 01 operator runbook (Task 4 / 01-08)

## Safety boundary

This runbook is an offline verification and handoff guide, not authorization to run against candidate data. The live path remains default-off. No applications are submitted, no forms are typed, and no employers are contacted. Use paid OmniRoute model IDs only (`openai/`, `claude/`, `google/`); do not substitute free or stealth routes, add subscriptions, or send candidate data to another route. Synthetic fixtures must never be attested as real jobs.

The agentic batch CLI currently exposes only `--dry-run` inventory mode; its non-dry-run path is not yet a functional, snapshot-authorized operator command. Do not infer live-run support from the CLI's zero exit status. Release/live QA is blocked until snapshot admission, database package-schema integration, real PDF-evidence inputs, and end-to-end cross-layer verification are complete and independently approved. The read-only checker is currently a manifest-backed audit adapter for database layouts containing `pipeline_state`, `applications`, and `drafts`; it cannot yet audit the newer agentic persistence schema, which has no complete package/evaluation record.

## Offline verification

From the project root, run the focused synthetic acceptance suite:

```sh
PYTHONPATH=$PWD /home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agentic_acceptance.py
```

Run the full suite when the checkout has its test dependencies (on 2026-10-09 it reports 1,830 passed, 1 skipped, and 1 failure in the unrelated `tests/web/test_ai.py::test_load_rows_attaches_ai_and_state_in_one_query`; investigate that existing query-count regression separately):

```sh
PYTHONPATH=$PWD /home/phroggingphrog/apps/jobwatch/.venv/bin/python -m pytest -q -p no:cacheprovider
```

The acceptance checker is read-only and does not run model calls. It requires an explicit database, data root, and operator-prepared JSON snapshot attestation; entries must have integer `posting_id` and `synthetic: false`. Exact `run_key`, `evaluation_hash`, `evidence_hash`, and `review_hash` fields are required and bind the attestation to package evidence. Protect the manifest as private evidence (mode 600, local only); do not include personal text or upload it. Example after schema readiness, using a copy/snapshot only:

```sh
umask 077
PYTHONPATH=$PWD /home/phroggingphrog/apps/jobwatch/.venv/bin/python scripts/agentic_acceptance.py \
  --db /path/to/read-only-snapshot.sqlite --data-root /path/to/snapshot-data \
  --snapshot-manifest /path/to/approved-snapshot.json
```

Exit 0 means at least 20 distinct rows passed this checker; exit 1 means the threshold was not met; exit 2 means the audit could not run. A pass is not live-release authorization. Inspect only safe IDs/counts/reasons in its output. A non-ready, legacy, synthetic/unattested, stale, malformed, missing/out-of-root, hash-mismatched, or failed-PDF package does not count.

## Dry-run and snapshot execution

The existing `pipeline.agentic.cli` supports only `--dry-run` and prints an inventory message. It does not query a snapshot, execute a batch, or enforce the intended <=20 admission limit; do not use it as a live execution command. There is no approved live snapshot command at this phase. Do not run `pipeline.agentic.service.run_agentic_job` manually or enable the agentic flag against a live database. Release must first provide a bounded snapshot command, demonstrate that it excludes unrelated work (including legacy DLQ items), and record the authorized IDs and operator approval.

When a future command is approved, execute one explicitly authorized snapshot of at most 20 jobs, record proposed/processed/READY/held/failed counts without candidate text, and stop between batches. Do not subscribe to or configure additional model providers. If research is unavailable, proceed with explicit unavailable status; never make research a precondition that silently routes to a free model.

## Stop, rollback, and recovery

1. Emergency stop: stop admitting agentic jobs by leaving `agentic.enabled` false; if an approved run is in flight, stop the runner at its supported boundary and preserve its checkpoint/ledger. Do not delete run, budget, application, or draft records.
2. Roll back code/config with the recorded Git commit/revert procedure after an independently reviewed change; restore the prior default-off config. Keep the append-only ledger and evidence artifacts for reconciliation.
3. Do not retry an ambiguous package commit or allocate a new draft version until reconciliation confirms the prior operation's state. Do not retry unrelated legacy DLQ entries as part of this work.
4. After an actual authorized operation, Release records counts, approval reference, and undo in `~/brain/WHAT-HAPPENED.md`; updates the existing local todo only after the operation actually happened. Record no candidate text, contact data, answers, or prompts.

## Manual verification walkthrough (synthetic/local only until release approval)

1. Run the focused suite and inspect test outcome. Exercise full-ad/two-pass evaluation, requirement gaps, fresh independent review, both PDF verification outcomes, manifest hashes, and READY/held paths using fictional inputs and injected transport/verifier fixtures only.
2. For release QA, use a protected read-only DB/data snapshot and the approval manifest; run the checker above. Verify it rejects synthetic/unattested IDs, old/legacy rows, stale hashes, non-READY state, missing/tampered PDFs, and verifier failures. Confirm DB `total_changes` remains unchanged in tests.
3. Open the locally configured board through its existing test client and confirm the synthetic job shows clear READY/review/verification status and never implies submitted. Confirm the page returns HTTP 200 and escaped content. No live service restart or public-board browser walkthrough is authorized here.
4. Count only distinct, independently approved real jobs with current evaluation/evidence/review hashes and passing CV+letter checks toward the 20-job acceptance threshold. If fewer qualify, report the shortfall and responsible next operator; never pad with fixtures or legacy drafts.
5. Before any live backlog execution, require recorded board/owner authorization, verified snapshot-bounded CLI behavior, reviewed rollback, and independent QA sign-off. Until then, do not enable or process live jobs.

## Operator handoff

Built artifacts and synthetic tests are not evidence of live acceptance. Current release status: **not verified against 20 real jobs; no live processing authorized by this runbook**. T19 (answer-bank/form filling) remains separate and incomplete; this phase does not type application forms or submit applications. The owner remains the only submitter.
