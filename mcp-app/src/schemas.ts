import { z } from "zod";

export const jobRow = z.object({
  posting_id: z.number().int(),
  employer: z.string().nullable(),
  title: z.string().nullable(),
  score: z.number().nullable(),
  state: z.string(),
  detail: z.string(),
});

export const overviewOut = z.object({
  counts: z.object({
    needs_you: z.number().int(),
    needs_info: z.number().int(),
    outcome_unknown: z.number().int(),
    submitted: z.number().int(),
  }),
  jobs: z.array(jobRow),
});

export const jobOut = z.object({
  posting_id: z.number().int(),
  found: z.boolean(),
  employer: z.string().nullable().optional(),
  title: z.string().nullable().optional(),
  location: z.string().nullable().optional(),
  ad_url: z.string().nullable().optional(),
  score: z.number().nullable().optional(),
  why_it_fits: z.string().nullable().optional(),
  pros: z.array(z.string()).optional(),
  cons: z.array(z.string()).optional(),
  state: z.string().optional(),
  state_detail: z.string().optional(),
  documents_ready: z.boolean().optional(),
  draft_version: z.number().nullable().optional(),
  can_submit: z.boolean().optional(),
});

// task_status, prepare_application and revise_application share this shape so one view renders all three.
export const taskOut = z.object({
  posting_id: z.number().int(),
  state: z.string(),
  message: z.string().optional(),
  reason: z.string().optional(),
  // set only when Jobwatch's own agent is waiting for the person to press Approve or Reject
  approval: z
    .object({ interaction_id: z.string(), operation: z.string(), summary: z.string() })
    .optional(),
  answer: z.string().optional(),
  declined: z.array(z.string()).optional(),
  decision: z.enum(["approve", "reject"]).optional(),
});

export const reviewOut = z.object({
  posting_id: z.number().int(),
  found: z.boolean(),
  ready: z.boolean(),
  reason: z
    .enum([
      "not_prepared", "not_ready", "edited_in_browser",
      // the live form could not be read just now (browser closed, page moved, unsupported widget): never offers Submit
      "browser_unavailable", "application_changed", "final_control_changed", "unsupported_form_review",
      "form_review_unavailable", "form_review_changed", "application_not_ready",
    ])
    .optional(),
  employer: z.string().nullable().optional(),
  title: z.string().nullable().optional(),
  state: z.string().optional(),
  ad_url: z.string().nullable().optional(),
  // every filled form answer, question to answer, exactly what the digest was taken over
  answers: z.array(z.object({ question: z.string(), answer: z.string(), source: z.string() })),
  documents: z.array(z.object({ role: z.string(), label: z.string(), file: z.string(), sha256: z.string() })),
});

// A chat turn: either the assistant's answer, or one or more questions only the person can answer.
export const chatOut = z.object({
  thread_id: z.string(),
  status: z.enum(["complete", "needs_answer"]),
  answer: z.string().optional(),
  questions: z.array(z.object({ question: z.string(), options: z.array(z.string()).optional() })).optional(),
  note: z.string().optional(),
  declined: z.array(z.string()).optional(),
  approvals_not_answerable_here: z.array(z.string()).optional(),
  tools: z.array(z.string()).optional(),
});

export const submitOut = z.object({
  posting_id: z.number().int(),
  status: z.string(),
});

export type TaskOut = z.infer<typeof taskOut>;
export type ChatOut = z.infer<typeof chatOut>;
