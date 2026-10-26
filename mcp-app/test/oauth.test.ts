// OAuth login on the TypeScript server: public paths are proxied to Python (no caller bearer forwarded), the metadata
// names the PUBLIC origin, and bearers are checked as: static token (constant time) OR an OAuth token Python vouches for.
import { spawn, type ChildProcess } from "node:child_process";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
// @ts-expect-error plain JS helper
import { startMock, BACKEND_TOKEN, OAUTH_TOKEN } from "./mock-backend.mjs";

const MCP_TOKEN = "a".repeat(40);
const PUBLIC = "https://jobwatch.example.test";
const PORT_ON = 18944;
const PORT_OFF = 18945;
let on: ChildProcess;
let off: ChildProcess;
let mock: { server: import("node:http").Server; log: any[]; port: number };

const start = (port: number, extra: Record<string, string>) =>
  spawn("node_modules/.bin/mcp-use", ["start", "--port", String(port)], {
    env: { ...process.env, JOBWATCH_MCP_TOKEN: MCP_TOKEN, JOBWATCH_CONNECTOR_TOKEN: BACKEND_TOKEN, JOBWATCH_BACKEND_URL: `http://127.0.0.1:${mock.port}`, ...extra },
    stdio: "ignore",
  });
const origin = (port: number) => `http://127.0.0.1:${port}`;
const ready = async (port: number) => {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`${origin(port)}/.well-known/oauth-authorization-server`);
      if (r.status === 200) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("server did not start");
};
const rpc = (port: number, token?: string) =>
  fetch(`${origin(port)}/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: '{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
  });

beforeAll(async () => {
  mock = await startMock(0);
  on = start(PORT_ON, { JOBWATCH_MCP_OAUTH: "1", JOBWATCH_MCP_PUBLIC_URL: PUBLIC, MCP_URL: `${PUBLIC}/mcp` });
  off = start(PORT_OFF, {});
  await Promise.all([ready(PORT_ON), ready(PORT_OFF)]);
}, 90_000);
afterAll(() => {
  on?.kill();
  off?.kill();
  mock?.server.close();
});

describe("OAuth switched on", () => {
  it("metadata names the public origin, not the local address", async () => {
    const meta = await (await fetch(`${origin(PORT_ON)}/.well-known/oauth-authorization-server`)).json();
    expect(meta.issuer).toBe(PUBLIC);
    for (const k of ["authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"]) expect(meta[k].startsWith(PUBLIC + "/")).toBe(true);
    expect(meta.code_challenge_methods_supported).toEqual(["S256"]);
    const res = await (await fetch(`${origin(PORT_ON)}/.well-known/oauth-protected-resource/mcp`)).json();
    expect(res.resource).toBe(`${PUBLIC}/mcp`);
    expect(res.authorization_servers).toEqual([PUBLIC]);
  });

  it("proxies authorize, token, register, revoke and the consent page to Python, without any bearer", async () => {
    mock.log.length = 0;
    const authz = await fetch(`${origin(PORT_ON)}/authorize?response_type=code&client_id=c&state=s`, { redirect: "manual", headers: { authorization: `Bearer ${MCP_TOKEN}` } });
    expect(authz.status).toBe(302);
    expect(authz.headers.get("location")).toContain("/oauth/consent?txn=abc");
    const form = "grant_type=authorization_code&code=x";
    const tok = await fetch(`${origin(PORT_ON)}/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: form });
    expect(await tok.json()).toEqual({ proxied: "/token", method: "POST" });
    const reg = await fetch(`${origin(PORT_ON)}/register`, { method: "POST", headers: { "content-type": "application/json" }, body: '{"redirect_uris":["https://x/cb"]}' });
    expect((await reg.json()).proxied).toBe("/register");
    expect((await fetch(`${origin(PORT_ON)}/revoke`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "token=t&client_id=c" })).status).toBe(200);
    expect((await fetch(`${origin(PORT_ON)}/oauth/consent?txn=abc`)).status).toBe(200);
    const consent = await fetch(`${origin(PORT_ON)}/oauth/consent`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "txn=abc&passphrase=p" });
    expect(consent.status).toBe(200);
    const seen = mock.log.filter((e) => e.auth !== undefined);
    expect(seen.length).toBe(6);
    for (const e of seen) expect(e.auth).toBeNull();                              // the caller's bearer is never forwarded
    expect(seen.find((e) => e.path === "/token").body).toBe(form);
    expect(seen.find((e) => e.path === "/token").type).toContain("application/x-www-form-urlencoded");
  });

  it("proxies nothing else of Python, and no data-plane path", async () => {
    for (const p of ["/connector/overview", "/connector/oauth/verify", "/connector/jobs/1/review"]) {
      const r = await fetch(`${origin(PORT_ON)}${p}`);
      expect([401, 404]).toContain(r.status);
      expect(await r.text()).not.toContain("Acme");
    }
    mock.log.length = 0;
    await fetch(`${origin(PORT_ON)}/token`);                                        // wrong method for a proxied path
    expect(mock.log.some((e) => e.path === "/token")).toBe(false);
  });

  it("refuses an oversized body without forwarding it", async () => {
    mock.log.length = 0;
    const r = await fetch(`${origin(PORT_ON)}/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "a=" + "x".repeat(70_000) });
    expect(r.status).toBe(413);
    expect(mock.log.some((e) => e.path === "/token")).toBe(false);
  });

  it("accepts the static token and an OAuth token Python vouches for; rejects everything else", async () => {
    expect((await rpc(PORT_ON, MCP_TOKEN)).status).toBe(200);
    expect((await rpc(PORT_ON, OAUTH_TOKEN)).status).toBe(200);
    expect((await rpc(PORT_ON, "z".repeat(40))).status).toBe(401);
    expect((await rpc(PORT_ON, "expired-or-revoked-token")).status).toBe(401);
    expect((await rpc(PORT_ON)).status).toBe(401);
  });

  it("an OAuth token drives the same tools as the static one", async () => {
    const c = new Client({ name: "t", version: "1" });
    await c.connect(new StreamableHTTPClientTransport(new URL(`${origin(PORT_ON)}/mcp`), { requestInit: { headers: { Authorization: `Bearer ${OAUTH_TOKEN}` } } }));
    const r: any = await c.callTool({ name: "jobs_overview", arguments: {} });
    expect(r.structuredContent.jobs).toHaveLength(4);
    await c.close();
  });

  it("asks Python for each OAuth bearer and never for the static one", async () => {
    mock.log.length = 0;
    await rpc(PORT_ON, MCP_TOKEN);
    expect(mock.log.some((e) => e.path === "/connector/oauth/verify")).toBe(false);
    await rpc(PORT_ON, "some-unknown-token");
    expect(mock.log.filter((e) => e.path === "/connector/oauth/verify").length).toBeGreaterThanOrEqual(1);
  });
});

describe("OAuth off (the default)", () => {
  it("does not proxy and does not ask Python to verify anything", async () => {
    mock.log.length = 0;
    for (const p of ["/authorize", "/register"]) expect((await fetch(`${origin(PORT_OFF)}${p}`, { redirect: "manual" })).status).toBe(404);
    expect((await fetch(`${origin(PORT_OFF)}/token`, { method: "POST", body: "x" })).status).toBe(404);
    expect((await rpc(PORT_OFF, OAUTH_TOKEN)).status).toBe(401);                   // an OAuth token means nothing here
    expect((await rpc(PORT_OFF, MCP_TOKEN)).status).toBe(200);
    expect(mock.log.length).toBe(0);
  });
});

describe("configuration", () => {
  it("refuses to start half-configured", async () => {
    for (const extra of [{ JOBWATCH_MCP_OAUTH: "1" }, { JOBWATCH_MCP_OAUTH: "1", JOBWATCH_MCP_PUBLIC_URL: "http://example.com" }, { JOBWATCH_MCP_OAUTH: "1", JOBWATCH_MCP_PUBLIC_URL: "https://x.test/path" }]) {
      const p = start(18946, extra);
      const code = await new Promise<number | null>((resolve) => { p.on("exit", resolve); setTimeout(() => { p.kill(); resolve(-1); }, 15_000); });
      expect(code).not.toBe(-1);
      expect(code).not.toBe(0);
    }
  }, 60_000);
});
