// Workflow guidance the server gives its host: initialize `instructions`, the jobwatch_guide tool and skill:// resources.
// The skill texts are read from the repo at runtime (pipeline/agentic/skills); a bundled one-liner is the fallback.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const TOOL_COUNT = 21;

export const INSTRUCTIONS = `JOBWATCH OPERATING PROTOCOL (follow every turn)

Roles
- Jobwatch is the authoritative source of data and rules: profile, jobs, assessments, drafts, approvals. You, the host, run the conversation, the reasoning and the presentation. Jobwatch has no chatbot: do not relay questions to it or hand its output over as your answer.
- Answer the person's question in your own words: a short table or list, reasons, and what is uncertain. NEVER paste raw JSON or raw tool output.

Presentation
- Every tool returns a plain-text summary in content and structured data. Widgets (views) are OPTIONAL. If your host cannot render a view, present the result yourself from the summary and structured data (short table plus reasons). Never say you cannot answer because no widget showed, and never stall.
- Assessment activity is NOT a recommendation. "assessed", "queued", a score or a posting count only says Jobwatch looked at a job. Recommend a job only from job_detail: why it fits, pros, cons, score, and what is missing or stale. "Draft ready" is never "submitted".

Order of work
1. onboarding_status. If the profile is not confirmed: start_onboarding, ask the person the saved questions yourself, save only what they said (answer_onboarding_question, update_onboarding), review_onboarding, show the exact draft and search scope, and call confirm_onboarding only after they say yes to those unchanged digests.
2. discovery_status (collected, assessed, failed). start_discovery only when asked. retry_assessment only when the person explicitly asks for that retry.
3. jobs_overview for the list, job_detail for one job and its reasons.
4. Ask whether to prepare an application. Only after an explicit yes call prepare_application (revise_application for changes).
5. If it returns an approval, show the person its summary and confirm_digest, ask them to approve or reject, then call approve_application with that exact confirm_digest and user_quote set to their own words, verbatim. Never write the quote yourself, never approve for them, never reuse a digest.
6. review_submission shows the exact filled form. Show every answer and document to the person. Submitting is ALWAYS the person's own action on the exact form they reviewed (the Submit button in Jobwatch's review view or app). You cannot submit: never call submit_reviewed or decide.
7. task_status for progress.

Which tool for which question
- What needs me / what is going on: jobs_overview. Tell me about job N / should I apply: job_detail. How is job N going: task_status. Why nothing new / is it working: discovery_status. Where am I in setup: onboarding_status. Token allowance: get_discovery_settings / set_discovery_settings. How do I do X / what next: jobwatch_guide(topic).

Rules
- Candidate facts come only from the person or Jobwatch's saved evidence. Never invent; ask.
- When passing on a confirmation, quote the person's own words. Do not paraphrase them into consent.
- Every result has next_actions: plain sentences naming the next tool or question. Follow them unless the person asks something else.
- Errors: tell the person the reason in plain words and do not retry in a loop. A refusal is a safety check working, not something to route around.
- This server has ${TOOL_COUNT} tools. If your tool list is smaller, it is stale: tell the person to start a new thread (or reconnect the connector) instead of improvising.`;

export const TOPICS = ["overview", "onboarding", "discovery", "assess", "prepare", "submit", "troubleshooting"] as const;
export type Topic = (typeof TOPICS)[number];

export const SKILLS: Record<string, string> = {
  "career-ops": "Inspect a saved job, assess fit, or prepare an application; use Jobwatch's returned status and reason as the outcome.",
  "assess-fit": "Assess a saved job against current evidence without writing an application; explain cited requirements, matches, hard gates and uncertainties.",
  "prepare-application": "Prepare a tailored CV, cover letter and form map for a saved job after human approval. Preparing never submits.",
  "inspect-jobs": "Find saved jobs and explain current status using the authoritative latest outcome; never infer READY from a chat answer.",
  "company-research": "Research the employer and the skills the ad asks for; separate ad requirements from public company context; cite sources.",
  "followup-draft": "Draft a private follow-up for a confirmed application. Nothing is sent.",
  "interview-prep": "Prepare private, evidence-grounded interview material for a saved job. Never invent experience.",
  "model-insights": "Explain occupation fits, preference readiness and callback rates from existing calculations; report insufficient data explicitly.",
};

