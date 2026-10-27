# Prescreen: early checks before any model

Prescreen skips postings that are clearly wrong for a person using cheap, deterministic rules, before the ad is fetched or
any model is called. It is data driven: one generic engine (`jobwatch/prescreen/engine.py`) reads rows from four tables. The
code holds no words, no field of work and no person. A skip is a reversible recommendation to spend nothing on the posting,
shown with a reason; it is never a verdict on fit and never a recommendation to apply.

## Tables (migration 18, in each person's own database)

| table | holds |
|---|---|
| `prescreen_terms` | the vocabulary: `category`, `term`, `match_type` (word, phrase, regex), `applies_to` (title, location, hours, ad_text), `polarity` (exclude, allow), `strength` (obvious, weak), `value`, `field_tag`, `scope` (shared, person), `source`, `enabled`, `seed_key` |
| `prescreen_rules` | what hits mean: `kind` (term_hit, level_not_approved, years_over, region_outside), `params_json`, `effect` (skip, flag), `enabled`, `scope`, `derived_from_profile_version`, `source` |
| `prescreen_overrides` | the person's exceptions: a term, a posting or an employer |
| `prescreen_decisions` | audit log: posting, stage (metadata, full), outcome (admit, skip, flag), rule, term, matched text, reason, parsed fields, `rules_hash` |

Categories: `seniority_level`, `off_target_occupation`, `location_outside`, `employment_type`, `work_rights`, `experience`.

## How a posting is checked

1. Parse: every enabled term is matched against the field it applies to. A match is a hit carrying the term's `value`
   (a level, a region code, an employment type, a requirement, a family, or the years in a regex group named `n`).
   An `allow` hit masks the text it matched (the whole clause for `ad_text`) from `exclude` hits of the same category, for
   example "regardless of citizenship" or "company has 25 years of experience".
2. Evaluate: rules decide what the hits mean for this person. Only an `obvious` hit under a `skip` rule skips. `weak` hits and
   `flag` rules only flag; the posting still goes to the agent.
3. Record: one `prescreen_decisions` row, plus the reason on the job (`pipeline_state.reason = 'prescreened'`).

The listing is checked before the ad is fetched (stage `metadata`); the full ad is checked again (stage `full`).

## Profile to rules

When a profile is confirmed or changes, `jobwatch/prescreen/sync.py` rewrites the rows with `source='profile'` (it never
reads the profile at decision time): approved levels become a `level_not_approved` rule (and a `years_over` cap), regions and
remote preference a `region_outside` rule, excluded families and work types `term_hit` rules, and work-rights status the blocked
requirements. Nothing is written for a fact the person did not confirm; with no level, no region and so on, that stage does not run.

## Re-admission and overrides

Skipped postings are archived with reason `prescreened`, never deleted. `Engine.rules_hash` covers terms, rules and overrides.
`discovery.reconsider` re-runs every skip whose last decision has another hash; a posting no longer skipped returns to the
queue (an ad-less metadata skip is read again by ingest). A profile change, an edited term or an override therefore re-admits.
`jobwatch prescreen override POSTING_ID` admits that posting and switches off the term that fired for this person only
(`--posting-only` keeps the term).

## Extending the bank

Rows are the interface. Add a term for your field with `jobwatch prescreen words add --category seniority_level --term "charge nurse" --match phrase --value senior --strength obvious`, then check it with `jobwatch prescreen test "Charge Nurse" --location "Sydney NSW"`. A bad regex is rejected. Use `weak` when unsure. `jobwatch prescreen stats` shows
hits per term so bad terms can be disabled (`words disable ID`).

Shipped seed rows live in `jobwatch/prescreen/seed/terms.json` and `rules.json`, loaded by `ensure_seeds` (called from `db.connect`)
keyed by `seed_key`, so an upgrade adds missing rows and never changes a row the person edited. To extend the shipped seed,
add entries with a unique `key` and bump `version`. `value` conventions: seniority `entry|junior|mid|senior|executive`; location a state code or country
code (`AU` = a country-level mention that counts as inside every Australian region); employment `full_time|part_time|casual|contract|temporary|intern`;
work rights `citizen_only|citizen_or_pr|clearance|no_sponsorship|unrestricted_work_rights`; off-target occupation a family from `KNOWN_FAMILIES`.
The gazetteer is Australian for now; other countries need their own rows and regions.
