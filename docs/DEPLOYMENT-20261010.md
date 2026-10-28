# Jobwatch deployment candidate — 10 October 2026

This is a deployment procedure, not a record of a live cutover. The owner must approve the live cutover before the activation commands below are run. Nothing here submits an application. No live service, timer, database or employer form was changed while writing it.

## Candidate and acceptance boundary

Candidate checkout: `/home/phroggingphrog/Documents/Codex/2026-10-10/continue-and-take-over-the-jobwatch/work/jobwatch`, branch `codex/deployment-ready`. Record the final clean HEAD with the commands below; deploy that immutable revision and its committed `uv.lock`, never an uncommitted working tree.

The real Deep Agents 0.7.23 graph invokes bounded candidate, JD, evaluator, writer, reviewer and answer-planning roles through the existing paid local OmniRoute gateway. The runtime uses exactly one configured credential, without hidden retries to another credential or provider. Optional public employer research uses the existing SearXNG instance at `127.0.0.1:8888`; it does not require another service. Only public posting facts enter research queries. Candidate qualifications remain grounded in the private evidence snapshot.

Captured acceptance at this document's initial revision:

| Check | Evidence | Limit |
|---|---|---|
| Deep Agents execution and budgets | 44 runtime tests passed | Deterministic injected transport; actual framework execution |
| Canonical DB, recovery, ledger, CLI, configuration | 27 tests passed | Temporary migrated DB and synthetic evidence |
| Tailored documents | Three different employer packages rendered and passed the actual PDF verifier | Synthetic model responses; no claim of real writing quality |
| Existing deterministic pipeline and board | 38 tests passed | Local synthetic tests outside the sandbox's asyncio restriction |
| Paid local gateway | Actual candidate/evaluation smoke made 7 calls, approximately 19,000 tokens, with explicit credential index 1 | This identified a family-label gate issue; a successful final package and real-site pre-submit acceptance were not established by that run |
| New board projection | Actual graph-to-PDF-to-card/filter/table checks pass; corrupt artifacts are held | Final integrated regression is recorded by the release owner |
| Browser acceptance | See final release acceptance report | Local browser fixtures do not establish acceptance on an employer's real site |

The release owner must record the final full-suite result, any paid acceptance reruns and any real-site walkthrough separately before describing this candidate as ready. The browser must fill and attach up to the final Submit control, leave it untouched, and retain the owner-visible page. Missing facts remain explicit owner questions; CAPTCHA and MFA are completed by the owner in the embedded browser.

## 1. Prepare and verify the immutable release

Run in the candidate checkout. These commands install candidate dependencies and run synthetic tests; they do not activate the live deployment.

```bash
JW_RELEASE=/home/phroggingphrog/Documents/Codex/2026-10-10/continue-and-take-over-the-jobwatch/work/jobwatch
cd "$JW_RELEASE"
test -z "$(git status --porcelain)"
uv sync --frozen --python 3.12 --extra dev --extra browser
.venv/bin/python -m pytest -q
git diff --check
```

Python is restricted to 3.12. `deepagents==0.7.23` is pinned in `pyproject.toml`; the exact LangChain, Playwright and other resolved versions are in `uv.lock`. The browser extra is required for the embedded application browser. Do not replace the frozen sync with an unrestricted upgrade.

Chromium needs the native libraries selected for this host by Playwright. WeasyPrint needs Pango/font libraries; this host already has Pango and DejaVu. Its current PDF verification passes, with a warning about HarfBuzz-Subset being required by a future release. Install native dependencies and browser binaries only as part of the approved dependency preparation:

```bash
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
.venv/bin/python -m playwright install --with-deps --no-remove chromium
.venv/bin/python -m playwright install --list
.venv/bin/python -m weasyprint --info
```

`--no-remove` preserves previously installed Playwright browsers for rollback. No graphical desktop or new systemd unit is required: the existing web process starts a private Chromium process only when the owner opens an application browser. The owner sees and controls the page inside the protected board. Browser profiles, screenshots and form content are private data; do not publish them or copy them into git.

