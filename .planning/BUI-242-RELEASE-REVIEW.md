# BUI-242 release response — corrected evidence and remaining gate

## New evidence-window ruling and capture attempt

Product Lead technical ruling is delivered via [BUI-259](/BUI/issues/BUI-259), now done. Its bounded capture is complete below; independent Staff Reviewer verdict remains pending.

Product Lead technical direction is recorded in `.planning/BUI-259-CONTEXT.md` at commit `25bce44a7c7d18c9e0f3fa1f2e1d8cda61907b15`: distinguish historical sealed-snapshot evidence from current-live readiness; capture a pinned RO transaction and matching private online backup within 60 seconds, at most two attempts, never pause writers or weaken exact guards. No deployment/rehearsal repeat is needed.

A prior bounded attempt rejected counts 16/3; a later read returned 3/3. In this run, inventory showed timers active (fast next 15:00:21 AEDT, outcomes 15:03:37, slow 16:18:59, digest Monday 08:00), services inactive/dead, web active. Capture attempt 1 of at most 2 succeeded in a 60-second window (start `2026-10-09T03:51:17Z`, end `03:51:24Z`, elapsed 6.477s). Source-bound manifest and an online backup were created while the source RO transaction remained pinned; copy passed integrity and logical snapshot equality. Evidence directory `/home/phroggingphrog/brain/data/jobwatch/private-bui-215/bui242-capture-r8/` mode 0700. Evidence DB file SHA256 `3c7ed71a560a2a57fa9b6fb32ede51ddc0c33356d9aaa5a042a266a6078ba771`; source and copy logical snapshot both `e2b86904a34eaaa51723ca16bb7247a3e876f2f1b0cc1a5a27cf63e9b8a3def5`. Initial saved manifests omitted private `ids` and are retained as superseded serialization artifacts. Complete canonical manifests are now saved privately as `source-manifest-complete.json` and `copy-manifest-complete.json`, each with all seven inspect fields (including private IDs). Logical hashes are respectively `986c13fc597b45db00f90cfbd26ff735810684a4fabcbd0c84e56be0dd79dbdb` and `77320c2631059c9bd6c1388a7543941caf2a409cc02b66b444e66fed0d87ee75`; complete reinspection confirms all non-identity fields equal and source/copy identities differ. Provenance now binds their hashes and the evidence DB/source/copy identities privately. Aggregate 3/3, selected=3. Sidecar files show SQLite WAL mode remains active; reviewer must hash/verify the sealed evidence using coherent DB+WAL state or a separately validated checkpointed snapshot without changing source evidence. No live pause/mutation. Candidate `7bfbc3598b852475044b91b5b23b249decc1df8a`; protected hashes unchanged below.

## Scope and current state

This is a correction/preflight packet only. Candidate `7bfbc3598b852475044b91b5b23b249decc1df8a` is already integrated and service restart was performed under exact code-only approval `153c390a-e4a2-4903-ab6f-a829d2bb0d91`; those actions are historical and were not repeated here. No live apply/rollback, writer pause, model/sorter call, timer trigger, threshold/cap change, or live DB write was performed. Existing unrelated untracked files and worktrees (including form-fill) were preserved.

Protected hashes unchanged:

- `INTENT.md`: `0ce9ef863625b4f440e30a57c91148c8a2b1513073ca9021d8cadb6fc8488ec1`
- `GOAL_CONTRACT.md`: `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`

## Final handoff: sealed snapshot vs live readiness

The r8 capture bundle is the accepted candidate for independent historical snapshot review; this packet does not itself declare reviewer acceptance. Full canonical source/copy manifests are at the private `source-manifest-complete.json` and `copy-manifest-complete.json`; initial six-field serialized versions remain only as superseded artifacts. The complete copy manifest independently regenerates exactly from the sealed read-only evidence DB; all non-identity fields match source manifest, identities differ. Do not use any captured/source manifest for live authorization. Current live readiness is separately point-in-time only; subsequent DB drift is expected and invalidates readiness, not historical evidence.

Writer boundary per `.planning/BUI-259-CONTEXT.md`: listed timers are not a complete quiescence guarantee; timer pauses alone do not exclude known web `board_visit` writes or all writers. Any future separately approved writer-control proposal must enumerate all writers, specify timer/one-shot handling AND approved web-write exclusion/access-control, bounded downtime, abort/resume steps and exact restore set. No writer control is performed or approved here.

## Corrected effective count (round 2; historical superseded observations)

The prior paragraph incorrectly asserted zero because it looked for a top-level `hide_reason`; the canonical reader nests it at `r['ai']['hide_reason']`. Historical inspect at capture interval returned all/matches=3/3, selected=3. Stored `ad_reviews` hide/not_target remains 1049, a distinct status measure. Subsequent live observations have varied (including all=16/matches=3); do not treat old 3/3 results as current live acceptance. Retract every previous zero or stale-correction conclusion. Exact reproduction (prints aggregate only):

```python
import sqlite3
from scripts import legacy_too_senior as old
c=sqlite3.connect('file:/home/phroggingphrog/brain/data/jobwatch/jobwatch.db?mode=ro',uri=True)
c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
print(old.aggregates(c), len(old.selected(c)))
c.rollback(); c.close()
```

At capture time output was `{'all': 3, 'matches': 3} 3`; stored count query: `select count(*) from ad_reviews where verdict='hide' and hide_reason='not_target'` -> 1049. This snippet is reproducible but current counts may drift. Do not apply; any live change needs fresh inspection, independent review and separate approval.