// Skills whose repo text is appended to each topic. They are written for Jobwatch's in-app agent, so tool names in them
// that are not in this server's list are internal.
const TOPIC_SKILLS: Record<Topic, string[]> = {
  overview: ["career-ops"],
  onboarding: [],
  discovery: ["inspect-jobs", "model-insights"],
  assess: ["assess-fit", "company-research"],
  prepare: ["prepare-application", "followup-draft", "interview-prep"],
  submit: [],
  troubleshooting: [],
};

const BUNDLED: Record<Topic, string> = {
  overview: `Jobwatch finds jobs, assesses each ad against the person's confirmed profile, prepares a CV, letter and filled form, and stops before Submit. The person always submits.
You (the host) hold the conversation and explain results; Jobwatch holds the data and the rules.
Flow: onboarding_status -> discovery_status -> jobs_overview -> job_detail -> (person says yes) prepare_application -> approve_application (person's exact words) -> review_submission -> person presses Submit themselves.
Presentation: summarise with reasons and uncertainty. Never paste JSON. Views are optional: if you cannot render one, give a short table and reasons from the summary.
Never present assessment activity ("assessed", a score, a count) as a recommendation; use job_detail's reasons.`,
  onboarding: `1. onboarding_status: status not_started, parsing, draft or confirmed.
2. not_started: the person's documents must already be uploaded in Jobwatch; start_onboarding takes their upload_ids. Ask the person if you do not have them.
3. draft: ask the person the saved questions in your own conversation. Save answers with answer_onboarding_question or edits with update_onboarding, always with the current expected_revision. Save only what the person said. Never invent facts.
4. review_onboarding: show the exact facts, search scope (basis, locations, daily assessments, token allowance) and limits.
5. Only after the person clearly agrees to that exact review, call confirm_onboarding with the unchanged proposal_digest and scope_digest. Confirming authorises discovery and assessment only; no documents, messages or submissions.`,
  discovery: `discovery_status shows what was collected, how many were assessed today, unresolved failures and notification state.
start_discovery queues one bounded assessment pass for the confirmed scope; use a new request_id per request and reuse it only after a lost response. It does not retry paused failures.
Failed assessments stay paused until the person explicitly asks. Then call retry_assessment for that incident using its retry_context as expected_context.
Collected postings are not recommendations. Use jobs_overview and job_detail to explain results.
Token allowance: get_discovery_settings / set_discovery_settings (null = unlimited) only on the person's request.`,
  assess: `Assessment results come from Jobwatch; you explain them. Use job_detail for score, why it fits, pros, cons, and assessment state/reason.
"assessed" means the evaluation finished; it does not mean a good fit, and it does not mean documents exist.
Report uncertainty: stale or missing assessment, no score, failed assessment, a hard gate. If the ad or profile fact you need is missing, ask the person; do not guess.
Do not start preparing an application just because the person asked for an assessment.`,
  prepare: `Ask the person first. After an explicit yes call prepare_application(posting_id, instructions). It hands the paid drafting work to Jobwatch's own agent and never submits.
If it returns an approval: show the person the approval summary and the confirm_digest, ask approve or reject, then call approve_application(posting_id, interaction_id, decision, confirm_digest, user_quote). user_quote is the person's own words, verbatim. Wrong digest or empty quote is refused and the approval stays pending.
Afterwards call task_status until the state is "draft ready". For changes use revise_application(posting_id, changes).
Then review_submission.`,
  submit: `Submission is always the person's own action on the exact form they reviewed.
1. review_submission(posting_id): show the person every answer (question, answer, source) and each document. If it says not ready, report the reason and stop.
2. The person presses Submit in Jobwatch's review view or app. This server does not let you submit: submit_reviewed and decide are app-only buttons; do not call them and do not ask the person to paste digests to you.
3. If the form changes after review, Jobwatch refuses the press; review again.
4. If the state is "outcome unknown", do not retry; tell the person and let them check the employer site.
Afterwards task_status shows the state (queued, executing, submitted, outcome unknown).`,
  troubleshooting: `- Tool list smaller than ${TOOL_COUNT}, or a tool is "not found": your tool catalog is stale. Tell the person to start a new thread or reconnect the connector.
- "Jobwatch is not reachable": the backend is down. Say so, do not retry in a loop.
- approval_not_found: the approval expired, was already answered, or belongs to another person; run prepare_application again only if the person still wants it.
- approval_digest_mismatch: the digest was not the one shown. Re-show the pending approval card and use its exact confirm_digest.
- review_changed / submit_digest_mismatch: the form changed after review; call review_submission again and have the person look at it.
- You cannot render a view: present the result yourself from the text summary. That fully answers the request.`,
};

