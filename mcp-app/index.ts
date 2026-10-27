import { MCPServer } from "mcp-use";
import { z } from "zod";
import { backendConfig, call, BackendError } from "./src/backend.js";
import {
  onboardingStatusOut,
  onboardingReviewOut,
  onboardingConfirmOut,
  onboardingEdit,
  discoveryStatusOut,
  discoveryQueuedOut,
  discoverySettingsOut,
  jobOut,
  overviewOut,
  reviewOut,
  submitOut,
  taskOut,
  type TaskOut,
} from "./src/schemas.js";

const cfg = backendConfig();
const publicHost = new URL(process.env.JOBWATCH_MCP_PUBLIC_URL ?? "").hostname;

const server = new MCPServer({
  name: "jobwatch",
  title: "Jobwatch",
  version: "2.0.0",
  description:
    "Your job applications: what needs you, job details, task status, and a review step before anything is sent.",
  allowedHosts: [publicHost],
});

const READ = { readOnlyHint: true, destructiveHint: false, openWorldHint: false, idempotentHint: true };
const WORK = { readOnlyHint: false, destructiveHint: false, openWorldHint: false, idempotentHint: false };
const posting = z.number().int().min(1).describe("Jobwatch posting id");

const text = (t: string) => [{ type: "text" as const, text: t }];
const fail = (e: unknown) => ({
  isError: true as const,
  content: text(e instanceof BackendError ? `Jobwatch refused: ${e.code}` : "Jobwatch is not reachable right now."),
});

const countsText = (c: z.infer<typeof overviewOut>["counts"]) =>
  ([["needs_you", "need you"], ["needs_info", "need info"], ["outcome_unknown", "outcome unknown"], ["submitted", "submitted"]] as const)
    .filter(([k]) => c[k])
    .map(([k, l]) => `${c[k]} ${l}`)
    .join(" · ") || "Nothing needs you";

// ---- read tools -----------------------------------------------------------------------------------------------
export const jobsOverview = server.tool(
  {
    name: "jobs_overview",
    description:
      "List the person's jobs with activity (newest first), a plain state for each, and counts of what needs them. 'draft ready' is never 'submitted'.",
    inputSchema: z.object({ limit: z.number().int().min(1).max(100).default(50) }),
    outputSchema: overviewOut,
    annotations: READ,
    view: { name: "jobs-overview" },
  },
  async ({ limit }) => {
    try {
      const d = overviewOut.parse(await call(cfg, "GET", `/connector/overview?limit=${limit}`));
      const lines = d.jobs.slice(0, 10).map((j) => `#${j.posting_id} ${j.employer ?? "?"} - ${j.title ?? "?"}: ${j.state}`);
      return { content: text([`${countsText(d.counts)}. ${d.jobs.length} jobs with activity.`, ...lines].join("\n")), structuredContent: d };
    } catch (e) {
      return fail(e);
    }
  },
);

export const jobDetail = server.tool(
  {
    name: "job_detail",
    description: "Employer, title, score, why it fits, state, whether documents are ready, and the ad link for one job.",
    inputSchema: z.object({ posting_id: posting }),
    outputSchema: jobOut,
    annotations: READ,
    view: { name: "job-detail" },
  },
  async ({ posting_id }) => {
    try {
      const { job } = await call<{ job: unknown }>(cfg, "GET", `/connector/jobs/${posting_id}`);
      const d = jobOut.parse(job);
      const t = d.found
        ? `#${d.posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}${d.score != null ? `, score ${d.score}` : ""}. State: ${d.state}; ${d.documents_ready ? "documents ready" : "no documents ready"}.`
        : `No job ${posting_id} found.`;
      return { content: text(t), structuredContent: d };
    } catch (e) {
      return fail(e);
    }
  },
);

function taskFromCard(card: Record<string, unknown>, posting_id: number): TaskOut {
  const submit = (card.submit ?? {}) as Record<string, unknown>;
  return {
    posting_id,
    state: String(card.state ?? "not started"),
    ...(typeof card.message === "string" && card.message ? { message: card.message } : {}),
    ...(typeof submit.reason === "string" && submit.reason ? { reason: submit.reason } : {}),
  };
}

export const taskStatus = server.tool(
  {
    name: "task_status",
    description:
      "Plain state of the work on a posting: queued, drafting, draft ready, awaiting browser press, executing, submitted, outcome unknown, failed, cancelled, not started.",
    inputSchema: z.object({ posting_id: posting }),
    outputSchema: taskOut,
    annotations: READ,
    view: { name: "task-status" },
  },
  async ({ posting_id }) => {
    try {
      const card = await call<Record<string, unknown>>(cfg, "GET", `/connector/jobs/${posting_id}/status`);
      const d = taskFromCard(card, posting_id);
      return { content: text(`#${posting_id}: ${d.state}.${d.message ? " " + d.message : ""}`), structuredContent: d };
    } catch (e) {
      return fail(e);
    }
  },
);

