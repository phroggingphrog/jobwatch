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
    expect(Object.keys(by).sort()).toEqual(["career_ops_continue_chat", "career_ops_start_chat", "decide", "job_detail", "jobs_overview", "prepare_application", "review_submission", "revise_application", "submit_reviewed", "task_status"]);
    for (const n of ["jobs_overview", "job_detail", "task_status", "review_submission"]) expect(by[n].annotations?.readOnlyHint).toBe(true);
    expect(by.submit_reviewed.annotations).toMatchObject({ destructiveHint: true, openWorldHint: true, readOnlyHint: false });
    expect((by.submit_reviewed._meta as any).ui.visibility).toEqual(["app"]);
    expect((by.decide._meta as any).ui.visibility).toEqual(["app"]);
    for (const n of ["jobs_overview", "job_detail", "task_status", "review_submission", "prepare_application", "revise_application"]) {
      expect((by[n]._meta as any).ui.resourceUri).toMatch(/^ui:\/\//);
      expect(by[n].outputSchema).toBeTruthy();
    }
    expect(JSON.stringify(by.submit_reviewed.inputSchema)).toContain("confirm_digest");
  });
});

describe("read tools", () => {
  it("jobs_overview returns matching structured content", async () => {
    const r = await call("jobs_overview", {});
    expect(r.isError).toBeFalsy();
    expect(r.structuredContent.jobs).toHaveLength(4);
    expect(r.structuredContent.counts.needs_you).toBe(2);
    expect(r.content[0].text).toContain("Acme Pty Ltd");
  });
  it("job_detail and task_status", async () => {
    const d = await call("job_detail", { posting_id: 1 });
    expect(d.structuredContent).toMatchObject({ found: true, can_submit: true, state: "draft ready" });
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
  it("prepare raises an approval with the binding only in _meta; decide needs it", async () => {
    const p = await call("prepare_application", { posting_id: 2, instructions: "short letter" });
    expect(p.structuredContent.approval).toMatchObject({ interaction_id: "i-1", operation: "prepare_application" });
    expect(modelVisible(p)).not.toContain("bind-1");
    expect(p._meta.binding).toBe("bind-1");
    const bad = await call("decide", { posting_id: 2, interaction_id: "i-1", decision: "approve", binding: "nope" });
    expect(bad.isError).toBe(true);
    const ok = await call("decide", { posting_id: 2, interaction_id: "i-1", decision: "approve", binding: "bind-1" });
    expect(ok.structuredContent).toMatchObject({ state: "complete", decision: "approve" });
    const again = await call("decide", { posting_id: 2, interaction_id: "i-1", decision: "approve", binding: "bind-1" });
    expect(again.isError).toBe(true);
  });
  it("revise needs changes", async () => {
    const r = await client.callTool({ name: "revise_application", arguments: { posting_id: 1, changes: "" } }).catch(() => ({ isError: true }));
    expect((r as any).isError).toBe(true);
  });
});

describe("chat tools", () => {
  it("a plain request goes to Python and comes back with an opaque thread id", async () => {
    const r = await call("career_ops_start_chat", { message: "What needs me?" });
    expect(r.isError).toBeFalsy();
    expect(r.structuredContent).toMatchObject({ status: "complete", thread_id: "thread-3", answer: "Two jobs need you." });
    expect(r.content[0].text).toContain("Two jobs need you.");
    expect((mock.log as any[]).filter((e) => e.path === "/connector/chat/start").at(-1).body).toEqual({ message: "What needs me?" });
  });
  it("a question for the person is plain content with options, and never answered here", async () => {
    const r = await call("career_ops_start_chat", { message: "Which city should I tailor for?" });
    expect(r.structuredContent.status).toBe("needs_answer");
    expect(r.structuredContent.questions).toEqual([{ question: "Which city do you want to work in?", options: ["Melbourne", "Sydney"] }]);
    const t = r.content[0].text;
    expect(t).toContain("Which city do you want to work in?");
    expect(t).toContain("Melbourne | Sydney");
    expect(t).toMatch(/do not answer for them/i);
    expect(t).toContain("career_ops_continue_chat");
    const sent = (mock.log as any[]).filter((e) => e.path.startsWith("/connector/chat"));
    expect(sent.at(-1).path).toBe("/connector/chat/start");                // nothing was sent on the person's behalf
  });
  it("the person's answer goes back through continue_chat on the same thread", async () => {
    const r = await call("career_ops_continue_chat", { thread_id: "thread-1", message: "Melbourne" });
    expect(r.structuredContent).toMatchObject({ status: "complete", answer: "Letter tailored for Melbourne." });
    expect((mock.log as any[]).filter((e) => e.path === "/connector/chat/continue").at(-1).body).toEqual({ thread_id: "thread-1", message: "Melbourne" });
  });
  it("a declined approval is reported, not hidden", async () => {
    const r = await call("career_ops_start_chat", { message: "Please submit job 1" });
    expect(r.structuredContent.declined).toEqual(["submit_application"]);
    expect(r.content[0].text).toContain("nothing was run or sent");
  });
  it("refuses bad input before calling Python and surfaces only the fixed backend code", async () => {
    const before = (mock.log as any[]).length;
    await expect(call("career_ops_continue_chat", { thread_id: "bad id!", message: "x" })).resolves.toMatchObject({ isError: true });
    await expect(call("career_ops_start_chat", { message: "" })).resolves.toMatchObject({ isError: true });
    expect((mock.log as any[]).length).toBe(before);
    const r = await call("career_ops_continue_chat", { thread_id: "unknown", message: "x" });
    expect(r.isError).toBe(true);
    expect(r.content[0].text).toBe("Jobwatch refused: invalid_request");
  });
  it("takes no person argument and is not app-only", async () => {
    const { tools } = await client.listTools();
    for (const n of ["career_ops_start_chat", "career_ops_continue_chat"]) {
      const t = tools.find((x) => x.name === n)!;
      expect(JSON.stringify(t.inputSchema)).not.toMatch(/person|user/i);
      expect((t._meta as any)?.ui?.visibility).toBeUndefined();
      expect(t.annotations?.destructiveHint).toBe(false);
    }
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
