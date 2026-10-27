import { spawn, type ChildProcess } from "node:child_process";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { specs } from "../src/tools.js";
// @ts-expect-error plain JS helper
import { startMock, DIGEST, SHOWN, BACKEND_TOKEN, APPROVE_DIGEST } from "./mock-backend.mjs";

const PORT = 18943;
const URL_ = `http://127.0.0.1:${PORT}/mcp`;
let proc: ChildProcess;
let mock: { server: import("node:http").Server; log: unknown[]; port: number; queuedCount: () => number };
let client: Client;

async function connect() {
  const c = new Client({ name: "test", version: "1" });
  await c.connect(new StreamableHTTPClientTransport(new URL(URL_)));
  return c;
}
const call = (name: string, args: Record<string, unknown> = {}) => client.callTool({ name, arguments: args }) as Promise<any>;
const modelVisible = (r: any) => JSON.stringify({ content: r.content, structuredContent: r.structuredContent });

beforeAll(async () => {
  mock = await startMock(0);
  proc = spawn("node_modules/.bin/mcp-use", ["start", "--port", String(PORT)], {
    env: { ...process.env, JOBWATCH_CONNECTOR_TOKEN: BACKEND_TOKEN, JOBWATCH_BACKEND_URL: `http://127.0.0.1:${mock.port}`, JOBWATCH_MCP_PUBLIC_URL: `http://127.0.0.1:${PORT}` },
    stdio: "ignore",
  });
  for (let i = 0; i < 60; i++) {
    try { client = await connect(); return; } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error("server did not start");
}, 60_000);

afterAll(async () => {
  await client?.close().catch(() => {});
  proc?.kill();
  mock?.server.close();
});

describe("authentication boundary", () => {
  it("does not require a Jobwatch token; Cloudflare Access authenticates the public endpoint", async () => {
    const local = await connect();
    expect((await local.listTools()).tools.length).toBeGreaterThan(0);
    await local.close();
  });
});

describe("tools list", () => {
  it("lists exactly the registry, with hints, widget policy and visibility", async () => {
    const { tools } = await client.listTools();
    const by = Object.fromEntries(tools.map((t) => [t.name, t]));
    expect(Object.keys(by).sort()).toEqual(specs.map((s) => s.name).sort());
    for (const s of specs) {
      expect(by[s.name].annotations, s.name).toMatchObject(s.annotations);
      expect(by[s.name].outputSchema, s.name).toBeTruthy();
      const view = (by[s.name]._meta as any)?.ui?.resourceUri;
      // a view is attached only to tools whose widget policy allows one; every other tool is text only
      if (s.widget === "none") expect(view, `${s.name} must not attach a view`).toBeUndefined();
      else expect(view, s.name).toMatch(/^ui:\/\//);
      if (s.access === "app") expect((by[s.name]._meta as any).ui.visibility, s.name).toEqual(["app"]);
      else expect((by[s.name]._meta as any)?.ui?.visibility, s.name).toBeUndefined();
    }
    expect(specs.filter((s) => s.widget !== "none").map((s) => s.name).sort()).toEqual(["open_dashboard", "review_submission"]);
    expect(by.submit_reviewed.annotations).toMatchObject({ destructiveHint: true, openWorldHint: true, readOnlyHint: false });
    expect(JSON.stringify(by.submit_reviewed.inputSchema)).toContain("confirm_digest");
  });
  it("publishes the dashboard app as an MCP resource", async () => {
    const { tools } = await client.listTools();
    const dash = tools.find((tool) => tool.name === "open_dashboard")!;
    const uri = (dash._meta as any).ui.resourceUri as string;
    const result = await client.readResource({ uri });
    expect(result.contents[0].mimeType).toContain("profile=mcp-app");
    const html = result.contents[0].text ?? "";
    expect(html).toContain('<div id="root"');
    expect(html).toContain('<script type="module">');
    expect(html).toContain("Daily token allowance");
    expect(html).toContain("Retry this assessment");
    expect(html).toContain("Refresh shortlist");
    expect(html).not.toMatch(/<script\b[^>]*\bsrc\s*=|<link\b[^>]*\bhref\s*=/i);
  });
});

describe("read tools", () => {
  it("jobs_overview returns matching structured content", async () => {
    const r = await call("jobs_overview", {});
    expect(r.isError).toBeFalsy();
    expect(r.structuredContent.jobs).toHaveLength(2);
    expect(r.structuredContent.counts.needs_you).toBe(0);
    expect(r.content[0].text).toContain("Acme Pty Ltd");
    expect(r.structuredContent.jobs[0]).toMatchObject({ label: "stronger_match", can_prepare: true });
    expect(r.structuredContent.jobs[1]).toMatchObject({label:"needs_clarification",can_prepare:false});
  });
  it("job_detail and task_status", async () => {
    const d = await call("job_detail", { posting_id: 1 });
    expect(d.structuredContent).toMatchObject({ found: true, can_submit: true, state: "draft ready", assessment_state: "current" });
    expect(d.structuredContent).toMatchObject({assessment_state:"current", assessment_reason:"evaluation_complete", assessment_summary:"Synthetic assessed role."});
    expect(modelVisible(d)).toContain("stronger match");
    const missing = await call("job_detail", { posting_id: 99 });
    expect(missing.structuredContent.found).toBe(false);
    const s = await call("task_status", { posting_id: 3 });
    expect(s.structuredContent).toMatchObject({ posting_id: 3, state: "outcome unknown" });
  });
  it("rejects bad input", async () => {
    for (const args of [{ posting_id: 0 }, { posting_id: "1" }, {}]) {
      const r = await client.callTool({ name: "job_detail", arguments: args }).catch((e) => ({ isError: true, e }));
      expect((r as any).isError).toBe(true);
    }
  });
});

describe("digest handling", () => {
  it("never appears in what the model reads; only review_submission _meta carries it", async () => {
    const d = await call("job_detail", { posting_id: 1 });
    expect(JSON.stringify(d)).not.toContain(DIGEST);
    expect(d._meta?.submit_digest).toBeUndefined();
    const o = await call("jobs_overview", {});
    expect(JSON.stringify(o)).not.toContain(DIGEST);
    const r = await call("review_submission", { posting_id: 1 });
    expect(r.structuredContent).toMatchObject({ ready: true, employer: "Acme Pty Ltd" });
    expect(r.structuredContent.answers).toHaveLength(4);
    expect(r.structuredContent.answers[1]).toMatchObject({ question: "Right to work in Australia?", answer: "Yes" });
    expect(r.structuredContent.documents.map((d: any) => d.file)).toEqual(["cv.pdf", "letter.pdf"]);
    expect(modelVisible(r)).not.toContain(DIGEST);
    expect(modelVisible(r)).not.toContain(SHOWN);
    expect(r._meta.submit_digest).toBe(DIGEST);
    expect(r._meta.shown_hash).toBe(SHOWN);
    for (const [id, reason] of [[2, "not_prepared"], [3, "not_ready"], [4, "edited_in_browser"]] as const) {
      const none = await call("review_submission", { posting_id: id });
      expect(none.structuredContent).toMatchObject({ ready: false, reason });
      expect(none._meta?.submit_digest).toBeUndefined();
      expect(none._meta?.shown_hash).toBeUndefined();
    }
    const unknown = await call("review_submission", { posting_id: 99 });
    expect(unknown.structuredContent).toMatchObject({ found: false, ready: false });
  });
});

describe("submit safety (mock backend only)", () => {
  it("refuses a missing or wrong digest, queues once with the right one", async () => {
    for (const args of [{ posting_id: 1 }, { posting_id: 1, confirm_digest: "" }, { posting_id: 1, confirm_digest: DIGEST }, { posting_id: 1, confirm_digest: DIGEST, shown_hash: "" }]) {
      const r = await client.callTool({ name: "submit_reviewed", arguments: args }).catch(() => ({ isError: true }));
      expect((r as any).isError).toBe(true);
    }
    const wrong = await call("submit_reviewed", { posting_id: 1, confirm_digest: "a".repeat(64), shown_hash: SHOWN });
    expect(wrong.isError).toBe(true);
    expect(wrong.content[0].text).toContain("submit_digest_mismatch");
    const stale = await call("submit_reviewed", { posting_id: 1, confirm_digest: DIGEST, shown_hash: "f".repeat(64) });
    expect(stale.isError).toBe(true);
    expect(stale.content[0].text).toContain("review_changed");
    expect(mock.queuedCount()).toBe(0);
    const ok = await call("submit_reviewed", { posting_id: 1, confirm_digest: DIGEST, shown_hash: SHOWN });
    expect(ok.structuredContent).toMatchObject({ posting_id: 1, status: "queued" });
    const again = await call("submit_reviewed", { posting_id: 1, confirm_digest: DIGEST, shown_hash: SHOWN });
    expect(again.isError).toBe(true);
    expect(mock.queuedCount()).toBe(1);
  });
});

describe("work tools", () => {
  it("revise raises an approval with the binding only in _meta; decide needs it", async () => {
    const p = await call("revise_application", { posting_id: 2, changes: "short letter" });
    expect(p.structuredContent.approval).toMatchObject({ interaction_id: "i-1", operation: "revise_application" });
    expect(modelVisible(p)).not.toContain("bind-1");
    expect(p._meta.binding).toBe("bind-1");
    const bad = await call("decide", { posting_id: 2, interaction_id: "i-1", decision: "approve", binding: "nope" });
    expect(bad.isError).toBe(true);
    const ok = await call("decide", { posting_id: 2, interaction_id: "i-1", decision: "approve", binding: "bind-1" });
    expect(ok.structuredContent).toMatchObject({ state: "complete", decision: "approve" });
    const again = await call("decide", { posting_id: 2, interaction_id: "i-1", decision: "approve", binding: "bind-1" });
    expect(again.isError).toBe(true);
  });
  it("prepares only an exact current eligible entry after consent; stable retries do not duplicate",async()=>{
    expect((await call("prepare_application",{posting_id:1})).isError).toBe(true);
    const args={posting_id:1,expected_entry_id:"entry-1",expected_run_key:"run-1",request_id:"synthetic-prepare",confirmed:true};
    const first=await call("prepare_application",args);
    expect(first.structuredContent).toMatchObject({state:"queued",authorises:"preparation_only"});
    expect((await call("prepare_application",args)).structuredContent).toMatchObject({ state: first.structuredContent.state, selection_id: first.structuredContent.selection_id });
    expect((await call("prepare_application",{...args,posting_id:2,expected_entry_id:"entry-2",expected_run_key:"run-2"})).isError).toBe(true);
    expect((await call("prepare_application",{...args,expected_run_key:"changed"})).isError).toBe(true);
    const history=await call("applications_overview");expect(history.structuredContent.jobs).toHaveLength(4);
    const diagnostic=await call("assessment_detail",{posting_id:4});expect(diagnostic.structuredContent.found).toBe(true);
    expect((await call("job_detail",{posting_id:4})).structuredContent.found).toBe(false);
  });
  it("revise needs changes", async () => {
    const r = await client.callTool({ name: "revise_application", arguments: { posting_id: 1, changes: "" } }).catch(() => ({ isError: true }));
    expect((r as any).isError).toBe(true);
  });
});

describe("host guidance", () => {
  it("initialize returns instructions with the operating protocol", async () => {
    const ins = client.getInstructions() ?? "";
    expect(ins.length).toBeGreaterThan(1500);
    expect(ins.length).toBeLessThan(6000);
    for (const phrase of ["authoritative", "NEVER paste raw JSON", "do not depend on any view", "canonical shortlist", "NOT recommendations", "onboarding_status", "discovery_status", "jobs_overview", "job_detail", "prepare_application", "approve_application", "review_submission", "user_quote", "verbatim", "never call submit_reviewed", "start a new thread", "own action", "next_actions"]) {
      expect(ins.toLowerCase()).toContain(phrase.toLowerCase());
    }
  });
  it("lists jobwatch_guide and approve_application with the right hints and visibility", async () => {
    const { tools } = await client.listTools();
    const by = Object.fromEntries(tools.map((t) => [t.name, t]));
    expect(by.jobwatch_guide.annotations).toMatchObject({ readOnlyHint: true, destructiveHint: false });
    expect(by.approve_application.annotations).toMatchObject({ readOnlyHint: false, destructiveHint: false, openWorldHint: false });
    expect((by.approve_application._meta as any)?.ui?.visibility).toBeUndefined();
    expect(by.approve_application.inputSchema.required).toEqual(expect.arrayContaining(["posting_id", "interaction_id", "decision", "confirm_digest", "user_quote"]));
    expect((by.submit_reviewed._meta as any).ui.visibility).toEqual(["app"]);
    for (const t of tools) {
      if (t.name === "decide" || t.name === "submit_reviewed") continue;
      expect(t.description!.length, t.name).toBeGreaterThan(150);
      expect(t.description!.length, t.name).toBeLessThanOrEqual(620);
    }
  });
  it("the instructions name every model tool and state the count of the registry", async () => {
    const ins = client.getInstructions() ?? "";
    const model = specs.filter((s) => s.access === "model");
    for (const s of model) expect(ins, s.name).toContain(s.name);
    expect(ins).toContain(`offers ${model.length} tools`);
    expect(ins).toContain("open_dashboard");
    expect(ins).toContain("Never open a widget unless the person asks");
  });
  it("the instructions keep the canonical-shortlist rule", () => {
    const ins = client.getInstructions() ?? "";
    for (const phrase of ["ONLY from the current canonical shortlist", "application history", "assessment_detail", "refresh_shortlist", "confirmed=true"]) expect(ins).toContain(phrase);
  });
  it("guide topics return text built from the skills", async () => {
    for (const topic of ["overview", "onboarding", "discovery", "assess", "prepare", "submit", "troubleshooting"]) {
      const r = await call("jobwatch_guide", { topic });
      expect(r.isError).toBeFalsy();
      expect(r.content[0].text).toContain(`JOBWATCH GUIDE: ${topic}`);
      expect(() => JSON.parse(r.content[0].text)).toThrow();
      expect(r.structuredContent.topic).toBe(topic);
      expect(r.structuredContent.next_actions.length).toBeGreaterThan(0);
    }
    const assess = await call("jobwatch_guide", { topic: "assess" });
    expect(assess.content[0].text).toContain("evaluation_complete");        // from skills/assess-fit/SKILL.md
    expect(assess.structuredContent.sources).toEqual(expect.arrayContaining([{ name: "assess-fit", from: "repo" }]));
    expect((await call("jobwatch_guide", { topic: "nope" })).isError).toBe(true);
    expect((await call("jobwatch_guide", { topic: "submit" })).content[0].text).toContain("submit_reviewed");
  });
  it("publishes every skill as a skill:// resource", async () => {
    const { resources } = await client.listResources();
    const uris = resources.map((r) => r.uri).filter((u) => u.startsWith("skill://jobwatch/"));
    for (const n of ["career-ops", "assess-fit", "prepare-application", "inspect-jobs", "company-research", "followup-draft", "interview-prep", "model-insights"]) {
      expect(uris).toContain(`skill://jobwatch/${n}/SKILL.md`);
    }
    const r = await client.readResource({ uri: "skill://jobwatch/career-ops/SKILL.md" });
    expect(r.contents[0].text).toContain("name: career-ops");
  });
  it("every tool result is a readable summary, not JSON, and carries next_actions", async () => {
    const calls: [string, Record<string, unknown>][] = [
      ["jobs_overview", {}], ["refresh_shortlist", {}], ["applications_overview", {}], ["application_detail", { posting_id: 1 }], ["assessment_detail", { posting_id: 1 }], ["job_detail", { posting_id: 1 }], ["job_detail", { posting_id: 2 }], ["job_detail", { posting_id: 99 }], ["task_status", { posting_id: 2 }],
      ["review_submission", { posting_id: 1 }], ["review_submission", { posting_id: 2 }], ["onboarding_status", {}],
      ["review_onboarding", { proposal_id: "1111111111111111" }], ["discovery_status", {}], ["get_discovery_settings", {}],
      ["jobwatch_guide", {}],
      ["open_dashboard", { tab: "jobs" }], ["open_dashboard", { tab: "applications" }], ["open_dashboard", { tab: "discovery" }], ["open_dashboard", { tab: "settings" }],
    ];
    for (const [name, args] of calls) {
      const r = await call(name, args);
      const t: string = r.content[0].text;
      expect(r.isError, name).toBeFalsy();
      expect(() => JSON.parse(t), name).toThrow();
      expect(t.trimStart().startsWith("{") || t.trimStart().startsWith("["), name).toBe(false);
      expect(Array.isArray(r.structuredContent.next_actions), name).toBe(true);
      expect(r.structuredContent.next_actions.length, name).toBeGreaterThan(0);
      expect(t, name).toContain("Next actions:");
    }
    const o = await call("jobs_overview", {});
    expect(o.content[0].text).toMatch(/#1 job 1 Acme Pty Ltd - Data Analyst \| stronger match .*can prepare after consent/);
    expect(o.content[0].text).toMatch(/#2 job 2 Globex - BI Developer \| evidence hold \(needs clarification\).*cannot prepare yet/);
    expect(o.content[0].text).toContain("advisory");
    expect(o.structuredContent.next_actions[0]).toContain("job_detail");
    const d1 = await call("job_detail", { posting_id: 1 });
    expect(d1.content[0].text).toContain('expected_entry_id="entry-1" expected_run_key="run-1"');
    expect(d1.structuredContent.next_actions.join(" ")).toContain("review_submission");
    expect(d1.content[0].text).not.toContain(DIGEST);
    const d2 = await call("job_detail", { posting_id: 2 });
    expect(d2.content[0].text).toContain("Confirm availability");
    expect(d2.structuredContent.next_actions.join(" ")).not.toContain("call prepare_application");
    const hist = await call("applications_overview", {});
    expect(hist.content[0].text).toContain("history");
    expect(hist.structuredContent.next_actions.join(" ")).toContain("only from jobs_overview");
    const diag = await call("assessment_detail", { posting_id: 1 });
    expect(diag.content[0].text).toContain("Not a recommendation");
    const rev = await call("review_submission", { posting_id: 1 });
    expect(rev.content[0].text).toContain("Alex Example");
    expect(rev.content[0].text).not.toContain(DIGEST);
    const onb = await call("onboarding_status", {});
    expect(onb.content[0].text).toContain("q1");
    expect(onb.structuredContent.next_actions.join(" ")).toContain("answer_onboarding_question");
  });
});

describe("chat approval (approve_application)", () => {
  const prep = async (posting_id = 2) => (await call("revise_application", { posting_id, changes: "shorter letter" }));
  const base = (p: any, over: Record<string, unknown> = {}) => ({ posting_id: 2, interaction_id: p.structuredContent.approval.interaction_id, decision: "approve", confirm_digest: p.structuredContent.approval.confirm_digest, user_quote: "yes, prepare it", ...over });
  const refused = async (args: Record<string, unknown>) => {
    const r = await client.callTool({ name: "approve_application", arguments: args }).catch(() => ({ isError: true, content: [] }));
    return r as any;
  };
  it("revise shows the digest and tells the host how to approve, without the binding", async () => {
    const p = await prep();
    expect(p.structuredContent.approval.confirm_digest).toBe(APPROVE_DIGEST);
    expect(p.content[0].text).toContain(APPROVE_DIGEST);
    expect(p.content[0].text).toContain("approve_application");
    expect(modelVisible(p)).not.toContain("bind-1");
  });
  it("refuses a wrong digest, empty or blank quote, wrong posting and extra fields, and leaves the approval pending", async () => {
    const p = await prep();
    const logBefore = (mock.log as any[]).filter((x) => x.path === "/connector/approve").length;
    for (const over of [{ confirm_digest: "0".repeat(64) }, { confirm_digest: "bind-1" }, { user_quote: "" }, { user_quote: "   " }, { decision: "maybe" }, { person: "other" }]) {
      expect((await refused(base(p, over))).isError, JSON.stringify(over)).toBe(true);
    }
    const wrongPosting = await refused(base(p, { posting_id: 1 }));
    expect(wrongPosting.isError).toBe(true);
    const mismatch = await refused(base(p, { confirm_digest: "0".repeat(64) }));
    expect(mismatch.content[0].text).toContain("approval_digest_mismatch");
    // schema-level refusals never reach the backend; the two server-side ones did, and nothing was queued or submitted
    expect((mock.log as any[]).filter((x) => x.path === "/connector/approve").length - logBefore).toBe(3);
    expect((mock.log as any[]).some((x) => x.path.endsWith("/submit") && x.body?.posting_id === 2)).toBe(false);
    const ok = await call("approve_application", base(p));
    expect(ok.isError).toBeFalsy();
    expect(ok.structuredContent).toMatchObject({ state: "complete", decision: "approve" });
    expect((mock.log as any[]).at(-1).body).toMatchObject({ confirm_digest: APPROVE_DIGEST, user_quote: "yes, prepare it" });
    expect(ok.content[0].text).toContain("task_status");
    const again = await refused(base(p));
    expect(again.isError).toBe(true);
  });
  it("can reject, and never reaches submit", async () => {
    const p = await prep();
    const r = await call("approve_application", base(p, { decision: "reject", user_quote: "no, not this one" }));
    expect(r.structuredContent).toMatchObject({ state: "rejected", decision: "reject" });
    expect((mock.log as any[]).some((x) => /\/submit$/.test(x.path) && x.body?.posting_id === 2)).toBe(false);
  });
});

describe("widgets only on request", () => {
  it("read tool results never carry view metadata", async () => {
    for (const [name, args] of [["jobs_overview", {}], ["job_detail", { posting_id: 1 }], ["applications_overview", {}], ["discovery_status", {}], ["task_status", { posting_id: 1 }], ["get_discovery_settings", {}], ["assessment_detail", { posting_id: 1 }]] as const) {
      const r = await call(name, args);
      expect(JSON.stringify(r._meta ?? {}), name).not.toMatch(/ui:\/\/|resourceUri/);
    }
  });
  it("open_dashboard returns the tab's data as text and structure, and says whether the host declared views", async () => {
    const jobs = await call("open_dashboard", {});
    expect(jobs.structuredContent).toMatchObject({ tab: "jobs", host_views: expect.stringMatching(/declared/) });
    expect(jobs.structuredContent.jobs.jobs).toHaveLength(2);
    expect(jobs.content[0].text).toContain("Acme Pty Ltd");
    const settings = await call("open_dashboard", { tab: "settings" });
    expect(settings.structuredContent.settings).toHaveProperty("daily_token_ceiling");
    expect((await call("open_dashboard", { tab: "nope" })).isError).toBe(true);
  });
});

describe("direct onboarding", () => {
  it("exposes normal typed operations and no chatbot tools", async () => {
    const {tools} = await client.listTools();
    expect(tools.some(t => t.name.includes("chat"))).toBe(false);
    for (const name of ["onboarding_status", "review_onboarding", "confirm_onboarding"]) {
      const t = tools.find(t => t.name === name)!;
      expect(t.outputSchema).toBeTruthy();
      expect((t._meta as any)?.ui?.visibility).toBeUndefined();
      expect(JSON.stringify(t.inputSchema)).not.toMatch(/"person"|"actor"/);
    }
  });
  it("returns all facts and questions directly without a thread or chatbot", async () => {
    const r=await call("onboarding_status");
    expect(r.isError).toBeFalsy();
    expect(r.structuredContent).toMatchObject({status:"draft",proposal:{id:"1111111111111111",revision:2}});
    expect(r.structuredContent.proposal.questions).toHaveLength(2);
    expect(r.structuredContent.thread_id).toBeUndefined();
  });
  it("saves typed edits and answers through the canonical endpoints", async () => {
    const edits=[{op:"add",section:"location",value:"Victoria"}];
    expect((await call("update_onboarding", {proposal_id:"1111111111111111",expected_revision:2,edits})).isError).toBeFalsy();
    expect((mock.log as any[]).at(-1).body.edits).toEqual(edits);
    expect((await call("answer_onboarding_question", {proposal_id:"1111111111111111",expected_revision:2,question_id:"q1",text:"Victoria"})).isError).toBeFalsy();
    expect((mock.log as any[]).at(-1).path).toBe("/connector/onboarding/answer");
  });
  it("accepts the coordinating assistant's explicit confirmation bound to its reviewed digests", async () => {
    const reviewed=await call("review_onboarding",{proposal_id:"1111111111111111"});
    expect(reviewed.isError).toBeFalsy();
    const r=reviewed.structuredContent;
    expect(r.scope.locations).toEqual(["Victoria"]);
    expect(r.proposal_digest).toHaveLength(64);
    const ok=await call("confirm_onboarding",{proposal_id:r.proposal.id,proposal_digest:r.proposal_digest,scope_digest:r.scope_digest,confirmed:true});
    expect(ok.isError).toBeFalsy();
    expect(ok.structuredContent).toMatchObject({status:"confirmed",version:1,discovery_enabled:true});
  });
  it("refuses absent consent, false consent, wrong digests and identity arguments", async () => {
    const good={proposal_id:"1111111111111111",proposal_digest:"a".repeat(64),scope_digest:"c".repeat(64)};
    for(const args of [good,{...good,confirmed:false},{...good,confirmed:true,person:"other"}]) expect((await call("confirm_onboarding",args)).isError).toBe(true);
    const stale=await call("confirm_onboarding",{...good,confirmed:true,proposal_digest:"0".repeat(64)});
    expect(stale.isError).toBe(true);
    expect(stale.content[0].text).toContain("proposal_changed");
    expect((mock.log as any[]).some(x=>x.path.startsWith("/connector/chat"))).toBe(false);
  });
});

describe("discovery operations", () => {
  it("persists a typed unlimited daily allowance and rejects identity or invalid limits", async () => {
    expect((await call("get_discovery_settings")).structuredContent).toMatchObject({daily_token_ceiling:2000000});
    expect((await call("set_discovery_settings",{daily_token_ceiling:null})).structuredContent).toMatchObject({daily_token_ceiling:null});
    expect((await call("get_discovery_settings")).structuredContent).toMatchObject({daily_token_ceiling:null});
    expect((await call("discovery_status")).structuredContent.scope.daily_token_ceiling).toBeNull();
    expect((await call("set_discovery_settings",{daily_token_ceiling:0})).isError).toBe(true);
    expect((await call("set_discovery_settings",{daily_token_ceiling:null,person:"other"})).isError).toBe(true);
  });
  it("shows paused failures and queues start or explicit retry without a chat", async () => {
    const status=await call("discovery_status");
    expect(status.isError).toBeFalsy();
    expect(status.structuredContent.incidents[0]).toMatchObject({reason:"deadline_exceeded",state:"paused",notification_state:"failed"});
    expect((await call("start_discovery",{request_id:"start-one"})).structuredContent).toMatchObject({run_id:"discovery-one",state:"queued"});
    expect((await call("retry_assessment",{request_id:"retry-one",incident_id:"incident-one",posting_id:42,expected_context:"f".repeat(64)})).isError).toBeFalsy();
    const refused=await call("retry_assessment",{request_id:"retry-stale",incident_id:"incident-one",posting_id:42,expected_context:"0".repeat(64)});
    expect(refused.isError).toBe(true);
    expect(refused.content[0].text).toContain("retry_inputs_changed");
    expect((await call("start_discovery",{request_id:"x",person:"other"})).isError).toBe(true);
  });
});

describe("widgets off", () => {
  const OFF_PORT = 18944;
  let offProc: ChildProcess;
  let offClient: Client;
  beforeAll(async () => {
    offProc = spawn("node_modules/.bin/mcp-use", ["start", "--port", String(OFF_PORT)], {
      env: { ...process.env, JOBWATCH_MCP_WIDGETS: "off", JOBWATCH_CONNECTOR_TOKEN: BACKEND_TOKEN, JOBWATCH_BACKEND_URL: `http://127.0.0.1:${mock.port}`, JOBWATCH_MCP_PUBLIC_URL: `http://127.0.0.1:${OFF_PORT}` },
      stdio: "ignore",
    });
    for (let i = 0; i < 60; i++) {
      try { offClient = new Client({ name: "test", version: "1" }); await offClient.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${OFF_PORT}/mcp`))); return; } catch { await new Promise((r) => setTimeout(r, 500)); }
    }
    throw new Error("off server did not start");
  }, 60_000);
  afterAll(async () => { await offClient?.close().catch(() => {}); offProc?.kill(); });
  it("drops open_dashboard and every view, and the instructions say so", async () => {
    const { tools } = await offClient.listTools();
    expect(tools.map((t) => t.name)).not.toContain("open_dashboard");
    expect(tools.map((t) => t.name).sort()).toEqual(specs.filter((s) => s.widget !== "on_request").map((s) => s.name).sort());
    for (const t of tools) expect((t._meta as any)?.ui?.resourceUri, t.name).toBeUndefined();
    const ins = offClient.getInstructions() ?? "";
    expect(ins).toContain("opens no widgets");
    expect(ins).not.toContain("open_dashboard");
    expect(ins).toContain(`offers ${specs.filter((s) => s.access === "model" && s.widget !== "on_request").length} tools`);
  });
});

// Last: it closes the mock backend.
describe("failure", () => {
  it("reports a generic error without secrets when the backend is down", async () => {
    mock.server.close(); mock.server.closeAllConnections();
    const r = await call("jobs_overview", {});
    expect(r.isError).toBe(true);
    expect(JSON.stringify(r)).not.toContain(BACKEND_TOKEN);
    expect(r.content[0].text).toContain("not reachable");
  });
});