// ---- the review step: the only place the submit digest leaves Python ----------------------------------------
// The digest goes in result _meta, which the host gives to the View. Hosts may still pass _meta to the model;
// that residual risk is documented in mcp-app/README.md. The digest is useless without the app-only
// submit_reviewed tool, and the Python side re-checks it against the live reviewed form.
export const reviewSubmission = server.tool(
  {
    name: "review_submission",
    description:
      "Open the review step for one job: shows the exact filled form (every answer, attached CV and letter) that would be sent, with a Submit button. Does not send anything.",
    inputSchema: z.object({ posting_id: posting }),
    outputSchema: reviewOut,
    annotations: READ,
    view: { name: "review" },
  },
  async ({ posting_id }) => {
    try {
      const r = await call<{ review: Record<string, unknown>; submit_digest: string | null }>(cfg, "GET", `/connector/jobs/${posting_id}/review`);
      // shown_hash and the digest are removed from model-visible output and placed in view-only _meta.
      const { shown_hash, ...visible } = r.review as { shown_hash?: string } & Record<string, unknown>;
      const d = reviewOut.parse(visible);
      const ready = Boolean(d.ready && r.submit_digest && shown_hash);
      const t = ready
        ? `#${posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}: ${d.answers.length} answers and ${d.documents.length} documents ready for review. The person presses Submit in the view; do not call submit_reviewed.`
        : `#${posting_id} has nothing to submit (${d.reason ?? "not found"}).`;
      return {
        content: text(t),
        structuredContent: d,
        ...(ready ? { _meta: { submit_digest: r.submit_digest, shown_hash } } : {}),
      };
    } catch (e) {
      return fail(e);
    }
  },
);

// ---- work tools (hand heavy work to Jobwatch's own agent; never submit) --------------------------------------
function workResult(posting_id: number, res: { data: Record<string, unknown>; meta: Record<string, unknown> }) {
  const d = res.data;
  const awaiting = d.status === "awaiting_approval";
  const out: TaskOut = {
    posting_id,
    state: awaiting ? "awaiting approval" : d.decision === "reject" ? "rejected" : "complete",
    ...(awaiting
      ? { approval: { interaction_id: String(d.interaction_id), operation: String(d.operation), summary: String(d.summary) } }
      : { answer: String(d.answer ?? "").slice(0, 1500) }),
    ...(Array.isArray(d.declined) ? { declined: d.declined.map(String) } : {}),
    ...(d.decision === "approve" || d.decision === "reject" ? { decision: d.decision } : {}),
  };
  const meta = typeof res.meta.binding === "string" ? { _meta: { binding: res.meta.binding } } : {};
  return {
    content: text(awaiting ? `${out.approval!.summary} Waiting for the person to press Approve or Reject in the view; do not call decide.` : out.answer || "Done."),
    structuredContent: out,
    ...meta,
  };
}

export const prepareApplication = server.tool(
  {
    name: "prepare_application",
    description:
      "Hand the heavy work of preparing an application (cover letter, CV, form fill) to Jobwatch's own agent. Returns status and any approval it needs; the person approves in the view. Never submits.",
    inputSchema: z.object({ posting_id: posting, instructions: z.string().max(4000).default("") }),
    outputSchema: taskOut,
    annotations: WORK,
    view: { name: "task-prepare" },
  },
  async ({ posting_id, instructions }) => {
    try {
      return workResult(posting_id, await call(cfg, "POST", `/connector/jobs/${posting_id}/prepare`, { instructions }));
    } catch (e) {
      return fail(e);
    }
  },
);

export const reviseApplication = server.tool(
  {
    name: "revise_application",
    description:
      "Hand a requested revision of an existing application draft to Jobwatch's own agent. Returns status and any approval it needs; the person approves in the view. Never submits.",
    inputSchema: z.object({ posting_id: posting, changes: z.string().min(1).max(4000) }),
    outputSchema: taskOut,
    annotations: WORK,
    view: { name: "task-revise" },
  },
  async ({ posting_id, changes }) => {
    try {
      return workResult(posting_id, await call(cfg, "POST", `/connector/jobs/${posting_id}/revise`, { changes }));
    } catch (e) {
      return fail(e);
    }
  },
);

// ---- app-only buttons: hidden from the model ------------------------------------------------------------------
export const decide = server.tool(
  {
    name: "decide",
    description: "View button only. Approve or reject one pending Jobwatch approval. The model must not call this.",
    inputSchema: z.object({
      posting_id: posting,
      interaction_id: z.string().max(100),
      decision: z.enum(["approve", "reject"]),
      binding: z.string().max(200),
    }),
    outputSchema: taskOut,
    annotations: WORK,
    visibility: "app",
  },
  async ({ posting_id, interaction_id, decision, binding }) => {
    try {
      return workResult(posting_id, await call(cfg, "POST", "/connector/decide", { interaction_id, decision, binding }));
    } catch (e) {
      return fail(e);
    }
  },
);

