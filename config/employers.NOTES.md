# employers.yaml: notes (BUI-73 wave 1, agent B, 2026-10-06)

## Totals
- **148 employers researched. 84 enabled, 64 disabled.**
- Enabled entries showed **about 2,450 VIC postings** on 2026-10-06 (~9,500 postings in total).
- 62 enabled entries already have a jobwatch collector: Workday, PageUp, SmartRecruiters, Greenhouse, Lever, Ashby, Workable, Scout Talent and JSON-LD.
- 22 enabled entries need wave-2 work: 16 SuccessFactors feeds and 6 Oracle HCM sites. See "Wave-2 integration".

## Method
1. **Seed list.** Started from the archived `portals.yml`, `PHR-93-SOURCE-CONTRACTS.md`, `au_ats.py` and `career_sites.py`, plus the archived crawler `data/boards.csv`. These were read only.
2. **Find the ATS.** Fetched each employer's own careers page once, after checking robots.txt, and pulled out the ATS hosts it links to. Where the page was JS-only or blocked, used web search (e.g. `site:careers.pageuppeople.com …`).
3. **Verify.** Made one request per endpoint, at least 1.6 s apart, with a normal browser UA, no proxy and no stealth. Counted total, AU and VIC postings:
   - Workday: the location facets in the first CXS response.
   - PageUp: `job:location`.
   - SuccessFactors: the "(City, STATE, AU)" suffix on each title.
   - Others: the API location fields.

   PageUp and SuccessFactors feeds were fetched a second time, about 30 min later, with a better location parser. Nothing else was re-fetched.
4. **Count adjustments.**
   - `vic_only`: for employers that only hire in VIC (councils, some hospitals, TAFE), AU and VIC were set to the total. Their feeds use site names, not states.
   - `au_all`: for AU-only national employers, AU was set to the total.
   - SmartRecruiters and Oracle counts come from the first 100 or 25 postings only. Each entry's notes say which applies.
5. Nothing was guessed. Every `enabled: true` entry returned job data. Every disabled entry says why in `notes`.

## By provider
| provider | entries | enabled | VIC postings seen (enabled) |
|---|---|---|---|
| workday | 20 | 20 | 781 |
| successfactors | 17 | 16 | 744 |
| pageup | 21 | 21 | 520 |
| smartrecruiters | 9 | 9 | 209 |
| ashby | 2 | 2 | 65 |
| greenhouse | 4 | 4 | 61 |
| jsonld | 1 | 1 | 35 |
| oracle-hcm | 6 | 6 | 19 (first 25 only) |
| workable | 1 | 1 | 6 |
| lever | 3 | 3 | 5 |
| scouttalent | 1 | 1 | 3 |
| other / rss | 63 | 0 | n/a |

## By sector (entries / enabled)
accounting 14/6 · finance 8/5 · insurance 7/5 · super 5/1 · telco 4/3 · utility 7/5 · university 8/6 · tafe 3/1 · council 19/6 · health 18/12 · retail 14/10 · hospitality 6/4 · tech 22/14 · vicgov 2/1 · recruiter 6/0 · other 5/5

## Wave-2 integration (for whoever wires this in)
1. **SuccessFactors (16 enabled).** `feed_url` is RSS 2.0 (`/googlefeed.xml`) and holds every live job, at about 20 KB per job. Feed it through the RSS collector with `poll_tier: slow`. Parse the location from the title suffix. ANZ and Kmart feeds include NZ jobs. A light latest-20 variant, `/services/rss/job/?locale=en_GB`, works for Eastern Health. The same URL with `keywords=()` errors on some sites.
2. **Oracle HCM (6 enabled: Westpac, Suncorp, AustralianSuper, TPG ×2, VU).** Public REST, no auth: `GET {api_url}`. Read `items[0].requisitionList[]` (Title, PrimaryLocation, PostedDate, Id) and `TotalJobsCount`. The job URL is `https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}`. No collector exists yet.
3. **jsonld `tafe_vic`.** The JobPosting objects use a capital **`Title`** key. The collector reads `title`/`name`, so add `Title`. Set `follow_links: false`; the listing page already holds every posting.
4. **Workday Hungry Jack's** has about 990 jobs. The collector's default `max_pages: 3` only sees the first 60 in Workday's default order. That is fine for new-job alerts if the order is newest first; check in wave 2.
5. **Arm ids.** The registry uses the brief's arm names. Map them to the `rules.yaml` ids like this:
   - clerical_accounting → accounting_clerk, bookkeeper, payroll_clerk
   - admin → general_clerk, admin_other, information_officer
   - reception → receptionist
   - data_entry → data_entry
   - customer_service → call_centre, information_officer
   - graduate_accounting → graduate_accountant
   - graduate_audit → graduate_auditor
   - data_analyst → data_analyst
   - business_analyst → management_analyst, ict_business_analyst
   - retail → retail_sales, checkout
   - hospitality → barista_bar, cafe_worker, waiter, fast_food

   The arms are informational only: the filters match on job titles, not on employer arms.
