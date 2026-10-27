# jobwatch web: template contract

Routes live in `app.py`, data in `queries.py` (read) and `actions.py` (write). Keep this file true.
**The old server-rendered board, job page, pane, table, applications and inbox pages are gone (2026-10-19, owner: "need to be removed completely").**
`/` is the app shell: `templates/app.html` extends `base.html` (the one shared shell: top bar, side rail, theme switch, `static/v3/web.css`, `static/v3/shell.js`) and `static/v3/v3.js` plus `static/v3/pages/*.js` draw the views into `<main id="view">`; everything they show comes from `/api/*` (below). Server templates remain only for
the pages listed under "Server pages that stay". Templates are Jinja2 (autoescape on) in `templates/`; styles in `static/app.css`, `board.css`, `pages.css`;
the only script files they load are `static/htmx.min.js`, `static/v3/shell.js` and the page's own file (no inline `<script>`; CSP is `script-src 'self'`). All styling is `static/v3/web.css` (dark by default, light via the top-bar switch; stored in `localStorage` as `jw-theme`).
Never print raw HTML from the database: descriptions are already plain text (`job.blocks`).
Dates: always `{{ x|... }}` through the globals `ago(ts)` ("3h ago") and `absolute(ts)`.

## Globals available in every template

`/discovery-status` uses `discovery_status.html` in the shared shell. Its
`discovery_status` context is the current authenticated person's typed discovery
status: posting/usage counts, unresolved paused incidents with safe reason and
phase codes, Hermes handoff state, recent invocations and latest queued API run.
`/api/discovery/status` returns the same object. Both reads retain normal web
authentication. Retrying assessments is a separate authenticated typed operation;
refreshing this page never releases a paused job.

`ago, absolute, short_location, salary_display(row), arm_label, src_label, flag_label, STATE_LABEL (dict),
WORK_TYPES (dict), WITHIN [(days,label)], TABS, STATUS_RAIL [(key,label)], SORTS [(key,label)], WARN (dict),
APP_STATES (tuple), TABLE_COLS [(key,label)], SOURCE_LABEL`, and for the AI reading: `AI_VIEWS [(key,label)]` (show Good, review
Not fully read, hide Hidden by AI, pending Waiting for AI), `HIDE_REASONS [(reason,label)]` (sponsored_ad, not_a_real_job,
needs_citizen_or_pr, too_senior, low_fit), `RIGHTS_TEXT` (rights value -> plain sentence), `BLOCKING_RIGHTS` (citizen_or_pr,
citizen_only, clearance), `SENIORITY_TEXT`, `AD_KIND_LABEL` (agency, talent_pool, scam), and the functions `hide_label(reason)`
("Needs citizenship or PR"), `hide_sentence(reason)` ("needs citizenship or PR"), `ai_view_text(ai, why)` ("Hidden by AI: Too senior"),
`row_ai_text(row)` ("Good", "Hidden: too senior", ...). For the career-ops report (prompt v3): `score_display(score, fit=None)` ("4.1"; fit/20 when the score is NULL;
"" when neither), `score_label(v)` (Strong match 4.5+, Good match 4.0+, Decent match 3.5+, Recommend against), `score_class(v)` (fit-hi 4.0+, fit-mid 3.5+, fit-lo),
`SCORE_FLOORS` (3.5, 4.0, 4.5), `SCORE_FLOOR_LABEL`, and the code-to-words dicts `HOURS_TEXT, WORK_MODE_TEXT, LOCATION_TEXT, IMPORTANCE_TEXT, TIER_TEXT, TIER_WHY,
MATCH_TEXT, REC_TEXT, LEGIT_TEXT` and the list `DIM_LABEL [(key,label)]` (cv_match, north_star, comp, culture, red_flags). `HIDE_REASONS` is, in order: sponsored_ad, not_a_real_job,
needs_citizen_or_pr, needs_unrestricted_rights ("Needs unrestricted work rights"), full_time_only ("Full-time only: does not fit your hours"), out_of_area
("Outside your search area, not remote"), too_senior, low_fit; `hide_sentence` gives "full-time only, which does not fit your hours" and "outside your search area, not remote" for running text.
`BLOCKING_RIGHTS` now includes `unrestricted_work_rights`.
Every context also has: `request`, `nav` (`{inbox, applications, sources_bad}` ints, or `{}` on error pages), `now`, `path`.