function skillDirs(): string[] {
  const out: string[] = [];
  if (process.env.JOBWATCH_SKILLS_DIR) out.push(resolve(process.env.JOBWATCH_SKILLS_DIR));
  const roots = new Set<string>([process.cwd()]);
  try { roots.add(dirname(fileURLToPath(import.meta.url))); } catch { /* bundled without a file URL */ }
  for (const r of roots) {
    let d = r;
    for (let i = 0; i < 5; i++) {
      out.push(join(d, "pipeline", "agentic", "skills"));
      d = dirname(d);
    }
  }
  return out;
}

/** The SKILL.md body (frontmatter removed) from the repo, or null when it cannot be read. */
export function readSkill(name: string): string | null {
  if (!/^[a-z-]+$/.test(name) || !(name in SKILLS)) return null;
  for (const dir of skillDirs()) {
    const file = join(dir, name, "SKILL.md");
    try {
      if (existsSync(file)) return readFileSync(file, "utf8");
    } catch { /* try the next candidate */ }
  }
  return null;
}

const body = (raw: string) => raw.replace(/^---\n[\s\S]*?\n---\n?/, "").trim();

export function skillText(name: string): { text: string; source: "repo" | "bundled" } {
  const raw = readSkill(name);
  return raw !== null ? { text: raw, source: "repo" } : { text: `---\nname: ${name}\ndescription: ${SKILLS[name]}\n---\n\n${SKILLS[name]}\n(Full text unavailable on this server; this is the bundled summary.)\n`, source: "bundled" };
}

export function guide(topic: Topic): { text: string; sources: { name: string; from: "repo" | "bundled" }[] } {
  const sources: { name: string; from: "repo" | "bundled" }[] = [];
  const parts = [`JOBWATCH GUIDE: ${topic}`, BUNDLED[topic]];
  for (const name of TOPIC_SKILLS[topic]) {
    const s = skillText(name);
    sources.push({ name, from: s.source });
    parts.push(`--- Jobwatch agent skill "${name}" (${s.source}). Written for Jobwatch's in-app agent; tool names here that are not on this server are internal. ---\n${body(s.text)}`);
  }
  return { text: parts.join("\n\n"), sources };
}

export const GUIDE_NEXT: Record<Topic, string[]> = {
  overview: ["Call onboarding_status, then discovery_status, then jobs_overview."],
  onboarding: ["Call onboarding_status to see the current step."],
  discovery: ["Call discovery_status for the current state."],
  assess: ["Call job_detail with the posting_id the person asked about."],
  prepare: ["Ask the person whether to prepare it; only after an explicit yes call prepare_application."],
  submit: ["Call review_submission with the posting_id and show the person every answer and document."],
  troubleshooting: ["Tell the person the plain reason; if the tool list is stale, ask them to start a new thread."],
};
