import { timingSafeEqual } from "node:crypto";
import { MCPServer } from "mcp-use";
import { OAuthError, OAuthErrorCode, oauthCustomProvider, type OAuthMetadata } from "mcp-use/oauth";
import { z } from "zod";
import { backendConfig, call, BackendError } from "./src/backend.js";
import {
  jobOut,
  overviewOut,
  reviewOut,
  submitOut,
  taskOut,
  type TaskOut,
} from "./src/schemas.js";

// ---- auth: a bearer token is required. There is no unauthenticated mode. -------------------------------------
const mcpToken = process.env.JOBWATCH_MCP_TOKEN ?? "";
if (mcpToken.length < 32) throw new Error("JOBWATCH_MCP_TOKEN (32+ chars) is required");
const cfg = backendConfig();

const same = (a: string, b: string) => {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

const oauth = oauthCustomProvider<{ id: string }, (resource: URL) => OAuthMetadata>({
  // Static bearer only. The OAuth 2.1 authorization flow (consent page) stays in the Python service;
  // the metadata below only names this origin so the resource-server gate can mount.
  createTokenVerifier: (resource) => ({
    async verifyAccessToken(token: string) {
      if (!same(token, mcpToken)) {
        throw new OAuthError(OAuthErrorCode.InvalidToken, "invalid token");
      }
      return {
        token,
        clientId: "jobwatch",
        scopes: ["jobwatch"],
        expiresAt: Math.floor(Date.now() / 1000) + 3600,
        resource,
      };
    },
  }),
  oauthMetadata: (resource: URL) => ({
    issuer: resource.origin,
    authorization_endpoint: `${resource.origin}/authorize`,
    token_endpoint: `${resource.origin}/token`,
    response_types_supported: ["code"],
  }),
  requiredScopes: ["jobwatch"],
  mapAuthInfo: (info) => ({
    user: { id: info.clientId },
    payload: {},
    permissions: info.scopes,
  }),
});

const server = new MCPServer({
  name: "jobwatch",
  title: "Jobwatch",
  version: "2.0.0",
  description:
    "Your job applications: what needs you, job details, task status, and a review step before anything is sent.",
  oauth,
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
      const { job } = (await call<{ job: unknown }>(cfg, "GET", `/connector/jobs/${posting_id}`));
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
      "Open the review step for one job: shows what is about to be sent and offers the Submit button. Does not send anything.",
    inputSchema: z.object({ posting_id: posting }),
    outputSchema: reviewOut,
    annotations: READ,
    view: { name: "review" },
  },
  async ({ posting_id }) => {
    try {
      const r = await call<{ job: Record<string, unknown>; submit_digest: string | null }>(cfg, "GET", `/connector/jobs/${posting_id}`);
      const j = jobOut.parse(r.job);
      const ready = Boolean(j.found && j.can_submit && r.submit_digest);
      const d = reviewOut.parse({
        posting_id,
        found: j.found,
        ready,
        employer: j.employer,
        title: j.title,
        state: j.state,
        draft_version: j.draft_version,
        ad_url: j.ad_url,
      });
      return {
        content: text(ready ? `#${posting_id} is ready for review. The person presses Submit in the view; do not call submit_reviewed.` : `#${posting_id} has no reviewed application to submit (state: ${j.state ?? "unknown"}).`),
        structuredContent: d,
        ...(ready ? { _meta: { submit_digest: r.submit_digest } } : {}),
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
    inputSchema: z.object({ posting_id: posting, confirm_digest: z.string().min(1).max(200) }),
    outputSchema: submitOut,
    // Sends the application to the employer: destructive and open-world.
    annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true, idempotentHint: false },
    visibility: "app",
  },
  async ({ posting_id, confirm_digest }) => {
    try {
      const q = await call<{ status?: unknown }>(cfg, "POST", `/connector/jobs/${posting_id}/submit`, { confirm_digest });
      const d = { posting_id, status: String(q.status ?? "unknown") };
      return { content: text(`Submit ${d.status} for job ${posting_id}.`), structuredContent: d };
    } catch (e) {
      return fail(e);
    }
  },
);

export default server;
