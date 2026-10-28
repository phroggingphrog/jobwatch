# Councils sweep (2026-10-06, "and city councils")

Scope: 31 metro Melbourne councils + Greater Geelong, Ballarat, Greater Bendigo, Latrobe, Surf Coast, Mitchell, Moorabool,
Baw Baw, Golden Plains (40; Macedon Ranges was already enabled). Registry entries: `config/employers.councils.pending.yaml`
(35 entries: 13 REPLACE disabled stubs of the same name in employers.yaml, 22 are new; 17 enabled). Yarra, Knox, Casey,
Bayside, Monash (PageUp) and Macedon Ranges (Scout Talent) are unchanged and not repeated. `employers.yaml` was not touched.

## Result by council (live counts 2026-10-06, kept by the collector)
| council | platform | endpoint | collector | live | enabled |
|---|---|---|---|---|---|
| Banyule | Pulse | JSON `/WebServices/RCM/Jobs/Jobs` | ats_pulse (new) | 9 | yes |
| Brimbank | Pulse | same | ats_pulse | 4 | yes |
| Manningham | Pulse | same | ats_pulse | 2 | yes |
| Maribyrnong | RecruitmentHub | server HTML `/Vacancies/` | ats_recruitmenthub (new) | 7 | yes |
| Nillumbik | RecruitmentHub | HTML `/Current-vacancies/` | ats_recruitmenthub | 5 | yes |
| Moorabool | RecruitmentHub | HTML | ats_recruitmenthub | site down ("not available") | no, flip when up |
| Kingston | careers.*/jobs/search cards | server HTML | ats_jobs_search (new) | 13 | yes |
| Glen Eira | same | same | ats_jobs_search | 11 | yes |
| Mitchell | same | same | ats_jobs_search | 8 | yes |
| Stonnington | ELMO Talent | server HTML `/careers/cosjobs/jobs` | ats_elmo (new) | 6 | yes |
| Surf Coast | ELMO Talent | server HTML | ats_elmo | 2 | yes |
| Greater Bendigo | TechOne (council page JSON) | anonymous RaaS JSON | ats_techone (new) | 4 | yes |
| Baw Baw | Scout Talent (shared host) | tenant index HTML | ats_scouttalent (+`ref_prefix`) | 7 | yes |
| Melton | Scout Talent (`testmelton123`) | tenant index HTML | ats_scouttalent | 0 | yes (empty at probe) |
| Frankston | PageUp 1065 | RSS | ats_pageup | 12 | yes |
| Greater Geelong | PageUp 887 | RSS | ats_pageup | 10 | yes |
| Hume | SmartRecruiters HumeCityCouncil | JSON | ats_smartrecruiters | 33 | yes |
| Whitehorse | Oracle HCM CX_1001 | REST | ats_oracle | 9 | yes |
| Cardinia | Adlogic | RSS `/adlogic-jobs/rss` (6 items, with dates) | none (see below) | 6 | no |
| Boroondara | council page cards -> legacy SF career10 | HTML | none | 14 links | no |
| Merri-bek | council page `div.jobListing` -> applynow.net.au | HTML | none | ~5 | no |
| Greater Dandenong | custom Drupal, infinite scroll | HTML | none | 3 of 8 in first HTML | no |
| Darebin, Maroondah | Nga.Net | HTML | none | - | no: robots `Disallow: /` |
| Whittlesea, Hobsons Bay | BigRedSky | HTML | none | - | no: robots `Disallow: /` |
| Wyndham, Yarra Ranges, Mornington Peninsula | TechnologyOne CiAnywhere (t1cloud) | JS portal | none | - | no: robots disallows all but LogOn |
| Melbourne, Latrobe | Mercury eRecruit | HTML | none | - | no: host times out from this server, robots included |
| Ballarat | ColdFusion `careers.ballarat.vic.gov.au` | HTML | none | - | no: robots disallows the listing path |
| Port Phillip | not identified | - | none | - | no: 429 on first request, stopped |
| Golden Plains | Aurion | - | none | - | no: 403 on first request, stopped |
| Moonee Valley | unknown (behind Incapsula challenge) | - | none | - | no: bot challenge page, no bypass tried |

