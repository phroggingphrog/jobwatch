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
  reason: z.enum(["not_prepared", "not_ready", "edited_in_browser"]).optional(),
  employer: z.string().nullable().optional(),
  title: z.string().nullable().optional(),
  state: z.string().optional(),
  ad_url: z.string().nullable().optional(),
  // every filled form answer, question to answer, exactly what the digest was taken over
  answers: z.array(z.object({ question: z.string(), answer: z.string(), source: z.string() })),
  documents: z.array(z.object({ role: z.string(), label: z.string(), file: z.string(), sha256: z.string() })),
});

export const submitOut = z.object({
  posting_id: z.number().int(),
  status: z.string(),
});

export type TaskOut = z.infer<typeof taskOut>;
