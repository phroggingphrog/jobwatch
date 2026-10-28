# Intent: jobwatch   (revision 1, accepted by the owner 2026-10-09 23:55Z)

Rulebook: `~/phrogvps/INTENT-FIRST.md`. This file wins over `GOAL_CONTRACT.md`, PLAN*.md and any CONTEXT/PLAN.
Agents never edit the sections above "Rulings". Owner changes are added as new dated quotes.

## Owner's words (verbatim, dated)
> 2026-10-06 (chat, repeated several times): jobwatch is "basically automated career-ops".
> 2026-10-09 (chat): "you can see the original concepts it meant to use an agentic system"
> 2026-10-09 (chat): "thats why everything looks template you fuck it up"
> 2026-10-09 (chat): "why its stray away from the concept too far"
> 2026-10-05 (owner decisions, recorded in career.sqlite `owner_decision`, reconfirmed 2026-10-07): customer service and
> hospitality are NOT targets; internships, vacation and graduate programs ARE targets.
> Standing rule (~/.agents/AGENTS.md): "HUMAN_REQUIRED: submitting job applications" and "Finance and candidate data never
> go to free or stealth model routes"; job rule: "no free openrouter/commandcode LLM model".

## Identity
An **agentic career-ops system**: AI agents do the career work for each job (read the whole ad, judge it against the
owner's real profile, research when useful, write tailored applications, prepare the form). Only *collecting* jobs is a
fixed script. It is **not** a keyword watcher and **not** a fixed pipeline that calls a model per step. The agent is
**autonomous**: it reasons from the owner's instructions in conversation (owner 2026-10-25), uses its tools to act on
them, and reports what it did. Conversation can override hard gates; the agent decides with reasoning, not fixed rules.

## Capabilities
- **CAP-1 Collect.** New Melbourne/Victoria openings from boards, ATSs and employer sites, deduplicated, with source
  health. Fixed script on timers (the one non-agentic part). Success: the Sources page shows each source's health.
- **CAP-2 Agentic evaluation.** An agent reads the *whole* ad and evaluates it against `career_ops_profile.md` + CV with
  the career-ops rubric (`oferta.md`/`_shared.md`): 1-5 score, archetype, requirement-to-CV match, work rights,
  legitimacy, owner targets and hard gates. Success: each evaluated job shows the agent's reasoning on its Job page.
- **CAP-3 Agentic drafting.** An agent writes a CV and cover letter *for that job and employer*, without reading as a
  template. Success: 3 random drafts read as written for their job, judged against the golden example; each passes
  `verify_pdf`.
- **CAP-4 Board.** Personal Seek/LinkedIn-style board at jobs.phroggingphrog.com (Access-protected), the only alert
  channel. Success: the board shows new good matches with reasons, and READY jobs.
- **CAP-5 Form filling.** Open the application, fill every field from the answers file, attach CV and letter, **stop
  before Submit**. Success: a real form filled up to Submit, shown with a screenshot.
- **CAP-6 Tracker and follow-ups.** Applications, outcomes and callback statistics.

## Mechanisms required
- CAP-2 and CAP-3 are done by agents (the owner said "agentic system"), not one fixed prompt per step.
- Models only through paid OmniRoute `openai/`, `claude/`, `google/` combos.

## Non-goals
- Keyword match as the decision. Template-like drafts. Submitting an application without the owner's click or explicit
  confirmation (which may be given in chat or through the endpoint). Customer service, hospitality, retail or shop-floor roles as targets.

## Success signal
The owner opens the board, sees jobs worth applying for with an agent's reasons, opens one, finds a CV and letter that
read as written for that job and a form filled up to Submit, and submits with one click or one confirmation (web UI or chat).

## Invariants (checked every release)
- Nothing is submitted without the owner's own click or explicit confirmation of the exact reviewed form (chat or
  endpoint is fine). No free model routes. Hard gates (work rights, Melbourne/remote, entry level, hours) are the
  agent's defaults; the owner's words in conversation can override them.

## Examples
- Golden: the original career-ops evaluation and writing modes (`oferta.md`, `_shared.md` in Drive
  `hermes-gdrive:phrogvps-archive-20261008/job-system-20261004.tar`).
- Golden CV/letter look (owner 2026-10-12: "my original CV and Cover Letter is not this bad"): the owner's original
  `~/brain/data/raw/_from-mac-20261004/important-documents/Employment & Work Related/CV and Cover Letter/` (.CV.docx/.pdf,
  .CL.docx), plus `~/brain/data/career/templates/` and `GENERATOR-CONTRACT.md`. Drafts must start from these.
- Anti: current pipeline drafts in `~/brain/data/jobwatch/drafts/` (template-like, owner 2026-10-09).

## Open questions
- (none yet; agents add them here and ask through one request_confirmation)

## Rulings
| R | date | CAP | question / deviation | ruling | by | ref |
|---|---|---|---|---|---|---|
| R1 | 2026-10-14 | CAP-2 | Does a rolling-intake vacation/intern program (no identified live vacancy, e.g. KPMG Vacationer #354) count as a real job? | **Only if it has a proper job opening.** A rolling intake pool with no identified live vacancy (KPMG Vacationer #354) is not a real job and stays archived (`real_job=false`, `hard_gate`); a vacation/intern/graduate program with a real, open vacancy still counts as a target. | owner (chat: "no", then "only if they have proper job opening") | evaluation of #354 |
| R2 | 2026-10-25 | CAP-5 | Who may trigger Submit? The protected text says the owner always submits and only presses Submit; that came from web-UI planning. | **(Now folded into the sections above.) Submission needs the owner's own click OR their explicit confirmation of the exact reviewed form, and that confirmation may come from chat** (or the endpoint). It is never automatic. Where Non-goals/Success signal say "the owner always submits / only presses Submit", read them with this ruling. | owner (chat 2026-10-25: "submission happens either a click or confirmation which can be from chat; if its from endpoint the intent mixed up with the web ui planning") | jobwatch-native INTENT Boundaries |

## Deferred
| CAP / item | why | ruling R-n or phase | revisit when |
|---|---|---|---|

## Owner 2026-10-19
"ok the final jobwatch should be agnostic wise regardless of field etc"
"what else do we need to make it live it need to be proper build ready"
"this shoudl be based on profile, and agent should asked it over the chat and notify the users and render it as user interactive question like how DSH did / claude code did maybe verify/check instead of form make it like not robotic"
"bcs if you keep asking that what happen when new profile/another person use the app? as everything going on through the app web right"
Owner chose: Yes, multi-person (each person own profile, CV, answers, logins).
"yes add fix and after that we need to redesign the model selection"
"what i want is to use all of the template as consideration e.g. my friends, the one from cv consultations, the career ops or some github that we cloned and then use reasoning"

## Owner 2026-10-25
"conversation can override hard gates and agent need to use reasoning"
"submission happens either a click or confirmation which can be from chat; if its from endpoint the intent mixed up with the web ui planning"
"just edit it" / "i want it to be autonomous so proceed"