6. Each entry has a `state` field (HQ state). The filter uses it for unknown-location matching.

## Wave-2 status (2026-10-06)
1. SuccessFactors: done. `ats_successfactors` (slow tier) reads every enabled `provider: successfactors` feed with
   `rss.parse_successfactors` (title suffix, else `g:location`; non-AU rows dropped). No ETag/Last-Modified seen,
   conditional GET is used if a server starts sending them.
2. Oracle HCM: done. `ats_oracle` (fast tier), all 6 entries, newest first, stops at a seen requisition.
3. TAFE portal: done. Capital `Title` read; `follow_links: false` honoured; JobPostings have `url: null`, so
   `url_pattern` pairs each with its share link by title slug.
4. Workday order: newest first confirmed on Hungry Jack's; default 3 pages kept.
5. Arm names: `registry_arm_map` in `rules.yaml` (reporting only).
6. Careers.Vic: done (`careers_vic`, provider careers_vic, enabled). Coles and IAG: `ats_phenom`, enabled.
   PwC (0 jobs on its Phenom site) and McDonald's (now McHire, not Phenom) stay disabled. Atlassian: `ats_atlassian`.

## Disabled: verified endpoint, no collector (quick wins)
| employer | what exists | value |
|---|---|---|
| **Careers.Vic (Victorian Government)** | Server-rendered HTML `/jobs?keywords=&page=N`, newest first, 15 per page, about **1,584 VIC jobs**. No RSS (`/rss.xml` is empty) and no JSON-LD. robots.txt allows `/jobs` and `/job/`. | **Highest.** One small HTML collector unlocks the whole VPS. |
| Coles (also needed for IAG, PwC, McDonald's) | Phenom search-results page with embedded JSON state (`totalHits` 625 for Coles) | High: VIC store casuals. One Phenom collector covers four employers. |
| Atlassian | `atlassian.com/endpoint/careers/listings` JSON (350 jobs, about 11 AU) | Low for entry level |
| Woolworths | Avature RSS: 20 items, title only, not newest first | Needs an Avature collector |

## High-value employers with NO pollable endpoint (Seek/LinkedIn/Indeed only)
- **Banks and super:** NAB, ME Bank/BOQ, Judo, Up, Aware, UniSuper, Hostplus, Cbus, EY.
  - NAB: the Eightfold API is disallowed by robots.txt and returned 403. Its Workday site lists offshore jobs only.
  - EY: the only feed is global, with about 8k jobs. See "Accounting sweep" for the HTML search page.
- **Insurance and utilities:** Allianz (403), Bupa AU (the Avature feed is empty; `bupa/EXT_CAREER` is the UK site), Optus, EnergyAustralia (PageUp client 611 RSS returns 404), Yarra Valley Water (Cornerstone).
- **Accounting:** William Buck (Cornerstone), H&R Block, Nexia (JobAdder HTML), Bentleys (only a QLD board exists), EY (HTML search only). Pitcher, Findex and PwC were solved on 2026-10-06, see "Accounting sweep" below.
- **Councils:** City of Melbourne, Merri-bek, Darebin, Maroondah, Boroondara, Glen Eira, Wyndham, Brimbank, Manningham, Maribyrnong, Whittlesea, Port Phillip, Stonnington. Platforms seen: Mercury, Nga.Net, Pulse, BigRedSky, TechOne, RecruitmentHub, and legacy SuccessFactors pages.
  - Merri-bek lists applynow links on its own page; a jsonld entry with `allowed_hosts: [applynow.net.au]` might work, but is untested.
- **Health:** Alfred Health (LiveHire, Cloudflare 403), Northern Health (legacy SuccessFactors), Peter Mac (403), Ambulance Victoria (Springboard), Barwon Health.
- **Education:** Swinburne (Nga.Net), ACU (403), Melbourne Polytechnic (robots.txt disallows). Holmesglen, Box Hill and Kangan have no own feed; they are partly covered by the TAFE portal.
- **Retail and hospitality:** McDonald's (Phenom), Officeworks, David Jones, Grill'd. (Australian Venue Co was not checked: its domain did not resolve.)
- **Tech:** MYOB, carsales, SEEK corporate, Linktree, Employment Hero, Tyro.
- **Recruiters:** Hays, Robert Half, Randstad, Adecco, Hudson, Talent International. None publishes a public feed; they are covered by Seek/Indeed.

## Moved or gone (do not re-add the old endpoints)
- University of Melbourne: PageUp 422 now returns 404. It is now on Workday (`unimelb`/`UoM_External_Career`). The `UoM_Direct_Appointment_Confidential_Careers` site is invite-only; do not poll it.
- Suncorp: PageUp 346 now returns 404. It is now on Oracle `CX_1`.

## ToS / robots notes
- Every enabled endpoint is a public, unauthenticated job API or feed that the employer's own careers site serves to anonymous visitors. robots.txt allowed every HTML page that was fetched.
- **Blocked by robots.txt, so not used:** `nab.eightfold.ai/api/...`, `jobs.mp.edu.au`, `whittlesea.bigredsky.com`, `linktr.ee` careers.
- One request went to the NAB Eightfold API before the robots result was checked. It returned 403 and was not repeated.
- **Cloudflare/403 blocks:** LiveHire, Pitcher, Judo, Allianz, ACU, Peter Mac and several `.edu.au`/council sites block non-browser clients. Per PHR-93, do not retry 403/429 in a loop. Port Phillip returned 429.
- **Load:** SuccessFactors `googlefeed.xml` feeds are 1–3 MB each, so poll them on the slow tier. Do not poll the EY global feed.

## Scratch artifacts (not part of jobwatch)
The verification log (`results.jsonl`), raw responses and the probe/generator scripts are in this session's scratchpad (`…/scratchpad/jw/`). They are not needed to run jobwatch.

## Accounting sweep (owner request 2026-10-06: "all big four and mid tier firms")
Method as above: one polite request per endpoint, normal browser UA, no proxy; robots.txt respected.
Counts below are live per-employer counts seen on 2026-10-06 (total / AU kept / VIC).

Big Four
- **Deloitte**: SuccessFactors googlefeed, 245 / 245 / 51 (ok, slow tier).
- **KPMG**: SmartRecruiters KPMGAustralia1, 114 / 114 / 36 (ok).
- **PwC**: the Phenom root site `/au/en` holds 0 jobs (the old dead end). The jobs are under `/experiencedhires/au/en/search-results` (116 jobs, all AU). Enabled but PARTIAL: `ats_phenom` reads only the first 10, because the `/widgets` POST returns 0 rows for this site variant. Fix needed in `ats_phenom.py`: page the HTML (`search-results?from=N&s=1`, 10 per page) when the widgets call returns nothing. The global Workday tenant `pwc.wd3 / Global_Experienced_Careers` (3,892 jobs) has no AU locations.
- **EY**: disabled. `/services/rss` is disallowed by robots.txt and the global googlefeed is about 8k jobs. The HTML search `https://careers.ey.com/ey/search/?q=&locationsearch=Melbourne&optionsFacetsDD_country=AU` lists 129 Melbourne jobs, 25 per page, as `a.jobTitle-link` anchors (`/ey/job/...`), with no JSON-LD. Needs a small HTML collector.

Mid-tier
- **BDO** (two Workday sites), **RSM**, **Grant Thornton**: verified, unchanged. The Workday collector reads the newest 60 rows per site and drops ambiguous "N Locations" rows, so its AU/VIC counts are lower than the registry's facet counts.
- **Pitcher Partners**: now enabled. It is on the shared Workday tenant `prosper.wd105` (site `Pitcher-Partners-Melbourne`), 7 jobs. pitcher.com.au is still 403 and was not retried. No Baker Tilly rebrand site found.
- **Findex / Crowe**: now enabled. Oracle HCM host `egvc.fa.ap1.oraclecloud.com`, site `CX` (CX_1 returns the same 62 jobs). The vanity domain careers.findex.com.au blocks the REST API.
- **William Buck**: disabled. VIC is on Cornerstone careersite/4 (JS shell with an anonymous token for `uk.api.csod.com`). NSW/QLD/SA use ELMO boards. Needs a Cornerstone collector.
- **Nexia**: disabled. JobAdder public board `clientapps.jobadder.com/66341/nexia-australia` is HTML only (8 jobs, no location, no JSON-LD).
- **Bentleys**: disabled. Victoria (McLean Delmo Bentleys) has no ATS; only the QLD Greenhouse board exists.

Other additions
- **UNIQLO Australia** (retail): Workday `fastretailing / graduates_au_Uniqlo`, 2 jobs (Melbourne trainee internship, UMC graduate program). No separate UNIQLO AU store site was found on that tenant.

Other mid-tier and advisory firms (live 2026-10-06)
- Enabled: **McGrathNicol** (SuccessFactors googlefeed, 24 / 24 / 4, small feed), **KordaMentha** (SmartRecruiters, 28 / 27 / 10).
- Disabled, endpoint known but no collector: **Cutcher & Neale** (Rippling JSON, one row per location, 10 jobs), **Forvis Mazars** (JobAdder HTML, 6), **Kelly Partners** (LiveHire, Cloudflare 403), **SW Accountants** (Dayforce, 403 without a session), **UHY Haines Norton** (jsonld, Melbourne has 0 vacancies today), **Accru Melbourne** (empty WordPress feed), **Hayes Knight** (no open positions).
- Disabled, WordPress pages with no JSON-LD or RSS (a small HTML/sitemap collector would cover them): **HLB Mann Judd** (11), **Moore** (5), **PKF** (26), **Saward Dawson** (2), **Hall Chadwick** (5), **BG Private / Banks Group** (6).
- Disabled, no ATS: **Lowe Lippmann** (email), **Prosperity Advisers** (HTML), **FTI Consulting** (SelectMinds). Baker Tilly Australia and Walker Wayland had no resolvable careers page; Wellers is UK-only.

## RMIT employer-database "To add" batch (2026-10-06, 27 firms from `brain/data/jobwatch/sources/rmit-employer-db-A-F.md`)
- Enabled (11): Computershare and Treasury Wine Estates (Oracle HCM), CSL, APA Group, Brambles, Challenger, Cochlear (Workday, CSL and Brambles use `applied_facets` for Australia), BlueScope (SmartRecruiters), BHP, Eagers Automotive, Coates (SuccessFactors, slow tier).
- Ampol is disabled: its Attrax site works, but `models.is_australian()` rejects a locality like "Alexandria, AU", so the jsonld collector kept 0 of the 12 reachable postings.
- Disabled: Amcor (Workday, 0 AU), Ansell (Incapsula), Australia Post (Avature RSS, 20 items), Country Road, Coca-Cola Europacific (Radancy, robots), Bell Financial (no ATS), ARB and Brickworks (Connx JS), Data#3 (Salesforce Sites iframe), Cash Converters (Chris21), CSR (Springboard), Programmed (Applyflow), A2B (JobAdder, 11), Tetra Tech Coffey (SelectMinds), BAT (Radancy, robots, 0).
- Collector gaps seen: no Avature, JobAdder, Cornerstone, Rippling, LiveHire, Connx, Radancy or Springboard collector; `ats_phenom` widgets paging fails for PwC; `is_australian()` rejects ", AU" suffixes; Workday `is_australian()` can reject bare suburb locations (hence the AU facets).
- Dry runs (copy of the DB, no Matrix): workday 825 fetched / 522 AU / 193 VIC, oracle 248 / 158 / 50, smartrecruiters 1348 / 1348 / 367, successfactors 1806 / 1566 / 722, phenom 649 / 646 / 117, jsonld 36 / 36 / 36; 0 errors.
