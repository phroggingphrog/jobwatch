# Configuration and collection

[Project overview](../README.md) · [Current intent](../INTENT.md)

Reference material moved from README; commands describe available source interfaces,
not proof of current service activation or end-to-end acceptance.

## Config files (`config/`)

| File | What it holds |
|---|---|
| `jobwatch.yaml` | DB path, timezone, HTTP timeout/delay, `alerts.max_age_hours`, retention, tier membership |
| `rules.yaml` | Arms (keywords per ANZSCO arm, per-arm excludes), location rules, seniority/off-target excludes, flag patterns |
| `searches.yaml` | Seek keywords (`where`, `date_range`, pages, rotation) and JobSpy searches (sites, `hours_old`, `results_wanted`) |
| `feeds.yaml` | Generic RSS/Atom job feeds, and Reddit feeds, hiring/chatter keywords, digest themes |
| `employers.yaml` | Employer registry, maintained separately. If it is missing, `employers.example.yaml` is used |

### `employers.yaml` schema

```yaml
employers:
  - name: Telstra              # required; also used for "VIC employer" matching
    sector: telecommunications # free text
    arms: [call_centre, retail_sales]   # rules.yaml arm ids it is likely to hire for
    state: VIC                 # VIC lets unknown-location postings from it match
    provider: workday          # greenhouse | lever | ashby | workable | smartrecruiters |
                               # workday | pageup | employmenthero | scouttalent | jsonld |
                               # oracle-hcm | successfactors | phenom | atlassian | careers_vic
    tenant: telstra            # board slug / PageUp client no. / Workday tenant / Scout subdomain
    site: Telstra_Careers      # workday only
    host: telstra.wd3.myworkdayjobs.com   # workday only
    search_text: ""            # workday only, optional (string or list)
    applied_facets: {}         # workday only, optional CXS facet filter
    feed_url: https://careers.pageuppeople.com/527/cw/en/rss   # pageup
    careers_url: https://example.vic.gov.au/careers            # jsonld (string or list)
    link_pattern: '/jobs/\d+'  # jsonld, optional regex for job-detail links
    allowed_hosts: []          # jsonld, optional extra hosts for detail links
    follow_links: true         # jsonld, optional (false = read the listing page only)
    url_pattern: '…/job/\d+/[a-z0-9-]+'  # jsonld, optional: pair url-less JobPostings with page links by title slug
    host: …  site: CX_1        # oracle-hcm (api_url optional; offset paging is added by the collector)
    feed_url: https://…/googlefeed.xml   # successfactors (slow tier)
    careers_url: https://…/au/en/search-results   # phenom
    detail_cap: 10             # optional; workday/smartrecruiters default 10, jsonld max 30
    region: eu                 # lever only, when the board lives on api.eu.lever.co
    enabled: true
    notes: how it was verified
    verified_at: 2026-10-06
```

## Collectors

| Collector | Tier | Source |
|---|---|---|
| `ats_greenhouse` | fast | `boards-api.greenhouse.io/v1/boards/{tenant}/jobs?content=true` |
| `ats_lever` | fast | `api.lever.co/v0/postings/{tenant}?mode=json` |
| `ats_ashby` | fast | `api.ashbyhq.com/posting-api/job-board/{tenant}` |
| `ats_workable` | fast | `apply.workable.com/api/v1/widget/accounts/{tenant}?details=true` |
| `ats_smartrecruiters` | fast | `api.smartrecruiters.com/v1/companies/{tenant}/postings?country=au` (+ detail for target titles) |
| `ats_workday` | fast | `POST {host}/wday/cxs/{tenant}/{site}/jobs` (+ detail for target titles whose location is unclear) |
| `ats_pageup` | fast | PageUp RSS (`job:` namespace) |
| `ats_employmenthero` | fast | `services.employmenthero.com/ats/api/v1/career_page/organisations/{tenant}/jobs` |
| `ats_scouttalent` | fast | `{tenant}.applynow.net.au/` index (`div.jobblock` data attributes), robots.txt respected |
| `rss` | fast | `feeds.yaml` feeds (generic, or `format: pageup`) |
| `reddit` | fast | `reddit.com/r/<sub>/new/.rss` and `/search.rss`, descriptive UA, rate-limit headers honoured |
| `jobspy_src` | slow | python-jobspy: LinkedIn, Indeed (Australia), Google; "Melbourne, VIC" |
| `seek` | slow | `seek.com.au/api/jobsearch/v5/search` (AU-Main, All Melbourne VIC, at most 2 pages) |
| `ats_oracle` | fast | Oracle Recruiting Cloud `recruitingCEJobRequisitions` finder (public, newest first); pages until a seen id, 2 pages fast / 4 slow |
| `careers_vic` | fast + slow | careers.vic.gov.au `/jobs?page=N` HTML (15/page, newest first, robots.txt respected); pages 1-2 on fast runs, up to 10 on slow, stops at a seen id; VPS grade -> `classification` |
| `ats_successfactors` | slow | SuccessFactors `googlefeed.xml` RSS (1-3 MB each); location from the title suffix or `g:location`; conditional GET when the server sends ETag/Last-Modified |
| `ats_phenom` | slow | Phenom search page (`phApp.ddo` / `eagerLoadRefineSearch`) + the page's own `/widgets` paging (100/page, max 10); robots.txt respected |
| `ats_atlassian` | slow | `atlassian.com/endpoint/careers/listings` JSON (AU locations only) |
| `jsonld_pages` | slow | employer careers pages: schema.org `JobPosting` JSON-LD (incl. capitalised `Title`), robots.txt respected |

Politeness rules: requests time out after 20 s or less, and there is a 1.5 s gap (allowed range
1 to 2 s) between requests to the same host (at least 3 s for Reddit). The User-Agent is a normal
browser string; Reddit gets a descriptive one. There are no proxies and no stealth. A 403, 429 or
5xx marks the host as backed off for the rest of the run and is recorded as an error. Every
collector gates on Australia (a structured country of AU, or Australian place names); the filter
decides about Melbourne, Victoria and remote.

## Matching, flags, alerts

- **Match:** the title matches an arm keyword, the location is Melbourne/Victoria or remote in
  Australia (or the location is unknown and the employer has `state: VIC`), there is no
  seniority or off-target word, and the ad does not ask for 5 or more years. Each match stores
  its arm, all matching arms and the rules that fired (`matches.rules_json`).
- **Flags (warnings, not filters):** `work_rights_required`, `full_time_only`,
  `experience_years>=2`, `entry_level`, plus source tags such as `via_linkedin` or `reddit`.
- **Alerts:** there is no push. A fresh match gets an `alerts` row with status `board` (visible as NEW on
  the web board). Old or seed postings are `stale`. `--dry-run` leaves them `queued`. The board decides NEW itself (unviewed), not from this table.
- **Classification:** collectors that know a pay grade (Careers.Vic "Grade") set `classification`.
  `seniority.exclude_classification` excludes VPS 5+/SES/executive grades;
  `flags.entry_classification` flags VPS 1-3 as `entry_level`. VPS 4 matches with no flag.
- **Arm names:** `rules.yaml` `registry_arm_map` maps the registry's brief arm names (admin,
  retail, ...) to rule arm ids (`Rules.rule_arms_for`). Reporting only; matching is by title.
- **No floods:** a provider-dated posting older than 72 h is stored as `stale` and not alerted.
  The first time an employer or feed is read, observed-date postings are stored without alerts
  (seeding).
- **Health:** consecutive failures per collector are counted in `source_health` and shown by
  `jobwatch health` and the Sources page. Nothing is pushed.
