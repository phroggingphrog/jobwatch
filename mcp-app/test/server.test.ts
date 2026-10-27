import { spawn, type ChildProcess } from "node:child_process";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
// @ts-expect-error plain JS helper
import { startMock, DIGEST, SHOWN, BACKEND_TOKEN } from "./mock-backend.mjs";

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
  it("has the expected tools, hints, views and visibility", async () => {
    const { tools } = await client.listTools();
    const by = Object.fromEntries(tools.map((t) => [t.name, t]));
    expect(Object.keys(by).sort()).toEqual(["application_detail", "applications_overview", "assessment_detail", "answer_onboarding_question", "confirm_onboarding", "decide", "discovery_status", "get_discovery_settings", "job_detail", "jobs_overview", "onboarding_status", "prepare_application", "retry_assessment", "review_onboarding", "review_submission", "revise_application", "set_discovery_settings", "start_discovery", "start_onboarding", "submit_reviewed", "task_status", "update_onboarding", "refresh_shortlist"].sort());
    for (const n of ["jobs_overview", "job_detail", "task_status", "review_submission"]) expect(by[n].annotations?.readOnlyHint).toBe(true);
    expect(by.submit_reviewed.annotations).toMatchObject({ destructiveHint: true, openWorldHint: true, readOnlyHint: false });
    expect((by.submit_reviewed._meta as any).ui.visibility).toEqual(["app"]);
    expect((by.decide._meta as any).ui.visibility).toEqual(["app"]);
    for (const n of ["jobs_overview", "job_detail", "task_status", "review_submission", "prepare_application", "revise_application", "get_discovery_settings", "discovery_status", "applications_overview", "application_detail"]) {
      expect((by[n]._meta as any).ui.resourceUri).toMatch(/^ui:\/\//);
      expect(by[n].outputSchema).toBeTruthy();
    }
    expect(JSON.stringify(by.submit_reviewed.inputSchema)).toContain("confirm_digest");
  });
  it("publishes the settings app as an MCP resource for the existing client", async () => {
    const { tools } = await client.listTools();
    const settings = tools.find((tool) => tool.name === "get_discovery_settings")!;
    const uri = (settings._meta as any).ui.resourceUri as string;
    const result = await client.readResource({ uri });
    expect(result.contents[0].mimeType).toContain("profile=mcp-app");
    const html = result.contents[0].text ?? "";
    expect(html).toContain('<div id="root"');
    expect(html).toContain('<script type="module">');
    expect(html).toContain("Daily token allowance");
    expect(html).toContain("next discovery pass");
    expect(html).toContain("Assessment attempts today");
    expect(html).toContain("Retry this assessment");
    expect(html).toContain("Last successful phase:");
    expect(html).toContain("Job #");
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
    expect(modelVisible(d)).toContain("Assessment: assessed");
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
    expect(ok.structuredContent).toEqual({ posting_id: 1, status: "queued" });
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
    expect((await call("prepare_application",args)).structuredContent).toEqual(first.structuredContent);
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
    expect((await call("get_discovery_settings")).structuredContent).toEqual({daily_token_ceiling:2000000});
    expect((await call("set_discovery_settings",{daily_token_ceiling:null})).structuredContent).toEqual({daily_token_ceiling:null});
    expect((await call("get_discovery_settings")).structuredContent).toEqual({daily_token_ceiling:null});
    expect((await call("discovery_status")).structuredContent.scope.daily_token_ceiling).toBeNull();
    expect((await call("set_discovery_settings",{daily_token_ceiling:0})).isError).toBe(true);
    expect((await call("set_discovery_settings",{daily_token_ceiling:null,person:"other"})).isError).toBe(true);
  });
  it("shows paused failures and queues start or explicit retry without a chat", async () => {
    const status=await call("discovery_status");
    expect(status.isError).toBeFalsy();
    expect(status.structuredContent.incidents[0]).toMatchObject({reason:"deadline_exceeded",state:"paused",notification_state:"failed"});
    expect((await call("start_discovery",{request_id:"start-one"})).structuredContent).toEqual({run_id:"discovery-one",state:"queued"});
    expect((await call("retry_assessment",{request_id:"retry-one",incident_id:"incident-one",posting_id:42,expected_context:"f".repeat(64)})).isError).toBeFalsy();
    const refused=await call("retry_assessment",{request_id:"retry-stale",incident_id:"incident-one",posting_id:42,expected_context:"0".repeat(64)});
    expect(refused.isError).toBe(true);
    expect(refused.content[0].text).toContain("retry_inputs_changed");
    expect((await call("start_discovery",{request_id:"x",person:"other"})).isError).toBe(true);
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