## Row (`r`) = one posting as a card/table row (from `load_rows`)
`id, title, company, location, state, remote, work_type, salary_text, salary_min, salary_max, url, source, origin,
matched_at, first_seen_at, posted_at, match_id, arm, arm_tier, app_status, first_viewed_at` plus computed:
`flags (list), warn (set of 'rights'|'fulltime'|'experience'), entry (bool), srcs (list of source ids, primary first),
listed_dt, age_days, added_at, sal_year, has_salary, sector, is_remote, is_vic, wt, tier ('core'|'fallback'|'other'),
status ('new'|'seen'|'saved'|'applied'|'closed'|'hidden'), score (0-100), score_why (list of str), ai (dict|None), ai_state,
score_src ('ai'|'rules'), score5 (float 0-5 or None), score_text ("4.1" or ""), archetype (str, "" when none), rule_score, rule_why`.
Board rows additionally have `teaser` (str, only for rows the AI gave no reason for, else "") and `is_new` (bool).

### The AI reading (`row.ai`, `row.ai_state`)
`load_rows` LEFT JOINs `ad_reviews` (one query). `ai_state` is `show | review | hide | pending`: no row = `pending` ("Waiting for AI"),
verdict `show`/`hide` as stored, anything else (`review`, unknown) = `review` ("Not fully read", held back). `ai` is `None` when pending, else a dict:
`verdict, hide_reason ('' unless hidden), fit (int 0-100 or None), score (float 1.0-5.0 or None), archetype (str), legitimacy (high|caution|suspicious|''),
report (dict|None, below), reason (str, whitespace collapsed), pros, cons (lists of str),
rights (none_stated|valid_work_rights|unrestricted_work_rights|citizen_or_pr|citizen_only|clearance), rights_quote (str), seniority (entry|junior|mid|senior|''),
min_years (int|None), role_match, ad_kind (employer|agency|talent_pool|scam|other), text_source (full|teaser|partial|''; partial = cut at the collector's 2000-character cap), flags (list), model,
reviewed_at (ISO str)`. Every string in it is model output about an untrusted ad: print it only through autoescape.
**Score.** `score5` = `ai.score` (the career-ops score, 1.0-5.0); when that is NULL (a row read with an older prompt) it is `ai.fit / 20`; None when the AI gave
neither (pending rows, failed reads). `score_text` is `score_display(score5)`. `score` stays on the 0-100 scale: `round(score5 * 20)` when `score5` is set
(`score_src == 'ai'`, `score_why = [ai.reason]`), otherwise the old keyword score (`score_src == 'rules'`). `rule_score` / `rule_why` always hold the keyword score
and its breakdown (the pane shows them under "Keyword match"). "Best fit" sort = `score`, newest first on ties; the Table's Score column sorts by `score5`.
**Report** (`ai.report`, from `ad_reviews.report_json`; None when the column is NULL or not a JSON object, which is how rows read with the older prompt look). It is
rebuilt defensively by `queries._report`, so a bad row can never break a page: unknown codes fall back, numbers are clamped, text is capped, lists are cut.
`archetype, tldr, role {seniority, work_mode (onsite|hybrid|remote|unstated), hours (full_time_only|part_time_ok|casual|unstated), location_fit (inner|mid|cbd_or_far_suburb|outer|remote|out_of_scope|''),
min_years}, requirements [{requirement, importance (critical|high|meaningful|preferred|low_signal), tier (stated|structural|inferred), jd_signal (only for stated), match (strong|partial|missing|na),
evidence}] (max 8, in stored order), gaps [{gap, risk, mitigation}] (max 3), dimensions {cv_match, north_star, comp, culture, red_flags: float 1-5 or None}, recommendation (apply|consider|skip|''),
legitimacy {tier, signals [str]}, comp {company_type, reliability (High|Medium|Low|Unknown)}, authorization {requirement, quote}`.

## Pages and routes