The prior manifest `/home/phroggingphrog/brain/data/jobwatch/private-bui-215/bui242-fresh-manifest.json` is superseded as stale and must not be used: its snapshot was `e3411c9be2e53d267a8fbfedec089ef6674064c8c28c7b2d005dae02c26dd78f`, while current live snapshot is `bd4d888fac2d43de46dd2ebc4a8bbce5be0f0d67e845487212cfc0b7e870d72b`.

Historical round-3 live manifest at `/home/phroggingphrog/brain/data/jobwatch/private-bui-215/bui242-fresh-manifest-round3.json` is superseded for readiness: snapshot drift was independently observed. Its former matching counts do not imply current equality; never use it for live action. The sealed r8 snapshot supersedes it as historical evidence only, not live authorization.

## Safe board checks (executed)

Used runbook-prescribed loopback HX partial requests, no job parameter, without retaining response HTML:
- `GET /?scope=all`, headers `HX-Request: true`, `HX-Target: results` -> HTTP 200, visible results count 146 (not the unsorted aggregate).
- `GET /?scope=matches`, same headers -> HTTP 200, visible results count 146 (same caveat).

At the recorded check time canonical SQLite RO aggregate returned unsorted all=3/matches=3. Full-page GET is unsafe because `board_visit` may write; do not infer sidebar unsorted count from the HX result-page count. This is historical, not current-live readiness.

## Fresh private rehearsal and writer inventory

Created a fresh RO online copy in `/home/phroggingphrog/brain/data/jobwatch/private-bui-215/bui242-rehearsal/` (directory 0700), not using BUI-227 manifest. New identity-bound manifest count=3/3; file SHA256 `133550330f7110ee3cd527b12065f8cddcf8d2daedbedf0c9b7b22d28eaa1945`; logical manifest SHA256 `a1fd2366e2e1fb4571b2ec10665e97730f9726facfd088037a621954600fc11d`. Guarded private-copy apply then rollback produced preimage `bd4d888fac2d43de46dd2ebc4a8bbce5be0f0d67e845487212cfc0b7e870d72b`, postimage `66513340d197b23c829afa7ee65e3f3517553f87d2474587188fb7c419171655`, restored hash equal to preimage; aggregates 3/3 -> 0/0 -> 3/3. Manifest, backup, copy mode 0600. Rehearsal used guarded library methods strictly against private copy; live CLI correctly requires real approval, and no live mutation was done.

Historical systemd inventory found `jobwatch-fast.timer`, `jobwatch-slow.timer`, `jobwatch-outcomes.timer`, `jobwatch-digest.timer`, their services, and active web service. This inventory is not proof of writer exclusion. No unit paused. Per BUI-259, timer pauses alone do not suppress known web `board_visit` writes or all possible writers. Any future separately approved writer-control proposal must enumerate all writers, include timer/one-shot handling plus approved web-write exclusion/access control, downtime bound, abort/resume sequence, and exact restore set. This issue authorizes none.

## Verification performed

Release base: `0fbb8487b28ae6a097568cc1ab81b6adf507c574`; exact reviewed candidate `7bfbc3598b852475044b91b5b23b249decc1df8a` on `phase/bui-215-live-procedure`. This response workspace is technical-ruling commit `25bce44a7c7d18c9e0f3fa1f2e1d8cda61907b15`, branch `phase/bui-259-evidence-window`; do not confuse the two.

- `git rev-parse HEAD; git branch --show-current` -> exit 0; `25bce44a7c7d18c9e0f3fa1f2e1d8cda61907b15`, `phase/bui-259-evidence-window`.
- `git merge-base --is-ancestor 0fbb8487b28ae6a097568cc1ab81b6adf507c574 7bfbc3598b852475044b91b5b23b249decc1df8a` -> exit 0.
- `git -C /home/phroggingphrog/workspace/jobwatch-bui-215 status --short` -> exit 0, clean; exact candidate worktree confirmed.
- `git -C /home/phroggingphrog/workspace/jobwatch-bui-215 diff --check 0fbb8487b28ae6a097568cc1ab81b6adf507c574 7bfbc3598b852475044b91b5b23b249decc1df8a` -> exit 0, no output.
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/web/test_legacy_kinds.py tests/test_live_legacy_procedure.py` -> exit 0, `41 passed, 1 warning` (Starlette/httpx deprecation).
- Read-only `old.aggregates` / `old.selected` canonical predicate -> exit 0, effective all=3, matches=3, selected=3; stored hide/not_target=1049.
- r8 complete manifests added without recapturing or modifying DB: independent sealed-copy inspect full equality true, source/copy nonidentity fields equal, identities differ, counts 3/3, integrity ok. Full logical hashes are documented above; complete artifacts are mode 0600. Initial incomplete manifests are superseded.
- HX results-only GET both scopes -> exit 0 each; HTTP 200, visible count 146 (not sidebar unsorted aggregate).
- Fresh private-copy guarded roundtrip -> exit 0; 3/3 -> 0/0 -> 3/3, exact preimage restoration.
- `systemctl --user is-active jobwatch-web.service` -> exit 0, `active`.
- `sha256sum INTENT.md GOAL_CONTRACT.md` -> exit 0, `0ce9ef863625b4f440e30a57c91148c8a2b1513073ca9021d8cadb6fc8488ec1` / `808f0375b28840fe21598128664f2338a3dbb235ef09410c1281260fde036487`.

## Remaining and handoff

Snapshot evidence: capture r8 is sealed historical evidence for `2026-10-09T03:51:17Z`–`03:51:24Z`, with canonical complete manifests and matched source/copy logical snapshot; independent Staff Reviewer verdict is pending. Live readiness: not asserted beyond the point-in-time capture; later drift must be separately inspected and never changes historical evidence validity. No captured manifest authorizes live action. Parent [BUI-96] owns actual zero acceptance and any future separate live-data approval. No action here paused writers or wrote the live DB. No IDs/content are public.
