import { z } from "zod";

export const jobRow = z.object({
  posting_id: z.number().int(),
  employer: z.string().nullable(),
  title: z.string().nullable(),
  score: z.number().nullable(),
  state: z.string(),
  detail: z.string(),
  assessment_state: z.string().nullable().optional(),
  assessment_reason: z.string().nullable().optional(),
  assessment_summary: z.string().nullable().optional(),
});

export const shortlistEntry = jobRow.extend({
  entry_id: z.string(), shortlist_id: z.string(), run_key: z.string(),
  label: z.enum(["stronger_match", "stretch", "needs_clarification"]), rank: z.number().int(),
  ordering: z.enum(["provisional", "personalised"]), rank_reason: z.string(),
  objective_fit: z.string(), uncertainty: z.string(), can_prepare: z.boolean(),
  conditions: z.array(z.string()), unresolved: z.array(z.string()),
  mandatory_requirements: z.array(z.string()), transferable_skills: z.array(z.string()),
  evidence: z.array(z.record(z.string(), z.unknown())), requirements: z.array(z.record(z.string(), z.unknown())),
}).passthrough();

export const applicationsOut = z.object({
  counts: z.object({needs_you: z.number().int(), needs_info: z.number().int(), outcome_unknown: z.number().int(), submitted: z.number().int()}),
  jobs: z.array(jobRow),
});
export const overviewOut = applicationsOut.extend({
  status: z.enum(["ok", "not_built", "no_confirmed_profile", "stale"]),
  shortlist_id: z.string().optional(), meaning: z.string(), total: z.number().int(),
  jobs: z.array(shortlistEntry),
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
  can_prepare: z.boolean().optional(),
  shortlist_status: z.string().optional(),
  shortlist_entry: shortlistEntry.optional(),
  assessment_state: z.string().nullable().optional(),
  assessment_reason: z.string().nullable().optional(),
  assessment_summary: z.string().nullable().optional(),
});

// task_status, prepare_application and revise_application share this shape so one view renders all three.
export const taskOut = z.object({
  posting_id: z.number().int(),
  state: z.string(),
  selection_id: z.string().optional(),
  authorises: z.literal("preparation_only").optional(),
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

export const onboardingProposal = z.object({
  id: z.string(), revision: z.number().int(),
  status: z.enum(["parsing", "draft", "confirmed", "superseded"]),
  facts: z.array(z.object({ id: z.string(), section: z.string(), value: z.unknown(), basis: z.string() }).passthrough()),
  questions: z.array(z.object({ id: z.string(), section: z.string(), text: z.string(), why: z.string() }).passthrough()),
  parse_error: z.string(),
}).passthrough();

export const onboardingScope = z.object({
  basis: z.array(z.string()), locations: z.array(z.string()),
  daily_assessments: z.number().int(), daily_token_ceiling: z.number().int().nullable(),
});

export const onboardingStatusOut = z.object({
  status: z.enum(["draft", "parsing", "confirmed", "not_started"]),
  proposal: onboardingProposal.nullable(),
  current_version: z.record(z.string(), z.unknown()).nullable(),
});

export const onboardingReviewOut = z.object({
  status: z.literal("ready"), proposal: onboardingProposal, scope: onboardingScope,
  proposal_digest: z.string(), scope_digest: z.string(),
  authorises: z.array(z.string()), does_not_authorise: z.array(z.string()),
});

export const onboardingConfirmOut = z.object({
  status: z.literal("confirmed"), version: z.number().int(),
  discovery: onboardingScope.nullable(), discovery_enabled: z.boolean(),
  authorises: z.array(z.string()), does_not_authorise: z.array(z.string()),
});

export const onboardingEdit = z.discriminatedUnion("op", [
  z.strictObject({ op: z.literal("add"), section: z.string().min(1), value: z.json() }),
  z.strictObject({ op: z.literal("set"), fact_id: z.string().min(1), basis: z.literal("evidence"), value: z.json() }),
  z.strictObject({ op: z.literal("remove"), fact_id: z.string().min(1) }),
]);

export const submitOut = z.object({
  posting_id: z.number().int(),
  status: z.string(),
});

export const discoverySettingsOut = z.strictObject({ daily_token_ceiling: z.number().int().positive().nullable() });

export const discoveryStatusOut = z.object({
  enabled: z.boolean(), postings: z.number().int(), assessments_today: z.number().int(),
  charged_tokens_today: z.number().int(), scope: onboardingScope.nullable(),
  incidents: z.array(z.object({
    incident_id: z.string(), posting_id: z.number().int().nullable(), run_id: z.string(),
    reason: z.string(), phase: z.string().nullable(), last_successful_phase: z.string().nullable(),
    state: z.string(), notification_state: z.string(), notification_error: z.string().nullable(),
    retry_context: z.string().nullable().optional(),
  }).passthrough()),
  latest_run: z.record(z.string(), z.unknown()).nullable(),
  invocations: z.array(z.record(z.string(), z.unknown())),
});

export const discoveryQueuedOut = z.object({ run_id: z.string(), state: z.string() });

export type TaskOut = z.infer<typeof taskOut>;
