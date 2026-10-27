// The single registry every Jobwatch MCP tool is defined through. Instructions, tool descriptions, the guide, the
// tool-selection table, the tool count and the README tool reference are all generated from these specs.
import type { z } from "zod";
import { BackendError } from "./backend.js";

/** none: never opens a view. on_request: opens one only because the person asked (open_dashboard). review: the Submit boundary. */
export type WidgetPolicy = "none" | "on_request" | "review";
export type Access = "model" | "app";
export type Group = "guide" | "onboarding" | "discovery" | "shortlist" | "applications" | "settings" | "view";
export type WidgetMode = "off" | "on_request";

export interface Annotations {
  readOnlyHint: boolean;
  destructiveHint: boolean;
  openWorldHint: boolean;
  idempotentHint: boolean;
}

export interface ToolSpec<I extends z.ZodType = z.ZodType, O extends z.ZodType = z.ZodType> {
  name: string;
  title: string;
  group: Group;
  access: Access;
  /** One sentence: what the tool does. */
  summary: string;
  /** Clause completing "Use when ...", short enough for the generated tool-selection table. */
  whenToUse: string;
  /** Clause completing "Not for ...". */
  whenNotToUse: string;
  /** Clause naming the next tool or question. Must name at least one registered tool. */
  next: string;
  widget: WidgetPolicy;
  /** Name of the view in views/ ; required when widget is not "none". */
  view?: string;
  annotations: Annotations;
  inputSchema: I;
  outputSchema: O;
  handler: (input: z.infer<I>, ctx: HandlerContext) => Promise<unknown>;
}
export type AnySpec = ToolSpec<any, any>;

/** The slice of mcp-use's request context the handlers use. */
export interface HandlerContext {
  client?: { supportsViews?: () => boolean };
}

/** Keeps the literal name and schema types so views get typed tool calls. */
export const defineTool = <N extends string, I extends z.ZodType, O extends z.ZodType>(spec: ToolSpec<I, O> & { name: N }) => spec;

export const READ: Annotations = { readOnlyHint: true, destructiveHint: false, openWorldHint: false, idempotentHint: true };
export const WORK: Annotations = { readOnlyHint: false, destructiveHint: false, openWorldHint: false, idempotentHint: false };

export const MAX_DESCRIPTION = 600;

/** The text hosts show the model for a tool. App-only buttons get a short warning instead. */
export function describeTool(s: AnySpec): string {
  if (s.access === "app") return `${s.summary} The model must not call this.`;
  return `${s.summary} Use when ${s.whenToUse}. Not for ${s.whenNotToUse}. Next: ${s.next}.`;
}

export function widgetMode(env: Record<string, string | undefined> = process.env): WidgetMode {
  const v = (env.JOBWATCH_MCP_WIDGETS ?? "on_request").trim().toLowerCase();
  if (v === "off" || v === "on_request") return v;
  throw new Error("JOBWATCH_MCP_WIDGETS must be off or on_request");
}

/** Tools actually registered under a widget mode: with widgets off, tools that only exist to open a view are dropped. */
export const activeSpecs = (specs: AnySpec[], mode: WidgetMode) =>
  specs.filter((s) => !(mode === "off" && s.widget === "on_request"));
export const modelSpecs = (specs: AnySpec[], mode: WidgetMode) => activeSpecs(specs, mode).filter((s) => s.access === "model");

/** Validates the registry; used at startup and by the conformance test. Returns the problems found. */
export function lintRegistry(specs: AnySpec[]): string[] {
  const problems: string[] = [];
  const names = new Set(specs.map((s) => s.name));
  if (names.size !== specs.length) problems.push("duplicate tool names");
  for (const s of specs) {
    const where = s.name;
    for (const f of ["title", "summary", "whenToUse", "whenNotToUse", "next"] as const) if (!s[f]?.trim()) problems.push(`${where}: missing ${f}`);
    if (!["none", "on_request", "review"].includes(s.widget)) problems.push(`${where}: missing widget policy`);
    if (s.widget !== "none" && !s.view) problems.push(`${where}: widget policy ${s.widget} needs a view`);
    if (s.widget === "none" && s.view) problems.push(`${where}: view set but widget policy is none`);
    if (!s.annotations || typeof s.annotations.readOnlyHint !== "boolean") problems.push(`${where}: missing annotations`);
    if (s.widget === "on_request" && !s.annotations.readOnlyHint) problems.push(`${where}: an on-request widget tool must be read-only`);
    if (s.access === "model") {
      if (describeTool(s).length > MAX_DESCRIPTION) problems.push(`${where}: description is ${describeTool(s).length} chars (max ${MAX_DESCRIPTION})`);
      if (![...names].some((n) => n !== s.name && s.next.includes(n))) problems.push(`${where}: next must name another registered tool`);
    }
  }
  return problems;
}

// ---- result helpers -----------------------------------------------------------------------------------------------
export const text = (t: string) => [{ type: "text" as const, text: t }];
export const clip = (v: unknown, n = 160) => {
  const t = String(v ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

// One shape for every tool result: a compact human summary (never a JSON dump), the structured data, and plain
// sentences naming the next step.
export function reply<T extends object>(summary: string, data: T, next: string[], meta?: Record<string, unknown>) {
  return {
    content: text(next.length ? `${summary}\nNext actions:\n${next.map((n) => `- ${n}`).join("\n")}` : summary),
    structuredContent: { ...data, next_actions: next },
    ...(meta ? { _meta: meta } : {}),
  };
}

// Plain-English hints for refusals, so the host explains them instead of retrying.
const ERROR_HINT: Record<string, string> = {
  approval_not_found: "That approval has expired, was already answered, or is not yours. Ask the person whether to request the revision again.",
  approval_digest_mismatch: "The digest was not the one shown. The approval is still pending: show the person its card again and use its exact confirm_digest.",
  review_changed: "The form changed after review. Review it again and have the person look at it.",
  submit_digest_mismatch: "The form changed after review. Review it again and have the person look at it.",
  inputs_changed: "The shortlist entry changed since you read it. Read the job again and use its current entry_id and run_key.",
  idempotency_conflict: "That request_id was already used for different inputs. Read the job again and use a fresh request_id.",
  confirmation_required: "The person has not explicitly confirmed. Ask them first.",
  invalid_request: "The request was not valid. Check the arguments and the person's words.",
};
export const fail = (e: unknown) => {
  if (!(e instanceof BackendError)) {
    return { isError: true as const, content: text("Jobwatch is not reachable right now. Tell the person; do not retry in a loop. If other Jobwatch tools are missing from your list, ask them to start a new thread.") };
  }
  const hint = ERROR_HINT[e.code];
  return { isError: true as const, content: text(`Jobwatch refused: ${e.code}${hint ? `. ${hint}` : ""}`) };
};
