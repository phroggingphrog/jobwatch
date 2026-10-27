// Every Jobwatch MCP tool, defined once through defineTool. See GUIDANCE.md for how to add one.
// Handlers only forward to the Python connector service; all safety checks (digests, single-use approvals,
// per-person data) live there. Importing this module needs no environment, so the docs generator can use it.
import { z } from "zod";
import { backendConfig, call, type BackendConfig } from "./backend.js";
import { renderGuide, TOPICS } from "./guidance.js";
import { READ, WORK, clip, defineTool, fail, reply, widgetMode, type AnySpec } from "./registry.js";
import {
  onboardingStatusOut,
  onboardingReviewOut,
  onboardingConfirmOut,
  onboardingEdit,
  discoveryStatusOut,
  discoveryQueuedOut,
  discoverySettingsOut,
  discoverySettingsResult,
  dashboardOut,
  guideOut,
  jobOut,
  overviewOut,
  applicationsOut,
  reviewOut,
  submitOut,
  taskOut,
  type TaskOut,
} from "./schemas.js";

let cached: BackendConfig | undefined;
const cfg = () => (cached ??= backendConfig());

const posting = z.number().int().min(1).describe("Jobwatch posting id");
const proposalId = z.string().regex(/^[a-f0-9]{16}$/);
const revision = z.number().int().min(1);
const digest = z.string().regex(/^[a-f0-9]{64}$/);

const countsText = (c: z.infer<typeof applicationsOut>["counts"]) =>
  ([["needs_you", "need you"], ["needs_info", "need info"], ["outcome_unknown", "outcome unknown"], ["submitted", "submitted"]] as const)
    .filter(([k]) => c[k])
    .map(([k, l]) => `${c[k]} ${l}`)
    .join(" · ") || "No application actions pending";

const assessmentLabel = (j: { assessment_state?: string | null; assessment_reason?: string | null }) =>
  j.assessment_state ? `${j.assessment_state === "current" ? "assessed" : j.assessment_state}${j.assessment_reason ? ` (${j.assessment_reason})` : ""}` : "no assessment recorded";

// ---- shared readers: used by the plain read tools and by open_dashboard ---------------------------------------------
const labelText: Record<string, string> = { stronger_match: "stronger match", stretch: "stretch", needs_clarification: "evidence hold (needs clarification)" };
const shortlistLine = (j: z.infer<typeof overviewOut>["jobs"][number]) =>
  `#${j.rank} job ${j.posting_id} ${j.employer ?? "?"} - ${j.title ?? "?"} | ${labelText[j.label] ?? j.label} | fit: ${clip(j.objective_fit, 120)} | uncertainty: ${clip(j.uncertainty, 100)} | ${j.can_prepare ? "can prepare after consent" : "cannot prepare yet"}`;

function shortlistView(d: z.infer<typeof overviewOut>, refreshed = false) {
  const lines = d.jobs.slice(0, 10).map(shortlistLine);
  const holds = d.jobs.filter((j) => !j.can_prepare).length;
  const head = d.status === "ok"
    ? `${refreshed ? "Shortlist refreshed" : "Shortlist"}: ${d.jobs.length} current matches in rank order${holds ? `, ${holds} of them evidence holds` : ""}. ${d.meaning}`
    : `Shortlist ${d.status}: ${d.jobs.length} matches. ${d.meaning}`;
  const next: string[] = [];
  if (d.status === "no_confirmed_profile") next.push("There is no confirmed profile. Call onboarding_status.");
  else if (d.status === "not_built" || d.status === "stale") next.push("The shortlist is not current. Call refresh_shortlist (stored assessments only, no paid work), then jobs_overview again.");
  else if (!d.jobs.length) next.push("The shortlist is empty. Call discovery_status to see whether jobs are being collected and assessed.");
  else {
    next.push(`Call job_detail with posting_id=${d.jobs[0].posting_id} (or the job the person names) for its evidence, conditions and open questions before recommending anything.`);
    if (holds) next.push("Evidence holds cannot be prepared: ask the person the unresolved questions shown in job_detail.");
  }
  const summary = [head, ...lines, ...(d.jobs.length > 10 ? [`(+${d.jobs.length - 10} more in the structured data)`] : []), "Scores and ordering are advisory evidence, not a hiring probability or approval to apply."].join("\n");
  return { summary, next };
}

function applicationsView(d: z.infer<typeof applicationsOut>) {
  const lines = d.jobs.slice(0, 10).map((j) => `job ${j.posting_id} ${j.employer ?? "?"} - ${j.title ?? "?"} | application: ${j.state}${j.detail ? ` (${clip(j.detail, 80)})` : ""}`);
  const next: string[] = [];
  if (d.jobs.length) next.push(`Call task_status or application_detail with posting_id=${d.jobs[0].posting_id} (or the job the person names) for one application.`);
  else next.push("No application history. If the person wants new jobs, call jobs_overview.");
  if (d.counts.outcome_unknown) next.push("Tell the person which applications have an unknown outcome; do not retry them.");
  next.push("Do not present this history as a recommendation; recommendations come only from jobs_overview.");
  return { summary: [`${countsText(d.counts)}. ${d.jobs.length} applications in history.`, ...lines, ...(d.jobs.length > 10 ? [`(+${d.jobs.length - 10} more in the structured data)`] : [])].join("\n"), next };
}

