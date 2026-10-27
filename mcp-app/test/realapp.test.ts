// The full chain on a realistic filled application: MCP client -> TypeScript server -> Python JSON front -> real fill,
// real browser page, real native review API. Skipped unless JOBWATCH_REAL_APP_TEST=1 (it starts Chromium and Python).
// The Python side runs in a temp dir under /tmp and never presses an employer Submit.
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

const RUN = process.env.JOBWATCH_REAL_APP_TEST === "1";
const PY = process.env.JOBWATCH_PYTHON ?? "python3";
const REPO = new URL("../..", import.meta.url).pathname;
const MCP_TOKEN = "m".repeat(40);
const PORT = 18947;
let py: ChildProcess;
let ts: ChildProcess;
let client: Client;
let backend: { connector: string; connector_token: string; native: string };
let lines: string[] = [];
const editForm = async (name: string, value: string) => {
  const before = lines.length;
  py.stdin!.write(JSON.stringify({ edit: name, value }) + "\n");
  for (let i = 0; i < 100 && !lines.slice(before).some((l) => l.includes("edited")); i++) await new Promise((r) => setTimeout(r, 100));
  expect(lines.slice(before).some((l) => l.includes("edited"))).toBe(true);
};
const call = (name: string, args: Record<string, unknown> = {}) => client.callTool({ name, arguments: args }) as Promise<any>;
const modelVisible = (r: any) => JSON.stringify({ content: r.content, structuredContent: r.structuredContent });

beforeAll(async () => {
  if (!RUN) return;
  const root = mkdtempSync("/tmp/opencode/realapp-ts-");
  py = spawn(PY, ["-m", "tests.realapp", "serve", "--root", root, "--connector-port", "18953", "--native-port", "18954"], { cwd: REPO, stdio: ["pipe", "pipe", "inherit"] });
  backend = await new Promise((resolve, reject) => {
    let buf = "";
    py.stdout!.on("data", (d) => { lines.push(...String(d).split("\n")); buf += d; const line = buf.split("\n").find((l) => l.startsWith("{")); if (line) resolve(JSON.parse(line)); });
    py.on("exit", (c) => reject(new Error("python harness exited " + c)));
    setTimeout(() => reject(new Error("python harness timeout")), 90_000);
  });
  ts = spawn("node_modules/.bin/mcp-use", ["start", "--port", String(PORT)], {
    env: { ...process.env, JOBWATCH_MCP_TOKEN: MCP_TOKEN, JOBWATCH_CONNECTOR_TOKEN: backend.connector_token, JOBWATCH_BACKEND_URL: backend.connector },
    stdio: "ignore",
  });
  for (let i = 0; i < 60; i++) {
    try {
      client = new Client({ name: "real", version: "1" });
      await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${PORT}/mcp`), { requestInit: { headers: { Authorization: `Bearer ${MCP_TOKEN}` } } }));
      return;
    } catch { await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error("ts server did not start");
}, 180_000);
afterAll(async () => {
  await client?.close().catch(() => {});
  ts?.kill();
  py?.kill();
});

describe.skipIf(!RUN)("real filled application through the TypeScript server", () => {
  it("overview -> detail -> review -> submit queued -> second refused -> edit -> review changes -> old hash refused", async () => {
    const ov = await call("jobs_overview", {});
    expect(ov.structuredContent.jobs[0]).toMatchObject({ posting_id: 1, employer: "Acme Pty Ltd", state: "draft ready" });
    const detail = await call("job_detail", { posting_id: 1 });
    expect(detail.structuredContent).toMatchObject({ employer: "Acme Pty Ltd", can_submit: true });

    const rv = await call("review_submission", { posting_id: 1 });
    const { submit_digest, shown_hash } = rv._meta;
    expect(submit_digest).toMatch(/^[0-9a-f]{64}$/);
    expect(modelVisible(rv)).not.toContain(submit_digest);
    expect(modelVisible(rv)).not.toContain(shown_hash);
    const answers = Object.fromEntries(rv.structuredContent.answers.map((a: any) => [a.question, a.answer]));
    expect(answers["Why are you suitable for this role?"]).toContain("I would start by learning how your reporting is produced");
    expect(rv.structuredContent.documents.map((d: any) => d.file)).toEqual(["Alex_Example_CV_2026.pdf", "Cover letter - Acme Pty Ltd.pdf"]);

    const bad = await call("submit_reviewed", { posting_id: 1, confirm_digest: submit_digest, shown_hash: "f".repeat(64) });
    expect(bad.isError).toBe(true);
    expect(bad.content[0].text).toContain("review_changed");
    const ok = await call("submit_reviewed", { posting_id: 1, confirm_digest: submit_digest, shown_hash });
    expect(ok.structuredContent).toEqual({ posting_id: 1, status: "queued" });
    const again = await call("submit_reviewed", { posting_id: 1, confirm_digest: submit_digest, shown_hash });
    expect(again.isError).toBe(true);

    // the owner edits the live form; the review follows it, with a new hash and digest
    const edited = "I enjoy turning messy reporting data into dashboards people trust, and this role is mostly that.";
    await editForm("motivation", edited);
    const rv2 = await call("review_submission", { posting_id: 1 });
    const fresh = Object.fromEntries(rv2.structuredContent.answers.map((a: any) => [a.question, a.answer]));
    expect(fresh["Why are you suitable for this role?"]).toBe(edited);
    expect(rv2._meta?.shown_hash).not.toBe(shown_hash);
    expect(rv2._meta?.submit_digest).not.toBe(submit_digest);
    // the old hash and digest stay refused
    const stale = await call("submit_reviewed", { posting_id: 1, confirm_digest: submit_digest, shown_hash });
    expect(stale.isError).toBe(true);
    const mixed = await call("submit_reviewed", { posting_id: 1, confirm_digest: rv2._meta.submit_digest, shown_hash });
    expect(mixed.isError).toBe(true);
  }, 120_000);
});