Before activation, confirm the board remains protected by its existing access control, the web listener is loopback `127.0.0.1:8960`, OmniRoute is loopback `127.0.0.1:20128`, and existing SearXNG is available if public research is enabled. Do not print gateway key files or service environment values.

## 2. Approved cutover: stop writers and preserve rollback copies

The remaining commands change the live installation and require the owner's explicit cutover approval. Use the same shell for the variables below. If `JOBWATCH_DB`, `JOBWATCH_DATA_DIR`, `JOBWATCH_PROFILE_DIR` or the service's config directory differs from the standard paths, resolve that before proceeding; do not back up one database and deploy against another.

```bash
umask 077
JW_LIVE="$HOME/apps/jobwatch"
JW_DATA="$HOME/brain/data/jobwatch"
JW_BACKUP="$HOME/archive/jobwatch-cutover-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$JW_BACKUP"
test -z "$(git -C "$JW_RELEASE" status --porcelain)"
test -z "$(git -C "$JW_LIVE" status --porcelain)"
git -C "$JW_LIVE" rev-parse HEAD > "$JW_BACKUP/previous-revision.txt"
git -C "$JW_RELEASE" rev-parse HEAD > "$JW_BACKUP/release-revision.txt"
git -C "$JW_RELEASE" bundle create "$JW_BACKUP/release.bundle" HEAD
systemctl --user stop jobwatch-fast.timer jobwatch-slow.timer jobwatch-outcomes.timer jobwatch-digest.timer
systemctl --user stop jobwatch-fast.service jobwatch-slow.service jobwatch-outcomes.service jobwatch-digest.service jobwatch-web.service
cp -a "$JW_LIVE/config" "$JW_BACKUP/config"
tar -C "$JW_LIVE" -czf "$JW_BACKUP/previous-venv.tar.gz" .venv
tar -C "$JW_DATA" -czf "$JW_BACKUP/private-data.tar.gz" .
```

If either checkout is dirty, stop and preserve/reconcile those changes first. Never use `git reset --hard`, delete private state, or overwrite an unknown configuration to get around the check. The archive includes the original SQLite/WAL files, ledger, profile and documents after writers stop. Keep it private. Browser sessions should be closed through the board before stopping the web process; restarting loses the open tab, but private browser profiles remain on disk.

Install the recorded code and frozen environment:

```bash
git -C "$JW_LIVE" fetch "$JW_BACKUP/release.bundle" HEAD
git -C "$JW_LIVE" checkout --detach FETCH_HEAD
cd "$JW_LIVE"
uv sync --frozen --python 3.12 --extra browser --extra dev
.venv/bin/python -m playwright install --no-remove chromium
```

Existing local employer registries, secrets and environment overrides must remain intact. Compare the backed-up configuration with the candidate before changing settings. The selected switch is the **nested** `pipeline.agentic.enabled`, used by timers, CLI and the board's Draft worker. There must be exactly one `credential_index` key in that section. Index 1 selects the existing alternate local gateway credential verified in the synthetic paid smoke; it does not authorize another model route.

```yaml
pipeline:
  enabled: true
  agentic:
    enabled: true
    worker_model: openai/sol
    evaluator_model: openai/sol
    reviewer_model: openai/astra
    credential_index: 1
```

