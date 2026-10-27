import { MCPServer } from "mcp-use";
import { z } from "zod";
import { backendConfig, call, BackendError } from "./src/backend.js";
import { INSTRUCTIONS, TOPICS, SKILLS, GUIDE_NEXT, guide, skillText } from "./src/guidance.js";
import {
  onboardingStatusOut,
  onboardingReviewOut,
  onboardingConfirmOut,
  onboardingEdit,
  discoveryStatusOut,
  discoveryQueuedOut,
  discoverySettingsOut,
  discoverySettingsResult,
  guideOut,
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
  version: "2.1.0",
  description:
    "Your job applications: what needs you, job details, task status, and a review step before anything is sent.",
  instructions: INSTRUCTIONS,
  allowedHosts: [publicHost],
});

const READ = { readOnlyHint: true, destructiveHint: false, openWorldHint: false, idempotentHint: true };
const WORK = { readOnlyHint: false, destructiveHint: false, openWorldHint: false, idempotentHint: false };
const posting = z.number().int().min(1).describe("Jobwatch posting id");

const text = (t: string) => [{ type: "text" as const, text: t }];
const clip = (v: unknown, n = 160) => {
  const t = String(v ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

// Plain-English hints for refusals, so the host explains them instead of retrying.
const ERROR_HINT: Record<string, string> = {
  approval_not_found: "That approval has expired, was already answered, or is not yours. Ask the person whether to prepare it again.",
  approval_digest_mismatch: "The digest was not the one shown. The approval is still pending: show the person its card again and use its exact confirm_digest.",
  review_changed: "The form changed after review. Call review_submission again and have the person look at it.",
  submit_digest_mismatch: "The form changed after review. Call review_submission again and have the person look at it.",
  invalid_request: "The request was not valid. Check the arguments and the person's words.",
};
const fail = (e: unknown) => {
  if (!(e instanceof BackendError)) {
    return { isError: true as const, content: text("Jobwatch is not reachable right now. Tell the person; do not retry in a loop. If other Jobwatch tools are missing from your list, ask them to start a new thread.") };
  }
  const hint = ERROR_HINT[e.code];
  return { isError: true as const, content: text(`Jobwatch refused: ${e.code}${hint ? `. ${hint}` : ""}`) };
};

// One shape for every tool result: a compact human summary (also read by hosts without views), the structured data,
// and plain sentences naming the next step. The summary is never a JSON dump.
function reply<T extends object>(summary: string, data: T, next: string[], meta?: Record<string, unknown>) {
  return {
    content: text(next.length ? `${summary}\nNext actions:\n${next.map((n) => `- ${n}`).join("\n")}` : summary),
    structuredContent: { ...data, next_actions: next },
    ...(meta ? { _meta: meta } : {}),
  };
}

const countsText = (c: z.infer<typeof overviewOut>["counts"]) =>
  ([["needs_you", "need you"], ["needs_info", "need info"], ["outcome_unknown", "outcome unknown"], ["submitted", "submitted"]] as const)
    .filter(([k]) => c[k])
    .map(([k, l]) => `${c[k]} ${l}`)
    .join(" · ") || "No application actions pending";

const assessmentLabel = (j: { assessment_state?: string | null; assessment_reason?: string | null }) =>
  j.assessment_state ? `${j.assessment_state === "current" ? "assessed" : j.assessment_state}${j.assessment_reason ? ` (${j.assessment_reason})` : ""}` : "no assessment recorded";

// ---- guidance: the tool and the skill resources ---------------------------------------------------------------
export const jobwatchGuide = server.tool(
  {
    name: "jobwatch_guide",
    description:
      "Read Jobwatch's operating guide for one topic: overview, onboarding, discovery, assess, prepare, submit or troubleshooting. Use when unsure what to do next, how an approval works, or after an error. Read-only; changes nothing. Do not paste the guide at the person: use it to act and to explain in your own words.",
    inputSchema: z.strictObject({ topic: z.enum(TOPICS).default("overview") }),
    outputSchema: guideOut,
    annotations: READ,
  },
  async ({ topic }) => {
    const g = guide(topic);
    return reply(g.text, { topic, sources: g.sources }, GUIDE_NEXT[topic]);
  },
);

for (const name of Object.keys(SKILLS)) {
  server.resource(
    {
      name: `skill-${name}`,
      uri: `skill://jobwatch/${name}/SKILL.md`,
      title: `Jobwatch skill: ${name}`,
      description: SKILLS[name],
      mimeType: "text/markdown",
    },
    async (uri) => ({ contents: [{ uri: uri.href, mimeType: "text/markdown", text: skillText(name).text }] }),
  );
}

// ---- read tools -----------------------------------------------------------------------------------------------
export const jobsOverview = server.tool(
  {
    name: "jobs_overview",
    description:
      "List jobs with activity: assessment state and, separately, application progress. Use for 'what needs me / what is going on'. Do NOT use it to recommend a job: assessed or queued is not a recommendation, and 'draft ready' is never 'submitted'. Next: job_detail for the reasons on one job. The view is optional; without it, present the text summary as a short table.",
    inputSchema: z.object({ limit: z.number().int().min(1).max(100).default(50) }),
    outputSchema: overviewOut,
    annotations: READ,
    view: { name: "jobs-overview" },
  },
  async ({ limit }) => {
    try {
      const d = overviewOut.parse(await call(cfg, "GET", `/connector/overview?limit=${limit}`));
      const lines = d.jobs.slice(0, 10).map((j) => `#${j.posting_id} ${j.employer ?? "?"} - ${j.title ?? "?"} | ${j.score != null ? `score ${j.score}` : "no score"} | assessment: ${assessmentLabel(j)} | application: ${j.state}`);
      const more = d.jobs.length > 10 ? [`(+${d.jobs.length - 10} more in the structured data)`] : [];
      const summary = [`${countsText(d.counts)}. ${d.jobs.length} jobs with activity.`, ...lines, ...more, "Assessment activity is not a recommendation."].join("\n");
      const next: string[] = [];
      if (d.jobs.length) next.push(`Call job_detail with posting_id=${d.jobs[0].posting_id} (or the job the person names) to get the reasons before recommending anything.`);
      else next.push("Call discovery_status to see whether jobs are being collected and assessed.");
      if (d.jobs.some((j) => j.state === "draft ready")) next.push("For a job whose application is 'draft ready', offer review_submission so the person can check the exact form.");
      if (d.counts.outcome_unknown) next.push("Tell the person which jobs have an unknown outcome; do not retry them.");
      return reply(summary, d, next);
    } catch (e) {
      return fail(e);
    }
  },
);

export const jobDetail = server.tool(
  {
    name: "job_detail",
    description:
      "Read one job: assessment result, score, why it fits, pros and cons, plus separate application state and document readiness. Use before recommending a job or answering 'should I apply'. Do NOT use it to start work. 'Application not started' does not mean not assessed. Next: ask the person whether to prepare it (prepare_application) or review_submission if a draft is ready.",
    inputSchema: z.object({ posting_id: posting }),
    outputSchema: jobOut,
    annotations: READ,
    view: { name: "job-detail" },
  },
  async ({ posting_id }) => {
    try {
      const { job } = await call<{ job: unknown }>(cfg, "GET", `/connector/jobs/${posting_id}`);
      const d = jobOut.parse(job);
      if (!d.found) return reply(`No job ${posting_id} found.`, d, ["Call jobs_overview to see valid posting ids."]);
      const lines = [
        `#${d.posting_id} ${d.employer ?? "?"} - ${d.title ?? "?"}${d.location ? ` (${d.location})` : ""}${d.score != null ? `, score ${d.score}` : ", no score"}.`,
        d.assessment_state ? `Assessment: ${assessmentLabel(d)}.` : "Assessment: none recorded, so any fit is unknown.",
        ...(d.assessment_summary ? [`Summary: ${clip(d.assessment_summary, 300)}`] : []),
        ...(d.why_it_fits ? [`Why it fits: ${clip(d.why_it_fits, 300)}`] : []),
        ...(d.pros?.length ? [`Pros: ${d.pros.slice(0, 4).map((p) => clip(p, 100)).join("; ")}`] : []),
        ...(d.cons?.length ? [`Cons: ${d.cons.slice(0, 4).map((p) => clip(p, 100)).join("; ")}`] : []),
        `Application: ${d.state}; ${d.documents_ready ? "documents ready" : "no documents ready"}.${d.ad_url ? ` Ad: ${d.ad_url}` : ""}`,
      ];
      const next: string[] = [];
      if (d.state === "draft ready" || d.documents_ready) next.push(`If the person wants to check the application, call review_submission with posting_id=${d.posting_id}.`);
      else next.push(`Explain the fit with reasons and uncertainty. Only if the person says they want to apply, call prepare_application with posting_id=${d.posting_id}.`);
      return reply(lines.join("\n"), d, next);
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
      return ["The reviewed form is waiting for the person's own Submit press. Tell them to press Submit in Jobwatch's review view or app; you cannot."];
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

export const taskStatus = server.tool(
  {
    name: "task_status",
    description:
      "Plain state of the work on one posting: queued, drafting, draft ready, awaiting browser press, executing, submitted, outcome unknown, failed, cancelled, not started. Use to answer 'how is job N going' or to poll after prepare_application. Do NOT use it to judge fit (job_detail). Next depends on the state; see next_actions.",
    inputSchema: z.object({ posting_id: posting }),
    outputSchema: taskOut,
    annotations: READ,
    view: { name: "task-status" },
  },
  async ({ posting_id }) => {
    try {
      const card = await call<Record<string, unknown>>(cfg, "GET", `/connector/jobs/${posting_id}/status`);
      const d = taskFromCard(card, posting_id);
      return reply(`#${posting_id}: ${d.state}.${d.message ? " " + clip(d.message, 300) : ""}${d.reason ? ` Reason: ${clip(d.reason, 200)}.` : ""}`, d, nextForState(posting_id, d.state));
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
      "Show the exact filled application form for one job (every answer, attached CV and letter) as it would be sent. Use after the draft is ready, so the person can check it. Sends nothing, and you cannot submit: the person presses Submit themselves in Jobwatch's review view. Do NOT call submit_reviewed or decide. If not ready, report the reason.",
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
          "Submitting is the person's own action: they press Submit in Jobwatch's review view or app. You cannot submit; do not call submit_reviewed.",
          "If they want a change, call revise_application with their requested changes.",
        ],
        { submit_digest: r.submit_digest, shown_hash },
      );
    } catch (e) {
      return fail(e);
    }
  },
);

// ---- work tools (hand heavy work to Jobwatch's own agent; never submit) --------------------------------------
function workResult(posting_id: number, res: { data: Record<string, unknown>; meta: Record<string, unknown> }) {
  const d = res.data;
  const awaiting = d.status === "awaiting_approval";
  const digest = typeof d.confirm_digest === "string" ? d.confirm_digest : undefined;
  const out: TaskOut = {
    posting_id,
    state: awaiting ? "awaiting approval" : d.decision === "reject" ? "rejected" : "complete",
    ...(awaiting
      ? { approval: { interaction_id: String(d.interaction_id), operation: String(d.operation), summary: String(d.summary), ...(digest ? { confirm_digest: digest } : {}) } }
      : { answer: String(d.answer ?? "").slice(0, 1500) }),
    ...(Array.isArray(d.declined) ? { declined: d.declined.map(String) } : {}),
    ...(d.decision === "approve" || d.decision === "reject" ? { decision: d.decision } : {}),
  };
  const meta = typeof res.meta.binding === "string" ? { binding: res.meta.binding } : undefined;
  if (awaiting) {
    const a = out.approval!;
    const next = digest
      ? [
          `Show the person this approval: "${a.summary}" and its confirm_digest ${digest}. Ask whether to approve or reject. Do nothing until they answer.`,
          `Then call approve_application with posting_id=${posting_id}, interaction_id="${a.interaction_id}", decision, confirm_digest=${digest} and user_quote = the person's answer in their own words, verbatim.`,
          "Alternatively the person can press Approve or Reject in the view. Do not call decide.",
        ]
      : ["The person must press Approve or Reject in the view. Do not call decide."];
    return reply(`${a.summary} Approval needed before anything is drafted.${digest ? `\nconfirm_digest: ${digest}` : ""}`, out, next, meta);
  }
  const declined = out.declined?.length ? ` Jobwatch declined to proceed with: ${out.declined.join(", ")}.` : "";
  if (d.decision === "reject") {
    return reply(`Rejected. Nothing was prepared.${declined}`, out, ["Ask the person what they want changed, or leave it."], meta);
  }
  return reply(
    `${clip(out.answer || "Done.", 1200)}${declined}`,
    out,
    [`Call task_status with posting_id=${posting_id}; when it says 'draft ready', call review_submission so the person can check the form.`],
    meta,
  );
}

export const prepareApplication = server.tool(
  {
    name: "prepare_application",
    description:
      "Hand the paid drafting work (CV, cover letter, form fill) for one job to Jobwatch's own agent. Call ONLY after the person has said they want to apply to this job. It first returns an approval to show them (summary and confirm_digest); then use approve_application. Never submits. Do NOT use to assess a job (job_detail) or to change an existing draft (revise_application).",
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
      "Hand a requested change to an existing application draft to Jobwatch's own agent. Use when the person wants something in the CV, letter or form answers changed, with their exact requested changes. It may return an approval to show them, as prepare_application does. Never submits. Do NOT use for a first draft (prepare_application).",
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

// Chat-callable approval. It is the same pending approval and binding as the view's button (the Python side does
// the single-use, person, expiry and checkpoint checks); on top it needs the digest the person was shown and their
// own words. It cannot reach submit: Submit stays on the app-only submit_reviewed.
export const approveApplication = server.tool(
  {
    name: "approve_application",
    description:
      "Approve or reject ONE pending preparation approval (from prepare_application or revise_application), after the person was shown its summary and confirm_digest and answered. Needs that exact confirm_digest and user_quote = their words, verbatim; anything else is refused. Never invent the quote or answer for them. This starts drafting only; it cannot submit.",
    inputSchema: z.strictObject({
      posting_id: posting,
      interaction_id: z.string().min(1).max(100),
      decision: z.enum(["approve", "reject"]),
      confirm_digest: z.string().regex(/^[a-f0-9]{64}$/),
      user_quote: z.string().trim().min(2).max(1000).describe("The person's own words answering the approval, verbatim"),
    }),
    outputSchema: taskOut,
    annotations: WORK,
  },
  async ({ posting_id, interaction_id, decision, confirm_digest, user_quote }) => {
    try {
      return workResult(posting_id, await call(cfg, "POST", "/connector/approve", { posting_id, interaction_id, decision, confirm_digest, user_quote }));
    } catch (e) {
      return fail(e);
    }
  },
);

// ---- app-only buttons: hidden from the model ------------------------------------------------------------------
export const decide = server.tool(
  {
    name: "decide",
    description: "View button only. Approve or reject one pending Jobwatch approval. The model must not call this; use approve_application.",
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
      return reply(`Submit ${d.status} for job ${posting_id}.`, d, [`Call task_status with posting_id=${posting_id} to follow it. Do not retry.`]);
    } catch (e) {
      return fail(e);
    }
  },
);

const proposalId = z.string().regex(/^[a-f0-9]{16}$/);
const revision = z.number().int().min(1);
const digest = z.string().regex(/^[a-f0-9]{64}$/);

function onboardingNext(d: z.infer<typeof onboardingStatusOut>): string[] {
  const p = d.proposal;
  switch (d.status) {
    case "not_started":
      return ["Ask the person for their CV or other documents (they must be uploaded in Jobwatch), then call start_onboarding with the upload_ids."];
    case "parsing":
      return ["Jobwatch is still reading the documents. Tell the person and call onboarding_status again shortly."];
    case "confirmed":
      return ["The profile is confirmed. Call discovery_status to see what has been collected and assessed."];
    default: {
      if (p?.questions.length) {
        return [`Ask the person these ${p.questions.length} question(s) in your own conversation, then save the answers with answer_onboarding_question (proposal_id=${p.id}, expected_revision=${p.revision}).`, "Save only what the person actually said."];
      }
      return [`No open questions. Call review_onboarding with proposal_id=${p?.id ?? "<id>"} and show the person the exact draft and search scope.`];
    }
  }
}

async function onboardingStatusResult(path: string, body?: unknown) {
  const d = onboardingStatusOut.parse(await call(cfg, body === undefined ? "GET" : "POST", path, body));
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

export const onboardingStatus = server.tool({
  name: "onboarding_status",
  description: "Read the person's onboarding state: saved draft facts, open questions, confirmed version. Use FIRST in any new conversation and whenever setup is unclear. Read-only. You coordinate the conversation yourself; this calls no chatbot. Next: ask the open questions, or review_onboarding when none remain, or discovery_status when confirmed.",
  inputSchema: z.strictObject({}), outputSchema: onboardingStatusOut, annotations: READ,
}, async () => {
  try { return await onboardingStatusResult("/connector/onboarding/status"); } catch (e) { return fail(e); }
});

export const startOnboarding = server.tool({
  name: "start_onboarding",
  description: "Start an onboarding draft from document IDs the person already uploaded to Jobwatch. Use only when onboarding_status says not_started. Parsing runs in Jobwatch. Never confirms a profile. Next: onboarding_status until parsing ends, then ask the saved questions yourself.",
  inputSchema: z.strictObject({ upload_ids: z.array(proposalId).min(1).max(20), base_version: z.number().int().min(1).nullable().optional() }),
  outputSchema: onboardingStatusOut, annotations: WORK,
}, async (input) => {
  try { return await onboardingStatusResult("/connector/onboarding/start", input); } catch (e) { return fail(e); }
});

export const updateOnboarding = server.tool({
  name: "update_onboarding",
  description: "Save facts or corrections the person stated in their unconfirmed draft (atomic; expected_revision prevents overwriting another edit). Use only for what the person said; never invent facts. Does not confirm or start discovery. Next: onboarding_status to see remaining questions, then review_onboarding.",
  inputSchema: z.strictObject({ proposal_id: proposalId, expected_revision: revision, edits: z.array(onboardingEdit).min(1).max(100) }),
  outputSchema: onboardingStatusOut, annotations: WORK,
}, async (input) => {
  try { return await onboardingStatusResult("/connector/onboarding/update", input); } catch (e) { return fail(e); }
});

export const answerOnboarding = server.tool({
  name: "answer_onboarding_question",
  description: "Save the person's answer to one saved onboarding question, using the current expected_revision. Ask the questions in your own conversation first; never answer for the person. Does not confirm a profile. Next: more questions, or review_onboarding when none remain.",
  inputSchema: z.strictObject({ proposal_id: proposalId, expected_revision: revision, question_id: z.string().min(1).max(64), text: z.string().min(1).max(4000) }),
  outputSchema: onboardingStatusOut, annotations: WORK,
}, async (input) => {
  try { return await onboardingStatusResult("/connector/onboarding/answer", input); } catch (e) { return fail(e); }
});

export const reviewOnboarding = server.tool({
  name: "review_onboarding",
  description: "Read the exact current draft, search scope and limits for the person's review. Show them to the person in your own words, ask for their explicit confirmation, then call confirm_onboarding with these unchanged digests. No widget approval is needed. Do NOT call confirm_onboarding without the person's yes.",
  inputSchema: z.strictObject({ proposal_id: proposalId }), outputSchema: onboardingReviewOut, annotations: READ,
}, async (input) => {
  try {
    const d = onboardingReviewOut.parse(await call(cfg, "POST", "/connector/onboarding/review", input));
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
  } catch (e) { return fail(e); }
});

export const confirmOnboarding = server.tool({
  name: "confirm_onboarding",
  description: "Confirm the exact profile and search scope the person reviewed and explicitly approved in this conversation. Call only after their clear yes to what review_onboarding returned; both digests must match or Jobwatch refuses. Authorises discovery and assessment only; never documents, employer messages or submission. Next: discovery_status.",
  inputSchema: z.strictObject({ proposal_id: proposalId, proposal_digest: digest, scope_digest: digest, confirmed: z.literal(true) }),
  outputSchema: onboardingConfirmOut, annotations: WORK,
}, async (input) => {
  try {
    const d = onboardingConfirmOut.parse(await call(cfg, "POST", "/connector/onboarding/confirm", input));
    return reply(`Profile confirmed as version ${d.version}. Discovery eligibility: ${d.discovery_enabled ? "enabled" : "disabled"}. No application submission is authorised.`, d, [
      d.discovery_enabled ? "Call discovery_status. If the person wants jobs assessed now, call start_discovery." : "Discovery is disabled; tell the person and check discovery_status for why.",
    ]);
  } catch (e) { return fail(e); }
});

export const discoveryStatus = server.tool({
  name: "discovery_status",
  description: "Read collection counts, assessment progress today, unresolved failures with their reasons, notification state and retry contexts. Use for 'is it working / why nothing new / what failed'. Failed jobs stay paused until the person explicitly asks for a retry. Collected postings are not recommendations. Next: jobs_overview, or start_discovery / retry_assessment only on request.",
  inputSchema: z.strictObject({}), outputSchema: discoveryStatusOut, annotations: READ,
}, async () => {
  try {
    const d = discoveryStatusOut.parse(await call(cfg, "GET", "/connector/discovery/status"));
    const lines = [
      `Discovery ${d.enabled ? "enabled" : "disabled"}: ${d.postings} postings collected; ${d.assessments_today} assessed today (${d.charged_tokens_today} tokens); ${d.incidents.length} unresolved incident${d.incidents.length === 1 ? "" : "s"}.`,
      ...(d.scope ? [`Scope: ${d.scope.basis.join(", ") || "none"} in ${d.scope.locations.join(", ") || "no location"}; up to ${d.scope.daily_assessments} assessments a day.`] : ["No confirmed scope yet."]),
      ...d.incidents.slice(0, 8).map((i) => `- incident ${i.incident_id}${i.posting_id != null ? ` (job #${i.posting_id})` : ""}: ${i.reason} in ${i.phase ?? "?"}, ${i.state}; notification ${i.notification_state}${i.notification_error ? ` (${i.notification_error})` : ""}`),
    ];
    const next: string[] = [];
    if (!d.enabled) next.push("Discovery is off. Call onboarding_status: the profile may not be confirmed.");
    else if (d.postings) next.push("Call jobs_overview to see the jobs, then job_detail for reasons on one.");
    if (d.incidents.length) next.push("Tell the person what failed and why. Call retry_assessment only if they explicitly ask, using that incident's retry_context as expected_context.");
    if (d.enabled) next.push("If the person wants more jobs assessed, call start_discovery with a new request_id.");
    return reply(lines.join("\n"), d, next);
  } catch (e) { return fail(e); }
});

export const startDiscovery = server.tool({
  name: "start_discovery",
  description: "Queue one bounded assessment pass for the confirmed scope within the daily spending limits. Use only when the person wants more jobs assessed. Does not retry paused failures, draft documents or submit. Reuse request_id only after a lost response. Next: discovery_status for actual progress.",
  inputSchema: z.strictObject({ request_id: z.string().min(1).max(100) }),
  outputSchema: discoveryQueuedOut, annotations: WORK,
}, async (input) => {
  try {
    const d = discoveryQueuedOut.parse(await call(cfg, "POST", "/connector/discovery/start", input));
    return reply(`Discovery request ${d.state} (run ${d.run_id}).`, d, ["Call discovery_status later to see the real progress; queued is not done."]);
  } catch (e) { return fail(e); }
});

export const retryAssessment = server.tool({
  name: "retry_assessment",
  description: "Only after the person explicitly asks, retry ONE paused assessment using the current retry_context from discovery_status as expected_context. Refuses if the profile, posting or configuration changed. Does not retry other failures or raise spending limits. Reuse request_id only after a lost response. Next: discovery_status.",
  inputSchema: z.strictObject({ request_id: z.string().min(1).max(100), incident_id: z.string().min(1).max(100),
    posting_id: posting, expected_context: digest }),
  outputSchema: discoveryQueuedOut, annotations: WORK,
}, async (input) => {
  try {
    const d = discoveryQueuedOut.parse(await call(cfg, "POST", "/connector/discovery/retry", input));
    return reply(`Requested assessment retry ${d.state} (run ${d.run_id}). Other paused jobs are unchanged.`, d, ["Call discovery_status later to see whether it succeeded."]);
  } catch (e) { return fail(e); }
});

export const getDiscoverySettings = server.tool({
  name: "get_discovery_settings",
  description: "Read the person's daily token allowance (null means Unlimited; per-job and per-run limits still apply). Use for 'how much can it spend'. Read-only. Next: set_discovery_settings only if the person asks to change it.",
  inputSchema: z.strictObject({}), outputSchema: discoverySettingsResult, annotations: READ,
  view: { name: "settings" },
}, async () => {
  try {
    const d = discoverySettingsOut.parse(await call(cfg, "GET", "/connector/discovery/settings"));
    return reply(d.daily_token_ceiling === null ? "Daily token allowance: Unlimited." : `Daily token allowance: ${d.daily_token_ceiling}.`, d, ["Change it only if the person asks, with set_discovery_settings."]);
  } catch (e) { return fail(e); }
});

export const setDiscoverySettings = server.tool({
  name: "set_discovery_settings",
  description: "Save the daily token allowance the person explicitly asked for: a positive integer, or null for Unlimited. Do not change it on your own. Keeps recorded spending, profile facts, first-failure pauses and per-run limits. Next: get_discovery_settings to confirm.",
  inputSchema: discoverySettingsOut, outputSchema: discoverySettingsResult, annotations: WORK,
}, async (input) => {
  try {
    const d = discoverySettingsOut.parse(await call(cfg, "POST", "/connector/discovery/settings", input));
    return reply(d.daily_token_ceiling === null ? "Saved daily token allowance: Unlimited." : `Saved daily token allowance: ${d.daily_token_ceiling}.`, d, ["Tell the person it is saved; it applies to the next discovery pass."]);
  } catch (e) { return fail(e); }
});

export default server;