Platform groups: Pulse 3, RecruitmentHub 3, jobs/search 3, ELMO 2, TechOne portal 3 (+1 JSON), Nga.Net 2, BigRedSky 2,
Mercury 2, Scout Talent 3 (+Macedon), PageUp 2 (+5), Oracle/SmartRecruiters 1 each.

## What changed in jobwatch (undo: delete the new files; restore the `.pre-councils` copies from the scratchpad)
- New collectors in `jobwatch/collectors/`: `ats_pulse`, `ats_recruitmenthub`, `ats_jobs_search`, `ats_elmo`, `ats_techone`
  (provider names: `pulse`, `recruitmenthub`, `jobs-search`, `elmo`, `techone`). All fast tier.
- Edited: `collectors/__init__.py` (COLLECTORS), `config.py` (DEFAULT_SETTINGS tiers.fast), `config/jobwatch.yaml`
  (tiers.fast; this file overrides config.py, so it needs the same names), `collectors/ats_scouttalent.py` (optional
  `ref_prefix` for tenants whose job URLs sit on the shared host applynow.net.au; behaviour unchanged without it).
- Backups: `<scratchpad>/{__init__.py,ats_scouttalent.py,config.py,jobwatch.yaml}.pre-councils`.
- Tests: `tests/collectors_councils/test_councils_collectors.py` + `tests/fixtures/councils_*` (offline). No second conftest.
- Nothing runs in the background that did not already. The new collectors start working as soon as the pending entries
  are merged into employers.yaml (the first read of each council only seeds the DB, so no alert flood).

## Behaviour notes
- ELMO's robots.txt (`Allow: /careers/*/jobs`, `Disallow: /careers/*`) is correct under the longest-match rule but Python's
  `urllib.robotparser` ignores `*` wildcards and would block the allowed page. `ats_elmo` therefore reads robots.txt itself
  and applies the standard wildcard/longest-match rule; it only fetches the list page, never job detail pages.
  Fix for everyone instead: make `Fetcher.allowed` wildcard-aware (http.py was out of scope).
- Pulse, TechOne JSON: the data call is the same anonymous call the council's public page makes. Pulse hosts serve no
  robots.txt (404); the ION API host answers 400 to /robots.txt (data endpoint, not a page).
- `ats_jobs_search` records an error if the footer says N entries but fewer cards parsed (paged list not seen yet at 8-13 jobs).
- No posted dates for RecruitmentHub, jobs/search and ELMO (ELMO shows a closing date): observed-dated, first read seeds.
- Stale/changed endpoints found: Bendigo applynow tenant `city-of-bendigo` shows "no vacancies" (council moved to TechOne);
  Cardinia applynow tenant is a how-to-apply page (council moved to Adlogic); Melton's tenant is literally
  `testmelton123` (the one Melton's own page iframes).

## Request log (probing)
Discovery used web search (no council requests), then 1-4 fetches per council (robots.txt counted). Councils that were also
verified live with a collector (plus one `jobwatch run --dry-run` against a temp DB for Pulse and ELMO) took up to about 7
requests each in total. Stops: Port Phillip 429 (1 request), Golden Plains 403 (1), Mercury hosts time out (robots + 1
curl each), Nga.Net / BigRedSky / TechOne / Ballarat stopped at robots.txt. No proxies, no browser impersonation, normal
Chrome-on-Linux UA, 1.5 s+ between requests to a host. Pipeline test runs used a temp DB and `--dry-run` (no Matrix).

## Optional follow-ups (not done, listed for the owner)
1. Cardinia via the existing `rss` collector: add to `config/feeds.yaml` (feeds.yaml was out of my edit list):
   ```yaml
   - name: Cardinia Shire Council (Adlogic)
     url: https://careers.cardinia.vic.gov.au/adlogic-jobs/rss
     company: Cardinia Shire Council
     default_location: Cardinia, VIC
     au: true
     enabled: true
   ```
   Tested offline against the live feed: 6 postings with provider dates. Then set the Cardinia entry's note accordingly.
2. Merri-bek, Boroondara, Greater Dandenong: three single-council page parsers (~30 lines each) would add ~25 jobs.
3. Wildcard-aware `Fetcher.allowed` (see above) would let `jsonld`/other collectors read ELMO-style robots files.
