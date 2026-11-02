# Proposal

## Why

The screened pipeline embeds one person's category names and vocabulary in code. This defeats per-user configuration and prevents users from changing goals without code changes.

## What Changes

- Let users define goals and replace category IDs, labels, priority, matching phrases, actions and promotion policy.
- Research relevant websites to suggest per-user categories, synonyms and source-specific queries, with provenance, refresh, correction and rollback.
- Generate triage schema dynamically and apply category-independent policies throughout screening.
- Migrate current owner decisions into explicit per-user data without silently changing eligibility protections.
- Keep missing configuration neutral, and do not add collectors or infer personal exclusions.

## Capabilities

### New Capabilities
- `user-discovery-categories`: Goal-based research, configurable categories and their screening behavior.

### Modified Capabilities
None; this OpenSpec root has no existing main specifications.

## Impact

Screened ingest, title triage, tracks, gate, promotion and discovery query configuration. Parent owns integration and deployment. TASK-447 consumes a stable category interface; this change does not modify its brief.
