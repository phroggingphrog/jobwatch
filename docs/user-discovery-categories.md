# User discovery categories

Category names and phrases belong to each person's configuration. Runtime code does not inject program words or reserve career category names.

```yaml
pipeline:
  screened:
    category_snapshot:
      categories:
        - id: office-career
          label: Admin and clerical career roles
          priority: 0
          phrases: [administrative, clerical]
          action: admit
          promote: true
          hours: standard
    unlisted_action: admit
  discovery_research:
    enabled: true
    sources:
      - source: seek
        url: https://careers.example.com/jobs
        category_id: office-career
```

This is an example, not a default taxonomy. Each user can add, rename, reorder or remove categories. `action` controls admit, side or archive. `hours` grants an explicit hours-only exception; a category name never grants it. Missing categories remain neutral, including stale unlisted archive settings.

## Automatic research

Normal collection derives research from the current confirmed discovery scope. It refreshes when goals or source configuration change. Without source URLs, it searches the public web for job titles using the goals and existing enabled source adapters. It does not require a manually maintained keyword list. Disable with `pipeline.discovery_research.enabled: false`.

Configured source pages let a person choose authoritative websites. Optional `goal_terms` connect their goal to website terminology. Research reads bounded headings and link text; it cannot execute page instructions, create a personal restriction, enable a collector, or create an hours exemption. Optional `category_id` adds positive suggestions only to an existing admitting category.

Each suggestion records the source ID, URL, retrieval time and goal version. `pipeline.discovery_vocabulary` provides `status`, `queries`, `override` and `rollback`. Corrections remain in effect across research refreshes. A failed refresh records its error and retains the previous version. Discovery queries append to the confirmed scope instead of replacing admin, clerical or other approved goals.

Dry runs project existing scope without research requests or vocabulary writes. Public research rejects credentials, local addresses and redirects; the connection pins a validated public IP and checks TLS against the source hostname. Requests have time and response-size bounds. A failed public source does not authorize exclusion.

## Migration and rollback

Do not load an old configuration into the new branch without migration. No migration runs automatically against production.

1. Pause pipeline writers through the deployment procedure. This document does not authorize a restart or deployment.
2. Back up the configuration once in the designated backup directory. Retain the original configuration and database backup.
3. Call `category_migration.migrate_legacy` with the old phrase lists, old program phrases, explicit legacy policy, program category and ID mapping. The caller supplies all legacy vocabulary; runtime code has no hidden defaults.
4. Validate the returned category snapshot. Call `migrate_persisted` with that snapshot and its hash. It uses a savepoint and journals changed tracks and title-triage snapshot hashes. Unknown IDs or malformed records abort without a partial migration.
5. Activate the matching configuration only while writers remain paused. Keep the journal migration ID and previous configuration. Do not resume writers before config and stored IDs agree.
6. For rollback, keep writers paused, call `rollback_persisted`, then restore the previous configuration. Rollback refuses records changed since migration rather than overwriting newer work.

Database and YAML activation are not one cross-file transaction. The paused-writer boundary is mandatory. No migration claims an atomic configuration-file plus database update.

## Verification

Run category, research, goal-policy and migration regression tests, then the full available suite. Check the owner's actual URL and runtime identity before any future deployment claim. This feature branch does not deploy itself.