Apply only the activation setting programmatically after the reviewed configuration is in place:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml
p = Path('config/jobwatch.yaml')
d = yaml.safe_load(p.read_text())
a = d['pipeline']['agentic']
assert a['credential_index'] == 1
a['enabled'] = True
p.write_text(yaml.safe_dump(d, sort_keys=False))
PY
```

The first application startup uses existing DB migrations. Agentic runs add `agentic_batches`, `agentic_runs`, `agentic_budget_ops`, `agentic_artifacts`, `agentic_packages` and `agentic_ledger_outbox`; canonical applications/drafts/events retain their existing schema. Private artifacts live under `data/agentic/<run-key>/` and `data/drafts/<application-id>/v<version>/`, outside the evidence profile. Original IDs and owner-controlled outcome states are preserved.

The outbox journals committed canonical writes durably; retrying the same bound run reconciles it. `jobwatch reindex` refuses while agentic outbox rows remain unsent. Do not clear the outbox, reset budgets or rebuild the database to force recovery. Accepted packages can finish publication after their model budget expires without another paid call.

## 3. Smoke checks, then resume the existing timers

Start only the web process first. No new service or timer is added.

```bash
systemctl --user start jobwatch-web.service
systemctl --user is-active jobwatch-web.service
curl --fail --silent --output /dev/null -H 'Host: localhost' http://127.0.0.1:8960/
.venv/bin/python -m pipeline.agentic.cli --db "$JW_DATA/jobwatch.db" --limit 3 --dry-run --snapshot "$JW_BACKUP/inventory.json"
```

The dry-run reads local ads/profile, writes only the requested hash-only inventory and makes no model or employer calls. An execution of that exact reviewed inventory is explicit:

```bash
.venv/bin/python -m pipeline.agentic.cli --db "$JW_DATA/jobwatch.db" --snapshot "$JW_BACKUP/inventory.json"
```

Check the protected board's candidate assessment, full job evaluation, score/archetype sorting, hold reasons, three varied draft packages and PDF downloads. A ready package says **Documents ready**; it does not mean an employer form was filled. Open the application preparation page, start its embedded browser, complete login/MFA if needed, inspect the fields, run the bounded prefill and confirm both verified attachments. Any changed package, stale page, unknown required answer or blocked navigation must produce a hold/partial result. Confirm the final Submit control is untouched and the live form can still be inspected by the owner. Do not treat a local fixture screenshot as this real-site check.

Only after smoke checks pass:

```bash
systemctl --user start jobwatch-fast.timer jobwatch-slow.timer jobwatch-outcomes.timer jobwatch-digest.timer
systemctl --user is-active jobwatch-web.service jobwatch-fast.timer jobwatch-slow.timer jobwatch-outcomes.timer jobwatch-digest.timer
```

Record the deployed revision, configuration changes, acceptance results, existing on-demand browser behavior and rollback location in the owner's change log. Do not include profile text, form answers, screenshots, credentials or private model payloads in public logs or reports.

## 4. Rollback without losing applications or outcomes

The normal feature rollback is to set `pipeline.agentic.enabled: false`, then restart the existing web process. The next timer invocation uses the prior deterministic pipeline. Keep the additive tables, ledger and private artifacts: they contain recovery/accounting evidence.

```bash
cd "$JW_LIVE"
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml
p = Path('config/jobwatch.yaml')
d = yaml.safe_load(p.read_text())
d['pipeline']['agentic']['enabled'] = False
p.write_text(yaml.safe_dump(d, sort_keys=False))
PY
systemctl --user restart jobwatch-web.service
```

If the code/environment itself must be rolled back, stop the same services/timers as above, preserve the current config, and restore the recorded code plus prior environment. These commands preserve the failed environment and current private data rather than deleting them:

```bash
cp -a "$JW_LIVE/config" "$JW_BACKUP/failed-release-config"
git -C "$JW_LIVE" restore -- config/jobwatch.yaml
git -C "$JW_LIVE" checkout --detach "$(cat "$JW_BACKUP/previous-revision.txt")"
cp -a "$JW_BACKUP/config/." "$JW_LIVE/config/"
mv "$JW_LIVE/.venv" "$JW_BACKUP/failed-release-venv"
tar -C "$JW_LIVE" -xzf "$JW_BACKUP/previous-venv.tar.gz"
systemctl --user start jobwatch-web.service
systemctl --user start jobwatch-fast.timer jobwatch-slow.timer jobwatch-outcomes.timer jobwatch-digest.timer
```

Do **not** restore the old database over new application/outcome records. If actual data corruption requires recovery, retain a fresh copy of the current data and reconcile against the private backup/ledger as a separate reviewed repair.