function discoveryView(d: z.infer<typeof discoveryStatusOut>) {
  const lines = [
    `Discovery ${d.enabled ? "enabled" : "disabled"}: ${d.postings} postings collected; ${d.assessments_today} assessed today (${d.charged_tokens_today} tokens); ${d.incidents.length} unresolved incident${d.incidents.length === 1 ? "" : "s"}.`,
    ...(d.scope ? [`Scope: ${d.scope.basis.join(", ") || "none"} in ${d.scope.locations.join(", ") || "no location"}; up to ${d.scope.daily_assessments} assessments a day.`] : ["No confirmed scope yet."]),
    ...d.incidents.slice(0, 8).map((i) => `- incident ${i.incident_id}${i.posting_id != null ? ` (job #${i.posting_id})` : ""}: ${i.reason} in ${i.phase ?? "?"}, ${i.state}; notification ${i.notification_state}${i.notification_error ? ` (${i.notification_error})` : ""}`),
  ];
  const next: string[] = [];
  if (!d.enabled) next.push("Discovery is off. Call onboarding_status: the profile may not be confirmed.");
  else if (d.postings) next.push("Call jobs_overview for the current canonical shortlist (collected postings are not recommendations), then job_detail for one entry.");
  if (d.incidents.length) next.push("Tell the person what failed and why. Call retry_assessment only if they explicitly ask, using that incident's retry_context as expected_context.");
  if (d.enabled) next.push("If the person wants more jobs assessed, call start_discovery with a new request_id.");
  return { summary: lines.join("\n"), next };
}

const settingsView = (d: z.infer<typeof discoverySettingsOut>) => ({
  summary: d.daily_token_ceiling === null ? "Daily token allowance: Unlimited." : `Daily token allowance: ${d.daily_token_ceiling}.`,
  next: ["Change it only if the person asks, with set_discovery_settings."],
});

const readShortlist = async (limit: number) => overviewOut.parse(await call(cfg(), "GET", `/connector/overview?limit=${limit}`));
const readApplications = async (limit: number) => applicationsOut.parse(await call(cfg(), "GET", `/connector/applications?limit=${limit}`));
const readDiscovery = async () => discoveryStatusOut.parse(await call(cfg(), "GET", "/connector/discovery/status"));
const readSettings = async () => discoverySettingsOut.parse(await call(cfg(), "GET", "/connector/discovery/settings"));

// ---- task cards ---------------------------------------------------------------------------------------------------
function taskFromCard(card: Record<string, unknown>, posting_id: number): TaskOut {
  const submit = (card.submit ?? {}) as Record<string, unknown>;
  return {
    posting_id,
    state: String(card.state ?? "not started"),
    ...(typeof card.message === "string" && card.message ? { message: card.message } : {}),
    ...(typeof submit.reason === "string" && submit.reason ? { reason: submit.reason } : {}),
  };
}

function nextForState(posting_id: number, state: string): string[] {
  switch (state) {
    case "not started":
      return [`Nothing has been done on #${posting_id}. If the person wants to apply, ask, then call prepare_application.`];
    case "queued":
    case "drafting":
      return [`Drafting is in progress. Tell the person, and call task_status for #${posting_id} again later.`];
    case "draft ready":
      return [`Call review_submission with posting_id=${posting_id} so the person can check the exact form.`];
    case "awaiting browser press":
      return ["The reviewed form is waiting for the person's own Submit press. Tell them to press Submit in Jobwatch; you cannot."];
    case "executing":
      return [`Submission is being processed. Call task_status for #${posting_id} again shortly; do not retry.`];
    case "submitted":
      return ["Tell the person it was submitted. Nothing more to do here."];
    case "outcome unknown":
      return ["The outcome is not known. Do not retry. Tell the person to check the employer's site or inbox."];
    case "failed":
    case "cancelled":
      return ["Explain the reason shown. Ask the person whether they want it prepared again; do not retry on your own."];
    default:
      return [`Report the state to the person as returned: ${state}.`];
  }
}

function workResult(posting_id: number, res: { data: Record<string, unknown>; meta: Record<string, unknown> }) {
  const d = res.data;
  const awaiting = d.status === "awaiting_approval";
  const confirm = typeof d.confirm_digest === "string" ? d.confirm_digest : undefined;
  const out: TaskOut = {
    posting_id,
    state: awaiting ? "awaiting approval" : d.decision === "reject" ? "rejected" : "complete",
    ...(awaiting
      ? { approval: { interaction_id: String(d.interaction_id), operation: String(d.operation), summary: String(d.summary), ...(confirm ? { confirm_digest: confirm } : {}) } }
      : { answer: String(d.answer ?? "").slice(0, 1500) }),
    ...(Array.isArray(d.declined) ? { declined: d.declined.map(String) } : {}),
    ...(d.decision === "approve" || d.decision === "reject" ? { decision: d.decision } : {}),
  };
  const meta = typeof res.meta.binding === "string" ? { binding: res.meta.binding } : undefined;
  if (awaiting) {
    const a = out.approval!;
    const next = confirm
      ? [
          `Show the person this approval: "${a.summary}" and its confirm_digest ${confirm}. Ask whether to approve or reject. Do nothing until they answer.`,
          `Then call approve_application with posting_id=${posting_id}, interaction_id="${a.interaction_id}", decision, confirm_digest=${confirm} and user_quote = the person's answer in their own words, verbatim.`,
        ]
      : ["This approval cannot be answered from chat. Tell the person to answer it in Jobwatch. Do not call decide."];
    return reply(`${a.summary} Approval needed before anything is drafted.${confirm ? `\nconfirm_digest: ${confirm}` : ""}`, out, next, meta);
  }
  const declined = out.declined?.length ? ` Jobwatch declined to proceed with: ${out.declined.join(", ")}.` : "";
  if (d.decision === "reject") return reply(`Rejected. Nothing was changed.${declined}`, out, ["Ask the person what they want changed, or leave it."], meta);
  return reply(
    `${clip(out.answer || "Done.", 1200)}${declined}`,
    out,
    [`Call task_status with posting_id=${posting_id}; when it says 'draft ready', call review_submission so the person can check the form.`],
    meta,
  );
}

// ---- onboarding -----------------------------------------------------------------------------------------------------
function onboardingNext(d: z.infer<typeof onboardingStatusOut>): string[] {
  const p = d.proposal;
  switch (d.status) {
    case "not_started":
      return ["Ask the person for their CV or other documents (they must be uploaded in Jobwatch), then call start_onboarding with the upload_ids."];
    case "parsing":
      return ["Jobwatch is still reading the documents. Tell the person and call onboarding_status again shortly."];
    case "confirmed":
      return ["The profile is confirmed. Call discovery_status to see what has been collected and assessed."];
    default:
      if (p?.questions.length) {
        return [`Ask the person these ${p.questions.length} question(s) in your own conversation, then save the answers with answer_onboarding_question (proposal_id=${p.id}, expected_revision=${p.revision}).`, "Save only what the person actually said."];
      }
      return [`No open questions. Call review_onboarding with proposal_id=${p?.id ?? "<id>"} and show the person the exact draft and search scope.`];
  }
}

async function onboardingStatusResult(path: string, body?: unknown) {
  const d = onboardingStatusOut.parse(await call(cfg(), body === undefined ? "GET" : "POST", path, body));
  const p = d.proposal;
  const lines = [
    `Onboarding: ${d.status}${p ? ` (draft ${p.id}, revision ${p.revision})` : ""}${d.current_version ? `; confirmed version ${String((d.current_version as Record<string, unknown>).version ?? "?")}` : ""}.`,
    ...(p ? [`${p.facts.length} facts saved, ${p.questions.length} open questions.`] : []),
    ...(p?.facts.slice(0, 8).map((f) => `- fact ${f.section}: ${clip(typeof f.value === "string" ? f.value : JSON.stringify(f.value), 100)} (${f.basis})`) ?? []),
    ...(p?.questions.slice(0, 8).map((q) => `- question ${q.id} [${q.section}]: ${clip(q.text, 160)} (why: ${clip(q.why, 100)})`) ?? []),
    ...(p?.parse_error ? [`Parse problem: ${clip(p.parse_error, 160)}`] : []),
  ];
  return reply(lines.join("\n"), d, onboardingNext(d));
}

const attempt = async (run: () => Promise<unknown>) => {
  try { return await run(); } catch (e) { return fail(e); }
};

// ---- the registry -------------------------------------------------------------------------------------------------
export const T = {
  jobwatch_guide: defineTool({
    name: "jobwatch_guide", title: "Operating guide", group: "guide", access: "model",
    summary: "Read Jobwatch's operating guide for one topic (read-only).",
    whenToUse: "you are unsure what to do next, how an approval works, or after an error",
    whenNotToUse: "pasting at the person; use it to act and explain in your own words",
    next: "act on it, e.g. onboarding_status or jobs_overview",
    widget: "none", annotations: READ,
    inputSchema: z.strictObject({ topic: z.enum(TOPICS).default("overview") }), outputSchema: guideOut,
    handler: async ({ topic }) => {
      const g = renderGuide(topic, specs, widgetMode());
      return reply(g.text, { topic, sources: g.sources }, ["Act on this guide; start with onboarding_status or jobs_overview as it says."]);
    },
  }),

  // -- onboarding
  onboarding_status: defineTool({
    name: "onboarding_status", title: "Onboarding status", group: "onboarding", access: "model",
    summary: "Read the person's onboarding state: saved facts, open questions, confirmed version.",
    whenToUse: "first in a new conversation, or when setup is unclear",
    whenNotToUse: "asking the person anything yourself; you run the conversation",
    next: "ask the open questions, review_onboarding when none remain, discovery_status when confirmed",
    widget: "none", annotations: READ,
    inputSchema: z.strictObject({}), outputSchema: onboardingStatusOut,
    handler: () => attempt(() => onboardingStatusResult("/connector/onboarding/status")),
  }),
  start_onboarding: defineTool({
    name: "start_onboarding", title: "Start onboarding", group: "onboarding", access: "model",
    summary: "Start an onboarding draft from document IDs the person already uploaded to Jobwatch. Never confirms a profile.",
    whenToUse: "onboarding_status says not_started and you have upload_ids",
    whenNotToUse: "a draft already exists, or inventing document IDs",
    next: "onboarding_status until parsing ends, then ask the saved questions yourself",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({ upload_ids: z.array(proposalId).min(1).max(20), base_version: z.number().int().min(1).nullable().optional() }), outputSchema: onboardingStatusOut,
    handler: (input) => attempt(() => onboardingStatusResult("/connector/onboarding/start", input)),
  }),
  update_onboarding: defineTool({
    name: "update_onboarding", title: "Update onboarding draft", group: "onboarding", access: "model",
    summary: "Save facts or corrections the person stated in their unconfirmed draft (atomic; expected_revision prevents overwriting another edit). Does not confirm or start discovery.",
    whenToUse: "the person states or corrects a profile fact",
    whenNotToUse: "saving anything the person did not say; never invent facts",
    next: "onboarding_status for remaining questions, then review_onboarding",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({ proposal_id: proposalId, expected_revision: revision, edits: z.array(onboardingEdit).min(1).max(100) }), outputSchema: onboardingStatusOut,
    handler: (input) => attempt(() => onboardingStatusResult("/connector/onboarding/update", input)),
  }),
  answer_onboarding_question: defineTool({
    name: "answer_onboarding_question", title: "Answer onboarding question", group: "onboarding", access: "model",
    summary: "Save the person's answer to one saved onboarding question, using the current expected_revision. Does not confirm a profile.",
    whenToUse: "the person has answered a saved onboarding question",
    whenNotToUse: "answering for the person, or confirming the profile",
    next: "more questions via onboarding_status, or review_onboarding when none remain",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({ proposal_id: proposalId, expected_revision: revision, question_id: z.string().min(1).max(64), text: z.string().min(1).max(4000) }), outputSchema: onboardingStatusOut,
    handler: (input) => attempt(() => onboardingStatusResult("/connector/onboarding/answer", input)),
  }),
  review_onboarding: defineTool({
    name: "review_onboarding", title: "Review onboarding", group: "onboarding", access: "model",
    summary: "Read the exact current draft, search scope and limits, plus the two digests, for the person's review.",
    whenToUse: "no open questions remain and the person should confirm their profile",
    whenNotToUse: "confirming; show the review to the person and wait for their yes",
    next: "confirm_onboarding with these unchanged digests after the person's explicit yes",
    widget: "none", annotations: READ,
    inputSchema: z.strictObject({ proposal_id: proposalId }), outputSchema: onboardingReviewOut,
    handler: (input) => attempt(async () => {
      const d = onboardingReviewOut.parse(await call(cfg(), "POST", "/connector/onboarding/review", input));
      const s = d.scope;
      const summary = [
        `Draft ${d.proposal.id} revision ${d.proposal.revision}: ${d.proposal.facts.length} facts, ${d.proposal.questions.length} unanswered questions.`,
        ...d.proposal.facts.slice(0, 12).map((f) => `- ${f.section}: ${clip(typeof f.value === "string" ? f.value : JSON.stringify(f.value), 100)} (${f.basis})`),
        `Search scope: ${s.basis.join(", ") || "none"} in ${s.locations.join(", ") || "no location"}; up to ${s.daily_assessments} assessments a day; token allowance ${s.daily_token_ceiling ?? "unlimited"}.`,
        `Confirming authorises: ${d.authorises.join(", ")}. It does not authorise: ${d.does_not_authorise.join(", ")}.`,
        `proposal_digest=${d.proposal_digest} scope_digest=${d.scope_digest}`,
      ].join("\n");
      return reply(summary, d, [
        "Show the person the facts, scope, unknowns and limits and ask whether to confirm exactly this.",
        `Only after a clear yes, call confirm_onboarding with proposal_id=${d.proposal.id}, these two digests unchanged and confirmed=true. If the draft changes meanwhile, review again.`,
      ]);
    }),
  }),
  confirm_onboarding: defineTool({
    name: "confirm_onboarding", title: "Confirm onboarding", group: "onboarding", access: "model",
    summary: "Confirm the exact profile and search scope the person reviewed and approved. Both digests must match or Jobwatch refuses. Authorises discovery and assessment only, never documents, messages or submission.",
    whenToUse: "the person clearly said yes to what review_onboarding returned",
    whenNotToUse: "any consent you inferred or any changed draft",
    next: "discovery_status",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({ proposal_id: proposalId, proposal_digest: digest, scope_digest: digest, confirmed: z.literal(true) }), outputSchema: onboardingConfirmOut,
    handler: (input) => attempt(async () => {
      const d = onboardingConfirmOut.parse(await call(cfg(), "POST", "/connector/onboarding/confirm", input));
      return reply(`Profile confirmed as version ${d.version}. Discovery eligibility: ${d.discovery_enabled ? "enabled" : "disabled"}. No application submission is authorised.`, d, [
        d.discovery_enabled ? "Call discovery_status. If the person wants jobs assessed now, call start_discovery." : "Discovery is disabled; tell the person and check discovery_status for why.",
      ]);
    }),
  }),

  // -- discovery
  discovery_status: defineTool({
    name: "discovery_status", title: "Discovery status", group: "discovery", access: "model",
    summary: "Read collection counts, assessment progress today, unresolved failures with reasons and retry contexts. Failed jobs stay paused until the person asks for a retry.",
    whenToUse: "the person asks if it is working, why nothing is new, or what failed",
    whenNotToUse: "recommending jobs; collected postings are not recommendations",
    next: "jobs_overview, or start_discovery / retry_assessment only on request",
    widget: "none", annotations: READ,
    inputSchema: z.strictObject({}), outputSchema: discoveryStatusOut,
    handler: () => attempt(async () => {
      const d = await readDiscovery();
      const v = discoveryView(d);
      return reply(v.summary, d, v.next);
    }),
  }),
  start_discovery: defineTool({
    name: "start_discovery", title: "Start discovery", group: "discovery", access: "model",
    summary: "Queue one bounded assessment pass for the confirmed scope within the daily spending limits. Does not retry paused failures, draft documents or submit.",
    whenToUse: "the person wants more jobs assessed now",
    whenNotToUse: "retrying a failure (retry_assessment) or refreshing the shortlist (refresh_shortlist)",
    next: "discovery_status for the real progress; queued is not done",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({ request_id: z.string().min(1).max(100).describe("New per request; reuse only after a lost response") }), outputSchema: discoveryQueuedOut,
    handler: (input) => attempt(async () => {
      const d = discoveryQueuedOut.parse(await call(cfg(), "POST", "/connector/discovery/start", input));
      return reply(`Discovery request ${d.state} (run ${d.run_id}).`, d, ["Call discovery_status later to see the real progress; queued is not done."]);
    }),
  }),
  retry_assessment: defineTool({
    name: "retry_assessment", title: "Retry assessment", group: "discovery", access: "model",
    summary: "Retry ONE paused assessment using the current retry_context as expected_context. Refuses if the profile, posting or configuration changed.",
    whenToUse: "the person explicitly asks to retry that failed assessment",
    whenNotToUse: "retrying on your own, or raising spending limits",
    next: "discovery_status to see whether it succeeded",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({ request_id: z.string().min(1).max(100), incident_id: z.string().min(1).max(100), posting_id: posting, expected_context: digest }), outputSchema: discoveryQueuedOut,
    handler: (input) => attempt(async () => {
      const d = discoveryQueuedOut.parse(await call(cfg(), "POST", "/connector/discovery/retry", input));
      return reply(`Requested assessment retry ${d.state} (run ${d.run_id}). Other paused jobs are unchanged.`, d, ["Call discovery_status later to see whether it succeeded."]);
    }),
  }),
  get_discovery_settings: defineTool({
    name: "get_discovery_settings", title: "Discovery settings", group: "settings", access: "model",
    summary: "Read the person's daily token allowance (null means Unlimited; per-job and per-run limits still apply).",
    whenToUse: "the person asks how much it can spend",
    whenNotToUse: "changing the allowance (set_discovery_settings)",
    next: "set_discovery_settings only if the person asks to change it",
    widget: "none", annotations: READ,
    inputSchema: z.strictObject({}), outputSchema: discoverySettingsResult,
    handler: () => attempt(async () => {
      const d = await readSettings();
      const v = settingsView(d);
      return reply(v.summary, d, v.next);
    }),
  }),
  set_discovery_settings: defineTool({
    name: "set_discovery_settings", title: "Set discovery settings", group: "settings", access: "model",
    summary: "Save the daily token allowance the person asked for: a positive integer, or null for Unlimited. Keeps recorded spending, profile facts and per-run limits.",
    whenToUse: "the person explicitly asks to change the allowance",
    whenNotToUse: "changing it on your own",
    next: "get_discovery_settings to confirm",
    widget: "none", annotations: WORK,
    inputSchema: discoverySettingsOut, outputSchema: discoverySettingsResult,
    handler: (input) => attempt(async () => {
      const d = discoverySettingsOut.parse(await call(cfg(), "POST", "/connector/discovery/settings", input));
      return reply(d.daily_token_ceiling === null ? "Saved daily token allowance: Unlimited." : `Saved daily token allowance: ${d.daily_token_ceiling}.`, d, ["Tell the person it is saved; it applies to the next discovery pass."]);
    }),
  }),

  // -- shortlist (the only source of recommendations)
  refresh_shortlist: defineTool({
    name: "refresh_shortlist", title: "Refresh shortlist", group: "shortlist", access: "model",
    summary: "Rebuild the canonical shortlist from stored assessments only. No paid assessment, collection, preparation or submission.",
    whenToUse: "jobs_overview says not_built or stale, or the person asks to refresh",
    whenNotToUse: "finding new jobs (start_discovery)",
    next: "jobs_overview",
    widget: "none", annotations: { ...READ, readOnlyHint: false },
    inputSchema: z.object({}), outputSchema: overviewOut,
    handler: () => attempt(async () => {
      const d = overviewOut.parse(await call(cfg(), "POST", "/connector/shortlist/refresh", {}));
      const v = shortlistView(d, true);
      return reply(v.summary, d, v.next);
    }),
  }),
  jobs_overview: defineTool({
    name: "jobs_overview", title: "Current matches", group: "shortlist", access: "model",
    summary: "List the current canonical shortlist in rank order, evidence holds labelled. This is the only source of recommendations.",
    whenToUse: "the person asks what jobs match them or what to apply to",
    whenNotToUse: "application history, collected postings or assessment activity",
    next: "job_detail for one entry's evidence; refresh_shortlist if stale",
    widget: "none", annotations: READ,
    inputSchema: z.object({ limit: z.number().int().min(1).max(100).default(50) }), outputSchema: overviewOut,
    handler: ({ limit }) => attempt(async () => {
      const d = await readShortlist(limit);
      const v = shortlistView(d);
      return reply(v.summary, d, v.next);
    }),
  }),
  job_detail: defineTool({
    name: "job_detail", title: "Job detail", group: "shortlist", access: "model",
    summary: "Open one current shortlist entry: evidence per requirement, conditions, unresolved questions, fit, uncertainty and whether it can be prepared, with its entry_id and run_key.",
    whenToUse: "recommending a job or answering whether to apply",
    whenNotToUse: "a job not on the shortlist; assessment_detail is for explicit diagnostics only",
    next: "ask the person, then prepare_application",
    widget: "none", annotations: READ,
    inputSchema: z.object({ posting_id: posting }), outputSchema: jobOut,
    handler: ({ posting_id }) => attempt(async () => {
      const { job } = await call<{ job: unknown }>(cfg(), "GET", `/connector/jobs/${posting_id}`);
      const d = jobOut.parse(job);
      const e = d.shortlist_entry;
      if (!d.found || !e) {
        return reply(`Job ${posting_id} is not on the current shortlist (${d.shortlist_status ?? "unknown"}), so it is not recommended.`, d, [
          "Call jobs_overview for the current matches. Use assessment_detail only if the person explicitly asks why this job is missing.",
        ]);
      }
      const ev = (e.evidence as Record<string, unknown>[]).slice(0, 6).map((x) => `- ${clip(x.requirement, 80)}: ${clip(x.status, 40)}`);
      const lines = [
        `Job ${d.posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}${d.location ? ` (${d.location})` : ""}: rank ${e.rank}, ${labelText[e.label] ?? e.label}.`,
        `Fit: ${clip(e.objective_fit, 300)}`,
        `Uncertainty: ${clip(e.uncertainty, 200)}`,
        ...(e.conditions.length ? [`Conditions: ${e.conditions.slice(0, 5).map((c) => clip(c, 100)).join("; ")}`] : []),
        ...(e.unresolved.length ? [`Unresolved questions: ${e.unresolved.slice(0, 5).map((c) => clip(c, 100)).join("; ")}`] : []),
        ...(e.mandatory_requirements.length ? [`Mandatory requirements: ${e.mandatory_requirements.slice(0, 5).map((c) => clip(c, 100)).join("; ")}`] : []),
        ...(ev.length ? ["Evidence:", ...ev] : []),
        ...(e.can_prepare ? [`Preparation identity: expected_entry_id="${e.entry_id}" expected_run_key="${e.run_key}"`] : []),
        `Application: ${d.state ?? "not started"}; ${d.documents_ready ? "documents ready" : "no documents ready"}. ${e.can_prepare ? "Can be prepared after the person consents." : "Evidence hold: cannot be prepared yet."}${d.ad_url ? ` Ad: ${d.ad_url}` : ""}`,
      ];
      const next: string[] = [];
      if (d.state === "draft ready" || d.documents_ready) next.push(`If the person wants to check the application, call review_submission with posting_id=${d.posting_id}.`);
      else if (e.can_prepare) next.push(`Explain the fit with reasons and uncertainty. Only if the person explicitly confirms they want it prepared, call prepare_application with posting_id=${d.posting_id}, expected_entry_id="${e.entry_id}", expected_run_key="${e.run_key}", a new request_id and confirmed=true.`);
      else next.push("Ask the person the unresolved questions above; this job cannot be prepared until the evidence hold is resolved.");
      return reply(lines.join("\n"), d, next);
    }),
  }),
  assessment_detail: defineTool({
    name: "assessment_detail", title: "Assessment diagnostic", group: "shortlist", access: "model",
    summary: "Diagnostic lookup of one assessment, including exclusions and failures. Never a recommendation.",
    whenToUse: "the person explicitly asks why a job was assessed, excluded or failed",
    whenNotToUse: "picking or recommending jobs (jobs_overview)",
    next: "explain the reason; discovery_status for failures and retries",
    widget: "none", annotations: READ,
    inputSchema: z.object({ posting_id: posting }), outputSchema: jobOut,
    handler: ({ posting_id }) => attempt(async () => {
      const d = jobOut.parse((await call<{ job: unknown }>(cfg(), "GET", `/connector/assessments/${posting_id}`)).job);
      if (!d.found) return reply(`No assessment record for job ${posting_id}.`, d, ["Tell the person nothing was recorded for that job."]);
      return reply(`Diagnostic for job ${posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}: assessment ${assessmentLabel(d)}.${d.assessment_summary ? ` ${clip(d.assessment_summary, 300)}` : ""} Not a recommendation.`, d,
        ["Explain this as a diagnostic only. If the job is not on the shortlist it is not recommended. For failures see discovery_status."]);
    }),
  }),

  // -- applications (history and work)
  applications_overview: defineTool({
    name: "applications_overview", title: "Application history", group: "applications", access: "model",
    summary: "List application history: preparation, drafts, submissions and uncertain outcomes. Not recommendations.",
    whenToUse: "the person asks what they applied to or what needs them on an application",
    whenNotToUse: "deciding what to apply to (jobs_overview)",
    next: "task_status or application_detail for one posting",
    widget: "none", annotations: READ,
    inputSchema: z.object({ limit: z.number().int().min(1).max(100).default(50) }), outputSchema: applicationsOut,
    handler: ({ limit }) => attempt(async () => {
      const d = await readApplications(limit);
      const v = applicationsView(d);
      return reply(v.summary, d, v.next);
    }),
  }),
  application_detail: defineTool({
    name: "application_detail", title: "Application detail", group: "applications", access: "model",
    summary: "Read one application history item: state, document readiness and ad link. Says nothing about current fit.",
    whenToUse: "the person asks where their application for a job stands",
    whenNotToUse: "whether to apply (job_detail)",
    next: "task_status for progress, review_submission if a draft is ready",
    widget: "none", annotations: READ,
    inputSchema: z.object({ posting_id: posting }), outputSchema: jobOut,
    handler: ({ posting_id }) => attempt(async () => {
      const d = jobOut.parse((await call<{ job: unknown }>(cfg(), "GET", `/connector/applications/${posting_id}`)).job);
      if (!d.found) return reply(`No application history for job ${posting_id}.`, d, ["Call applications_overview to see valid posting ids."]);
      return reply(`Application for job ${posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}: ${d.state ?? "unknown"}${d.state_detail ? ` (${clip(d.state_detail, 120)})` : ""}; ${d.documents_ready ? "documents ready" : "no documents ready"}.${d.ad_url ? ` Ad: ${d.ad_url}` : ""} History only, not a recommendation.`, d,
        [d.state === "draft ready" || d.documents_ready ? `If the person wants to check it, call review_submission with posting_id=${posting_id}.` : `Call task_status with posting_id=${posting_id} for current progress.`]);
    }),
  }),
  task_status: defineTool({
    name: "task_status", title: "Task status", group: "applications", access: "model",
    summary: "Plain state of the work on one posting: queued, drafting, draft ready, awaiting browser press, executing, submitted, outcome unknown, failed, cancelled, not started.",
    whenToUse: "the person asks how a job's application is going, or to poll after preparing",
    whenNotToUse: "judging fit (job_detail)",
    next: "review_submission when it says draft ready",
    widget: "none", annotations: READ,
    inputSchema: z.object({ posting_id: posting }), outputSchema: taskOut,
    handler: ({ posting_id }) => attempt(async () => {
      const card = await call<Record<string, unknown>>(cfg(), "GET", `/connector/jobs/${posting_id}/status`);
      const d = taskFromCard(card, posting_id);
      return reply(`#${posting_id}: ${d.state}.${d.message ? " " + clip(d.message, 300) : ""}${d.reason ? ` Reason: ${clip(d.reason, 200)}.` : ""}`, d, nextForState(posting_id, d.state));
    }),
  }),
  prepare_application: defineTool({
    name: "prepare_application", title: "Prepare application", group: "applications", access: "model",
    summary: "Queue preparation (CV, letter, form fill) of the exact current eligible shortlist entry: pass the ids from job_detail, a stable request_id and confirmed=true. Authorises preparation only, never Submit. Evidence holds and changed inputs are refused.",
    whenToUse: "the person explicitly confirmed preparing this job",
    whenNotToUse: "assessing a job, or changing a draft (revise_application)",
    next: "task_status until draft ready",
    widget: "none", annotations: WORK,
    inputSchema: z.object({ posting_id: posting, expected_entry_id: z.string().min(1).max(200), expected_run_key: z.string().min(1).max(200), request_id: z.string().min(1).max(200), confirmed: z.literal(true) }), outputSchema: taskOut,
    handler: ({ posting_id, ...body }) => attempt(async () => {
      const d = taskOut.parse(await call(cfg(), "POST", `/connector/jobs/${posting_id}/prepare`, body));
      return reply(`Preparation of job ${posting_id}: ${d.state}. This authorises preparation only, never Submit.`, d, [
        `Call task_status with posting_id=${posting_id} until it says 'draft ready' (drafting takes a while; do not re-queue), then call review_submission so the person can check the form.`,
      ]);
    }),
  }),
  revise_application: defineTool({
    name: "revise_application", title: "Revise application", group: "applications", access: "model",
    summary: "Hand a requested change to an existing draft to Jobwatch's own agent. Returns an approval (summary and confirm_digest) to show the person. Never submits.",
    whenToUse: "the person wants something in the CV, letter or answers changed",
    whenNotToUse: "a first draft (prepare_application)",
    next: "show the approval, then approve_application",
    widget: "none", annotations: WORK,
    inputSchema: z.object({ posting_id: posting, changes: z.string().min(1).max(4000) }), outputSchema: taskOut,
    handler: ({ posting_id, changes }) => attempt(async () => workResult(posting_id, await call(cfg(), "POST", `/connector/jobs/${posting_id}/revise`, { changes }))),
  }),
  // Chat-callable approval. Same pending approval and binding as the app-only decide button (Python does the
  // single-use, person, expiry and checkpoint checks); on top it needs the digest the person was shown and their
  // own words. It cannot reach submit: Submit stays on the app-only submit_reviewed.
  approve_application: defineTool({
    name: "approve_application", title: "Answer an approval", group: "applications", access: "model",
    summary: "Approve or reject ONE pending approval returned by revise_application. Needs the exact confirm_digest shown and user_quote = the person's words, verbatim; anything else is refused. Cannot submit.",
    whenToUse: "the person has seen the approval summary and digest and answered",
    whenNotToUse: "inventing the quote or answering for the person",
    next: "task_status for progress",
    widget: "none", annotations: WORK,
    inputSchema: z.strictObject({
      posting_id: posting,
      interaction_id: z.string().min(1).max(100),
      decision: z.enum(["approve", "reject"]),
      confirm_digest: z.string().regex(/^[a-f0-9]{64}$/),
      user_quote: z.string().trim().min(2).max(1000).describe("The person's own words answering the approval, verbatim"),
    }), outputSchema: taskOut,
    handler: ({ posting_id, interaction_id, decision, confirm_digest, user_quote }) => attempt(async () =>
      workResult(posting_id, await call(cfg(), "POST", "/connector/approve", { posting_id, interaction_id, decision, confirm_digest, user_quote }))),
  }),
  // The review step is the person's Submit boundary. The digest goes in result _meta, which the host gives to the
  // View; the digest is useless without the app-only submit_reviewed, and Python re-checks it against the live form.
  review_submission: defineTool({
    name: "review_submission", title: "Review before submit", group: "applications", access: "model",
    summary: "Show the exact filled application form (every answer, attached CV and letter) as it would be sent. Sends nothing; you cannot submit. Opens the Submit review view when widgets are on, so call it only when the person asks to review or submit.",
    whenToUse: "the person asks to review or submit a ready draft",
    whenNotToUse: "submitting; the person presses Submit themselves",
    next: "show every answer and document, then revise_application for changes",
    widget: "review", view: "review", annotations: READ,
    inputSchema: z.object({ posting_id: posting }), outputSchema: reviewOut,
    handler: ({ posting_id }) => attempt(async () => {
      const r = await call<{ review: Record<string, unknown>; submit_digest: string | null }>(cfg(), "GET", `/connector/jobs/${posting_id}/review`);
      // shown_hash and the digest are removed from model-visible output and placed in view-only _meta.
      const { shown_hash, ...visible } = r.review as { shown_hash?: string } & Record<string, unknown>;
      const d = reviewOut.parse(visible);
      const ready = Boolean(d.ready && r.submit_digest && shown_hash);
      if (!ready) {
        return reply(`#${posting_id} has nothing to submit (${d.reason ?? "not found"}).`, d, [
          d.reason === "not_prepared" ? `Nothing is prepared for #${posting_id}. If the person wants to apply, ask, then call prepare_application.` : "Tell the person the reason. Call task_status for the current state; do not try to work around it.",
        ]);
      }
      const rows = d.answers.slice(0, 40).map((a) => `- ${clip(a.question, 90)}: ${clip(a.answer, 200)} (${a.source})`);
      const docs = d.documents.map((x) => `${x.label} (${x.file})`).join(", ") || "none";
      const summary = [
        `#${posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}: ${d.answers.length} answers and ${d.documents.length} documents ready for review.`,
        ...rows,
        ...(d.answers.length > 40 ? [`(+${d.answers.length - 40} more answers in the structured data)`] : []),
        `Documents: ${docs}`,
      ].join("\n");
      return reply(
        summary,
        d,
        [
          "Show the person every answer and document above and ask them to check it. Answers marked agent_draft were written by Jobwatch's agent and are the likeliest to need editing; point them out.",
          "Submitting is the person's own action: they press Submit in Jobwatch. You cannot submit; do not call submit_reviewed.",
          "If they want a change, call revise_application with their requested changes.",
        ],
        { submit_digest: r.submit_digest, shown_hash },
      );
    }),
  }),

  // -- the one explicit way to open the interactive dashboard
  open_dashboard: defineTool({
    name: "open_dashboard", title: "Open dashboard", group: "view", access: "model",
    summary: "Open the interactive dashboard (tabs: jobs, applications, discovery, settings) and return the same data as text. The only tool that opens a view besides the Submit review.",
    whenToUse: "the person asks to open the dashboard, widget or view",
    whenNotToUse: "answering a normal question; use the text tools instead",
    next: "answer from the text summary if no view appears; jobs_overview for details",
    widget: "on_request", view: "dashboard", annotations: READ,
    inputSchema: z.strictObject({ tab: z.enum(["jobs", "applications", "discovery", "settings"]).default("jobs") }), outputSchema: dashboardOut,
    handler: ({ tab }, ctx) => attempt(async () => {
      let supports = false;
      try { supports = ctx?.client?.supportsViews?.() === true; } catch { /* unknown means text-only */ }
      const host_views = supports ? ("declared" as const) : ("not_declared" as const);
      let summary: string, next: string[], data: Record<string, unknown>;
      if (tab === "jobs") { const d = await readShortlist(100); ({ summary, next } = shortlistView(d)); data = { jobs: d }; }
      else if (tab === "applications") { const d = await readApplications(100); ({ summary, next } = applicationsView(d)); data = { applications: d }; }
      else if (tab === "discovery") { const d = await readDiscovery(); ({ summary, next } = discoveryView(d)); data = { settings: await readSettings() }; }
      else { const d = await readSettings(); ({ summary, next } = settingsView(d)); data = { settings: d }; }
      const hint = supports
        ? "The dashboard is open for the person; add only a brief note and do not repeat everything it shows."
        : "This host did not declare view support. If no view appeared, present the summary above as text; that fully answers the request.";
      return reply(`Dashboard (${tab}).\n${summary}`, { tab, host_views, ...data }, [hint, ...next]);
    }),
  }),

  // -- app-only buttons: hidden from the model
  decide: defineTool({
    name: "decide", title: "Approve or reject (button)", group: "applications", access: "app",
    summary: "View button only. Approve or reject one pending Jobwatch approval using its binding; the model uses approve_application instead.",
    whenToUse: "never by the model", whenNotToUse: "any model call", next: "approve_application",
    widget: "none", annotations: WORK,
    inputSchema: z.object({ posting_id: posting, interaction_id: z.string().max(100), decision: z.enum(["approve", "reject"]), binding: z.string().max(200) }), outputSchema: taskOut,
    handler: ({ posting_id, interaction_id, decision, binding }) => attempt(async () => workResult(posting_id, await call(cfg(), "POST", "/connector/decide", { interaction_id, decision, binding }))),
  }),
  submit_reviewed: defineTool({
    name: "submit_reviewed", title: "Submit (button)", group: "applications", access: "app",
    summary: "View Submit button only. Sends the reviewed application to the employer if confirm_digest and shown_hash match the reviewed form.",
    whenToUse: "never by the model", whenNotToUse: "any model call", next: "task_status",
    widget: "none",
    // Sends the application to the employer: destructive and open-world.
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true, idempotentHint: false },
    inputSchema: z.object({ posting_id: posting, confirm_digest: z.string().min(1).max(200), shown_hash: z.string().min(1).max(200) }), outputSchema: submitOut,
    handler: ({ posting_id, confirm_digest, shown_hash }) => attempt(async () => {
      const q = await call<{ status?: unknown }>(cfg(), "POST", `/connector/jobs/${posting_id}/submit`, { confirm_digest, shown_hash });
      const d = { posting_id, status: String(q.status ?? "unknown") };
      return reply(`Submit ${d.status} for job ${posting_id}.`, d, [`Call task_status with posting_id=${posting_id} to follow it. Do not retry.`]);
    }),
  }),
};

/** All specs, in registration order. */
export const specs: AnySpec[] = Object.values(T);