export const submitReviewed = server.tool(
  {
    name: "submit_reviewed",
    description:
      "View Submit button only. Sends the reviewed application to the employer if confirm_digest matches the reviewed form. The model must not call this.",
    inputSchema: z.object({ posting_id: posting, confirm_digest: z.string().min(1).max(200), shown_hash: z.string().min(1).max(200) }),
    outputSchema: submitOut,
    // Sends the application to the employer: destructive and open-world.
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true, idempotentHint: false },
    visibility: "app",
  },
  async ({ posting_id, confirm_digest, shown_hash }) => {
    try {
      const q = await call<{ status?: unknown }>(cfg, "POST", `/connector/jobs/${posting_id}/submit`, { confirm_digest, shown_hash });
      const d = { posting_id, status: String(q.status ?? "unknown") };
      return { content: text(`Submit ${d.status} for job ${posting_id}.`), structuredContent: d };
    } catch (e) {
      return fail(e);
    }
  },
);

const proposalId = z.string().regex(/^[a-f0-9]{16}$/);
const revision = z.number().int().min(1);
const digest = z.string().regex(/^[a-f0-9]{64}$/);

async function onboardingStatusResult(path: string, body?: unknown) {
  const d = onboardingStatusOut.parse(await call(cfg, body === undefined ? "GET" : "POST", path, body));
  return { content: text(`Onboarding: ${d.status}. ${d.proposal?.questions.length ?? 0} saved questions. Use the structured facts and questions to coordinate onboarding with the person.`), structuredContent: d };
}

export const onboardingStatus = server.tool({
  name: "onboarding_status",
  description: "Read the person's saved onboarding draft, all facts, all outstanding questions and confirmed version. Coordinate the conversation yourself; this calls no chatbot.",
  inputSchema: z.strictObject({}), outputSchema: onboardingStatusOut, annotations: READ,
}, async () => {
  try { return await onboardingStatusResult("/connector/onboarding/status"); } catch (e) { return fail(e); }
});

export const startOnboarding = server.tool({
  name: "start_onboarding",
  description: "Start a draft from the person's existing uploaded document IDs. Document parsing runs in Jobwatch; collect missing answers in your own conversation. Never confirms a profile.",
  inputSchema: z.strictObject({ upload_ids: z.array(proposalId).min(1).max(20), base_version: z.number().int().min(1).nullable().optional() }),
  outputSchema: onboardingStatusOut, annotations: WORK,
}, async (input) => {
  try { return await onboardingStatusResult("/connector/onboarding/start", input); } catch (e) { return fail(e); }
});

export const updateOnboarding = server.tool({
  name: "update_onboarding",
  description: "Atomically save the person's stated facts or corrections in their unconfirmed draft. Use only answers the person supplied; never invent facts. expected_revision prevents overwriting another edit. Does not confirm or start discovery.",
  inputSchema: z.strictObject({ proposal_id: proposalId, expected_revision: revision, edits: z.array(onboardingEdit).min(1).max(100) }),
  outputSchema: onboardingStatusOut, annotations: WORK,
}, async (input) => {
  try { return await onboardingStatusResult("/connector/onboarding/update", input); } catch (e) { return fail(e); }
});

export const answerOnboarding = server.tool({
  name: "answer_onboarding_question",
  description: "Save the person's answer to one saved onboarding question. Gather all needed answers together in your conversation, then save them with current revisions. Never answer for the person or confirm a profile.",
  inputSchema: z.strictObject({ proposal_id: proposalId, expected_revision: revision, question_id: z.string().min(1).max(64), text: z.string().min(1).max(4000) }),
  outputSchema: onboardingStatusOut, annotations: WORK,
}, async (input) => {
  try { return await onboardingStatusResult("/connector/onboarding/answer", input); } catch (e) { return fail(e); }
});

export const reviewOnboarding = server.tool({
  name: "review_onboarding",
  description: "Read the exact current draft, search scope and limits for the person's review. Show these in your conversation, collect their confirmation, then call confirm_onboarding with these unchanged digests. No separate chat or widget approval is required.",
  inputSchema: z.strictObject({ proposal_id: proposalId }), outputSchema: onboardingReviewOut, annotations: READ,
}, async (input) => {
  try {
    const d = onboardingReviewOut.parse(await call(cfg, "POST", "/connector/onboarding/review", input));
    return { content: text("Show the returned profile facts, search scope, unknowns and limits to the person. Confirmation authorises discovery and assessment only. After their explicit confirmation, call confirm_onboarding with these exact digests."), structuredContent: d };
  } catch (e) { return fail(e); }
});