### The app and its JSON API
| Route | Result |
|---|---|
| `GET /` | the app shell (`static/app/index.html`), always; routing is by hash: `#board`, `#job/{id}`, `#table`, `#applications`, `#inbox`, `#chat`, `#insights`, `#sources`, `#interview[/{ref}]`, `#followup/{id}` |
| `GET /app` | the same shell (preview link) |
| `GET /api/board`, `/api/table` | `{rows, total, page, pages, size, counts, ...}` for the filters in the query string (`page` is ASCII digits, anything else is page 1) |
| `GET /api/job/{id}`, `POST /api/job/{id}/{save,hide,unhide,applied,status,notes,draft}` | the job (Job context below) / one action (JSON body `{status}` or `{notes}`); an `ActionError` is 400 |
| `GET /api/applications`, `POST /api/applications/{id}/followup` | the kanban / record a confirmed follow-up event |
| `GET /api/inbox`, `POST /api/inbox/{id}/{approve,reject}` | outcome proposals |
| `GET /api/sources`, `/api/insights`, `/api/meta`, `/api/nav`, `GET/POST /api/chat` | what the matching app view shows |
| `GET/POST /api/interview...`, `GET/POST /api/followup-draft/{id}` | interview preparation and follow-up drafts |
| `POST /api/searches`, `POST /api/searches/{id}/{open,delete}` | saved searches |
| `GET /table.csv` | CSV of the same filters, all rows (the app's "Export CSV" link). Columns: id, title, company, location, job type, tier, sector, sources, work type, salary, listed, first seen, flags, status, **score**, **archetype**, **recommendation**, **ai view**, **ai reason**, url. Every cell goes through the formula-injection guard (a leading `= + - @` tab or CR gets a `'`) |
| `GET /s/{id}` | 303 to `/?...` (opens a saved search) |

### Old URLs: GET 307 redirects into the app
`/classic` -> `/`, `/table` -> `/#table`, `/applications` -> `/#applications`, `/job/{id}` and `/job/{id}/pane` -> `/#job/{id}`,
`/inbox` -> `/#inbox`, `/sources` -> `/#sources`, `/insights` -> `/#insights`, `/pebble` -> 308 `/`. The pages, their POST forms and
the htmx fragments behind them (`/job/{id}/draft`, `POST /job/{id}/{action}`, `POST /applications/{id}/status|followup`,
`POST /inbox/{id}/{decision}`, `POST /searches`, `POST /searches/{id}/delete`) no longer exist.

### Server pages that stay (extend `base.html`; they set `{% set active = 'key' %}` to mark the rail item, and fill `{% block crumb %}` and `{% block content %}` inside a `<div class="wk-page">`; `{% set bare = true %}` hides the rail, as on /welcome)
| Route | Template | Why it stays |
|---|---|---|
| `GET /chat`, `POST /chat`, `POST /chat/ask` | `chat.html` | the app's Chat has no ask cards; this page is the only place they exist |
| `GET /candidate` | `candidate.html` | profile; not in the app |
| `GET/POST /preferences...` | `preferences.html` | not in the app; includes the per-person daily discovery token allowance |
| `GET/POST /answers` | `answers.html` | not in the app |
| `/design...` | `design*.html` | annotation notes and references; not in the app |
| `GET /job/{id}/prepare` (+ status, browser/*, answers, `POST prepare`) | `prepare.html`, `_preparation.html` | application preparation and the live form browser |
| `GET /job/{id}/evaluation` | `evaluation.html` | linked from the app's Applications |
| `/applications/{id}/followup-draft`, `/jobs/{id}/interview-prep...`, `/interview-prep...` | `followup_draft.html`, `interview_prep.html`, `interview_url.html` | server forms and downloads; the app has its own views (`#followup`, `#interview`) that use the `/api/` equivalents, these pages are not linked from the app |
| any 404 / 422 | `error.html` | `message`, `code` (422 only) |

## Job context
`job` = a row plus `blocks` (list of `{'p': str}` or `{'ul': [str]}`), `desc_truncated` (bool), `sightings`
(list of `{source,url,first_seen_at,last_seen_at,times_seen}`), `rules` (dict), plus `ai`, `ai_state`, `rule_score`, `rule_why` from the row, `arms` (list of arm ids),
`flag_reasons` (list of `{flag,label,kind,why,snippet}`), `app` (application dict or None: `id, status, notes,
applied_at, updated_at, ...`), `events` (list of `{at,kind,from_status,to_status,actor,source}`).
`app` (same as `job.app`), `draft` = `{state: none|running|ready|failed|error, error, files: {cv,letter,summary} (URL paths
under /files/drafts/...), version, started}`, `files_ok`.

## Application (`a`) in `applications` / kanban
`id, posting_id, status, notes, applied_at, updated_at, title, company, location, url, event_text, last_at, stale (bool),
days_applied, files {cv,letter,summary} (URL paths), draft_state`.

## Proposal (`p`) in the Inbox
`id, application_id, posting_id, title, company, proposed_status, app_status, subject, from_addr (domain), mailbox,
received_at, confidence, evidence (str), ev_flags (list), method, status, decided_at`.

## Health row (`h`) / employer row (`e`)
`h`: `collector, label, last_status, last_ok_at, last_count, last_latency_ms, consecutive_failures, last_error, rag ('ok'|'warn'|'bad')`.
`e`: `name, sector, provider, enabled, vc_total, vc_au, vc_vic, live, matches, notes, verified_at, scope`.

## `ins` (insights)
`series` [(date, n)] 30 days; `by_arm` [(arm, tier, n)]; `by_src` [(source, n)]; `by_sector` [(sector, n)]; `top` [(employer, postings, matches)];
`remote` `{matches: (remote, total), all: (remote, total)}`; `themes` [(theme, n)]; `by_subreddit`; `reddit_top` (list of dicts);
`chatter_total`, `hiring_posts`; `callbacks` (dict `{arm: {successes, n, mean, hdi, a, b}, '_all': {...}}`; `_all` is always present, with `n` 0 when there are no applications); `prior_mean`; `totals` `{postings, matches, matches_30d, matches_7d, employers_live}`.

## Filter helpers (on `f`)
`f.query(**over)` returns a URL query string with overrides (empty value removes a key); `f.active_count()`, `f.summary()`.
Facet form fields use these names: `q, x, arm, tier, src, sector, within, arr (remote|vic), wt, sal, salmin, entry, hide (rights|fulltime|experience), st, sort, dir, scope (all), ai, why, minscore, arch`. Multi-valued fields repeat the key.

### Score floor and archetype (`minscore`, `arch`)
`minscore=3.5|4.0|4.5` keeps jobs whose `score5` is at least that (a NULL-score row counts as fit/20; a job the AI has not scored never passes). Anything else (`4`
is read as 4.0, `3.7` is not offered) is ignored. `arch=<archetype>` is multi-valued and matches `r.archetype` exactly; unlike the other multi fields its values are never split on commas
(archetypes are free text, up to 80 characters; hybrids look like "A + B"). Both count as filters (`f.active_count()`, chips "Score 4.0+" and one per archetype, Clear all), appear in
`f.summary()`, saved searches, `/table` and `/table.csv`. `counts['minscore']` = `{3.5: n, 4.0: n, 4.5: n}` and `counts['arch']` = archetype -> n, each counted with its own filter lifted.
`f.clear_over()` returns the `query()` overrides that drop every facet filter (used by every Clear all link). The pills are `#pill-minscore` (radio group named `minscore`, ids
`<pfx>-minscore-any|3.5|4.0|4.5`) right after the AI view, and `#pill-arch` (checkboxes named `arch`) after Sector; the face of the Score pill reads "Score 4.0+".

### AI view (`ai`, `why`)
`ai=show|review|hide|pending` (default `show`, never written to a URL) picks which postings the list, the tab counts, the facet counts, saved
searches, `/table` and `/table.csv` use; every posting is in exactly one. `why=<hide_reason>` narrows `ai=hide` to one reason (letters and
underscores only; ignored for any other view; an unknown reason is a valid filter that matches nothing). An unknown `ai` falls back to `show`.
The form's radio group is named `ai` and also carries `ai=hide:<reason>` for the reason options; `Filters.from_params` reads that as
`ai=hide&why=<reason>` (an explicit `why` wins), and `f.query()` always writes the two-parameter form. The view is not a "filter":
`f.active_count()`, the chips and Clear all ignore it; `f.summary()` names it when it is not Good ("Good matches" otherwise).
`counts['ai']` = jobs per view and `counts['why']` = hidden jobs per reason (reason `other` when none is stored), each counted with every
*other* filter applied, so the tabs respect the view while the pill's own counts do not shrink to the chosen view.
`f.ai`, `f.why` are the two fields on `Filters`.

## Design (annotations and references)
Code: `design.py` (data functions, Markdown export and routes; registered from `create_app`), `static/annotate.js` and
`static/annotate.css` (loaded by `base.html` on every server page), templates `design.html`, `design_ref.html`, `design_notes.html`.
Storage: UI-only tables `design_refs` and `design_notes` (db.py migration v4; not part of the ledger or `reindex`) and image files
`<data dir>/design/<32 hex>.png|jpg|webp` (random names; `design/removed/` keeps removed images). Limits: comment 2000, snapshot 120,
selector 300 characters; at most 500 open notes, 200 references; images png/jpeg/webp only, up to 8 MB, checked by magic bytes.

| Route | Template / result | Context |
|---|---|---|
| `GET /design` | `design.html` | `refs` (list of `{id,title,source_url,mime,width,height,created_at,open_n,total_n}`), `counts` `{open,resolved,all}`, `error`, `form` (kept title/source on error), `max_mb`, `categories` |
| `POST /design/upload` | redirect 303 to `/design/ref/{id}`; on error `design.html` with status 400/411/413/415 | multipart `file`, `title`, `source_url` |
| `GET /design/ref/{id}` | `design_ref.html` | `ref` (as above), `categories` |
| `GET /design/img/{id}` | image | fixed content type from our own file name, `nosniff`, inline |
| `POST /design/ref/{id}/remove` | redirect to `/design` | moves the file to `design/removed/`, deletes the row and its notes |
| `GET /design/notes` | `design_notes.html` | `notes` (note dicts plus `ref_title`), `f` `{status,category,page}`, `counts`, `qs` (filter query string), `categories`, `truncated` |
| `GET /design/notes.md` | text/plain Markdown | query `status` (open default, resolved, all), `category`, `page` |
| `POST /design/notes/{id}/resolve|reopen|delete` | redirect to `/design/notes?<filters>` | form `resolution` (optional), `back` (filter query string; only status, category, page are kept) |

JSON api (used by `annotate.js`; same Origin rule as every POST; bodies are `application/json`, at most 32 KB):
`GET /design/api/notes?path=/x[&status=all]` or `?ref=ID` returns `{notes:[...]}`; `POST /design/api/notes` creates (201, `{note}`);
`POST /design/api/notes/{id}` edits comment, category, priority; `POST .../resolve` (`{resolution}`), `POST .../reopen`; `DELETE /design/api/notes/{id}`.
Errors are `{error: "plain sentence"}`. A note is `{id, ref_id, page, selector, snapshot, tag, rect, viewport, scheme, comment, category,
priority, status, created_at, resolved_at, resolution}`. `page` is path plus query and is matched by path. Page notes use document-pixel rects;
reference notes use fractions 0..1 of the image (`w` and `h` are 0 for a pin). Categories: layout, spacing, colour, typography, content,
behaviour. Priorities: low, med, high.

Hooks the markup must keep: annotate mode inserts `#an-toggle` into `.topbar` before `[data-theme-toggle]` and builds selectors from
ids, `data-id` and `data-*` values, then classes, then `:nth-of-type`, so keep ids such as `card-N` and `data-id` stable. The overlay carries
`data-annot-ui`; `[data-theme-toggle]` is never intercepted. Text snapshots skip every form control, `contenteditable` and `[hidden]`.
The viewer needs `#ref-viewer` (with `data-ref-id`), `#ref-stage`, `#ref-canvas`, `#ref-marks`, `#ref-list`, buttons `[data-zoom]` and `[data-filter]`.
Keys: `A` toggles Annotate mode, `Enter` picks the outlined element, `Shift+Up/Down` parent/child, `Ctrl`+click uses the page, `Esc` closes/exits.
CLI (`cli_ext.py`): `jobwatch design notes [--open] [--md] [--all] [--page PATH]`, `design resolve ID [--note T]`, `design add-image PATH [--title T] [--source-url U]`.

## Errors and odd numbers
- A `show` verdict whose `text_source` is `teaser` or `partial` is listed as `review` ("Not fully read"): `queries.ai_state`. Teaser and partial read the same everywhere
  (card badge, "Held back" banner, work rights and years "Not checked"), only the wording differs: "short teaser" vs "cut copy of the ad".
- Every integer id in a path (job, search, proposal, design ref and note) must be 1..2**63-1, else 404 (never an OverflowError). Query numbers (`page`, `job`, `within`, `salmin`, `minscore`) are clamped or ignored.
- A bad request value gets the HTML error page for browsers, `{"error": ...}` JSON for `/design/api/*` and for requests with `Accept: application/json` or `X-Requested-With`,
  and a one-line `<p class="error-note">` fragment (status 422, 404 for a bad path id) for htmx (`HX-Request`).
- `/design/upload` needs an ASCII-digit `Content-Length` (else 411) no bigger than the image limit (else 413).

## Preference learning
`GET /preferences` reads current profile/evaluation provenance and immutable choice history without recording choices, fitting a model or calling an LLM. Context: `preference_state` (status/counts/fit), `choices` (currentness, answered state, three escaped alternatives and an idempotency token), `preference_error` (fixed public message). `POST /preferences/new` snapshots three previously unseen, current eligible evaluated jobs; `POST /preferences/{set_id}/pick` rechecks current provenance and records an explicit owner selection or none, protected by the global same-origin guard. Predictions are never shown before an unanswered comparison, avoiding model-primed validation labels. Fitting is local and on demand through `jobwatch preferences fit --output-dir PRIVATE_DIR`.

`GET /preferences` also reads the effective `daily_token_ceiling` for `users.current()` and renders it as the discovery token allowance; `null` means Unlimited. When no per-person override exists, the value comes from the confirmed discovery scope or the configured batch ceiling. `POST /preferences/discovery-settings` accepts form fields `mode` (`limited` or `unlimited`) and `daily_token_ceiling` (a positive ASCII whole number when Limited). It writes only the current authenticated person's override through `pipeline.agentic.discovery_settings`, then redirects to `/preferences` with 303. Invalid selection or limit returns 400 with a fixed visible explanation; cross-origin posts are refused by the global origin guard. Unlimited removes the daily token cap only; the daily assessment count and per-run ceilings remain in force. The setting is operational and does not change learned preference rankings.

### Follow-up owner controls (DES-42 / CAP-6)
Application cards carry `followup` state/kind/due_on/sent_count/reason and a per-render idempotency token. The Applications page shows cadence only for active applications. `POST /applications/{posting_id}/followup` accepts an explicit owner-confirmed event, date pin or pin removal and writes only the existing application event ledger. It never sends a message or marks a draft sent. Date/time inputs are Melbourne local time; ambiguous DST times, future events and pre-submission events are rejected. Ordinary form success redirects to Applications; HTMX success returns the kanban. Invalid input returns422 with a fixed safe explanation. Generated drafts use the separate owner-requested review page described below.

`GET /applications/{posting_id}/followup-draft` revalidates source/profile/history identity before displaying any approved text; HTMX requests return only the status section. `POST` starts an explicitly requested bounded writer/reviewer task in the existing web process (FastAPI background task), gated by `pipeline.agentic.enabled`. It has no send capability. Durable application-event checkpoints precede each model call and survive ledger replay; duplicate requests reuse the same snapshot record. Unknown failed calls retain maximum budget reservations and are not automatically retried. Stale/terminal/not-due inputs hide old text. Only a hash-bound approved draft is displayed for owner copy/review.

Held follow-up drafts may be explicitly retried by the owner within the original token/turn/failure limits. Prior unknown charges are retained, expired worker writes are fenced by attempt identity, and GET never starts a retry. Missing/malformed candidate sources render readiness instead of an internal error.

### Interview preparation (DES-43 / T28)
`GET /jobs/{posting_id}/interview-prep` displays optional owner context and a source-revalidated private report, with HTMX status polling during explicitly queued work. No application row is required or created. The inputs POST saves six bounded optional text sources using a revision check and the existing private ledger. The generation POST uses the existing web-process background queue; only provided paid combos and current enabled configuration are used. Held work retries only on an explicit owner POST while retaining previous reservations and limits. Job/Application entry links expose the page. Successful owner transitions to interview (including approved outcome proposals) queue once only when the current evaluation scores at least4.0 and there is no existing current attempt. This is not a new timer or external notification.

Reviewed reports render all fifteen structured sections, factual/inference/advice/unknown labels, result-first answers, primary versus owner-fact grounding and source citations. Source and draft hashes bind the independent review; all content is escaped. `/download` revalidates current inputs and returns a private no-store text attachment; stale or unavailable data returns409. Missing/malformed profiles and notes produce fixed readiness messages. The URL-entry flow for roles not yet collected is a separate unfinished part; existing unevaluated postings work without any application-state mutation.

Interview requests are durably queued before response. Lifespan recovery in the existing process resumes only undispatched work, and recovers unhandled owner-confirmed interview transitions once per event. It never re-enqueues a changed snapshot during recovery and never auto-retries running/held work. The current worker drains separately queued owner requests without dropping wakeups. No external notification or persistent scheduler is introduced.

Standalone interview preparation: `/interview-prep` accepts an explicit job URL or owner-pasted complete JD, preferring a source-current existing evaluation. Acquisition never writes postings, applications or status events. Private subjects and their reports are replayable v11 ledger indexes; duplicate sources preserve notes and allowance. Subject pages reuse the same bounded Deep Agents review, durable queued recovery and retry accounting. Source method/date/URL and complete saved JD are visible; fallback is explicitly unconfirmed. Owner note changes invalidate display/download. No model work begins merely by saving a URL/JD.