export const confirmOnboarding = server.tool({
  name: "confirm_onboarding",
  description: "Confirm the exact profile and search scope the person reviewed and explicitly approved in this conversation. The coordinating assistant handles their consent; call only after it is given. Both digests must match the latest review or Jobwatch refuses. Authorises discovery and assessment only; never documents, employer messages or application submission.",
  inputSchema: z.strictObject({ proposal_id: proposalId, proposal_digest: digest, scope_digest: digest, confirmed: z.literal(true) }),
  outputSchema: onboardingConfirmOut, annotations: WORK,
}, async (input) => {
  try {
    const d = onboardingConfirmOut.parse(await call(cfg, "POST", "/connector/onboarding/confirm", input));
    return { content: text(`Profile confirmed as version ${d.version}. Discovery eligibility: ${d.discovery_enabled ? "enabled" : "disabled"}. No application submission is authorised.`), structuredContent: d };
  } catch (e) { return fail(e); }
});

export const discoveryStatus = server.tool({
  name: "discovery_status",
  description: "Read collection counts, actual assessment progress, unresolved failures, Hermes handoff state and retry contexts. Failed jobs stay paused until an explicit retry request. Collected postings are not recommendations.",
  inputSchema: z.strictObject({}), outputSchema: discoveryStatusOut, annotations: READ,
}, async () => {
  try {
    const d = discoveryStatusOut.parse(await call(cfg, "GET", "/connector/discovery/status"));
    return { content: text(`${d.postings} postings collected; ${d.assessments_today} assessed today; ${d.incidents.length} unresolved incidents. Inspect structured reasons and notification states.`), structuredContent: d };
  } catch (e) { return fail(e); }
});

export const startDiscovery = server.tool({
  name: "start_discovery",
  description: "Queue one bounded assessment pass using the person's confirmed scope and existing daily spending limits. Does not retry paused failures, draft documents or submit applications. Reuse request_id after a lost response; discovery_status reports actual progress.",
  inputSchema: z.strictObject({ request_id: z.string().min(1).max(100) }),
  outputSchema: discoveryQueuedOut, annotations: WORK,
}, async (input) => {
  try {
    const d = discoveryQueuedOut.parse(await call(cfg, "POST", "/connector/discovery/start", input));
    return { content: text(`Discovery request ${d.state}. Read discovery_status for its outcome.`), structuredContent: d };
  } catch (e) { return fail(e); }
});

export const retryAssessment = server.tool({
  name: "retry_assessment",
  description: "Only after the person explicitly requests it, retry the selected paused assessment using the current retry_context from discovery_status. Refuses changed profile, posting or configuration. Does not retry other failures or increase spending limits. Reuse request_id after a lost response.",
  inputSchema: z.strictObject({ request_id: z.string().min(1).max(100), incident_id: z.string().min(1).max(100),
    posting_id: posting, expected_context: digest }),
  outputSchema: discoveryQueuedOut, annotations: WORK,
}, async (input) => {
  try {
    const d = discoveryQueuedOut.parse(await call(cfg, "POST", "/connector/discovery/retry", input));
    return { content: text(`Requested assessment retry ${d.state}. Other paused jobs are unchanged.`), structuredContent: d };
  } catch (e) { return fail(e); }
});

export const getDiscoverySettings = server.tool({
  name: "get_discovery_settings",
  description: "Read the person's effective daily token allowance. A null daily_token_ceiling means Unlimited. Individual job and run limits still apply.",
  inputSchema: z.strictObject({}), outputSchema: discoverySettingsOut, annotations: READ,
  view: { name: "settings" },
}, async () => {
  try {
    const d = discoverySettingsOut.parse(await call(cfg, "GET", "/connector/discovery/settings"));
    return { content: text(d.daily_token_ceiling === null ? "Daily token allowance: Unlimited." : `Daily token allowance: ${d.daily_token_ceiling}.`), structuredContent: d };
  } catch (e) { return fail(e); }
});

export const setDiscoverySettings = server.tool({
  name: "set_discovery_settings",
  description: "Save the person's explicitly requested daily token allowance in their own configuration. Set daily_token_ceiling to null for Unlimited, or a positive integer for a limit. Keeps recorded spending, profile facts, first-failure pauses and individual run limits.",
  inputSchema: discoverySettingsOut, outputSchema: discoverySettingsOut, annotations: WORK,
}, async (input) => {
  try {
    const d = discoverySettingsOut.parse(await call(cfg, "POST", "/connector/discovery/settings", input));
    return { content: text(d.daily_token_ceiling === null ? "Saved daily token allowance: Unlimited." : `Saved daily token allowance: ${d.daily_token_ceiling}.`), structuredContent: d };
  } catch (e) { return fail(e); }
});

export default server;
