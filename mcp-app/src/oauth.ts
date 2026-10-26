// OAuth login for the connector. The consent page, code/token issuing, refresh and revocation all stay in the Python
// service (pipeline/agentic/connector_http.py, JOBWATCH_CONNECTOR_OAUTH=1). This file only
//   * proxies the public OAuth paths to Python (the public URL origin is this server's, so the metadata names it), and
//   * asks Python whether a bearer is an OAuth access token it issued.
// The static JOBWATCH_MCP_TOKEN keeps working beside it (checked here, constant time). Off unless JOBWATCH_MCP_OAUTH=1.
import { timingSafeEqual } from "node:crypto";
import type { Context } from "hono";
import type { BackendConfig } from "./backend.js";

export interface OAuthConfig {
  /** Public origin of THIS server, e.g. https://jobwatch.example.com (the issuer and the resource origin). */
  publicUrl: URL;
}

/** null when OAuth login is off (the default). Half-configured is an error, never a silent downgrade. */
export function oauthConfig(env = process.env): OAuthConfig | null {
  if (env.JOBWATCH_MCP_OAUTH !== "1") return null;
  const raw = env.JOBWATCH_MCP_PUBLIC_URL ?? "";
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    throw new Error("JOBWATCH_MCP_PUBLIC_URL (the public https origin of this server) is required when JOBWATCH_MCP_OAUTH=1");
  }
  const local = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(u.hostname);
  if ((u.protocol !== "https:" && !(u.protocol === "http:" && local)) || (u.pathname !== "/" && u.pathname !== "") || u.search || u.hash) {
    throw new Error("JOBWATCH_MCP_PUBLIC_URL must be an https origin with no path (http only for loopback tests)");
  }
  return { publicUrl: new URL(u.origin) };
}

export const same = (a: string, b: string) => {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

/** Authorization-server metadata, naming the public origin (mcp-use serves this document itself from the provider). */
export function authorizationServerMetadata(origin: string) {
  return {
    issuer: origin,
    authorization_endpoint: `${origin}/authorize`,
    token_endpoint: `${origin}/token`,
    registration_endpoint: `${origin}/register`,
    revocation_endpoint: `${origin}/revoke`,
    scopes_supported: ["jobwatch"],
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    token_endpoint_auth_methods_supported: ["none", "client_secret_post"],
    revocation_endpoint_auth_methods_supported: ["none", "client_secret_post"],
    code_challenge_methods_supported: ["S256"],
  };
}

export type Verdict = { valid: true; expiresAt: number } | { valid: false };

/** Ask Python whether `token` is an unexpired OAuth access token it issued. Any failure is "not valid". */
export async function verifyWithBackend(cfg: BackendConfig, token: string): Promise<Verdict> {
  if (!token || token.length > 512) return { valid: false };
  try {
    const res = await fetch(`${cfg.url}/connector/oauth/verify`, {
      method: "POST",
      redirect: "error",
      signal: AbortSignal.timeout(10_000),
      headers: { Authorization: `Bearer ${cfg.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) return { valid: false };
    const j = (await res.json()) as { valid?: unknown; expires_at?: unknown };
    return j.valid === true && typeof j.expires_at === "number" ? { valid: true, expiresAt: Math.floor(j.expires_at) } : { valid: false };
  } catch {
    return { valid: false };
  }
}

// ---- the proxy: only these exact paths, only these methods; nothing else of Python is reachable from outside ---------
export const PROXIED: ReadonlyArray<{ method: "GET" | "POST" | "OPTIONS"; path: string }> = [
  { method: "GET", path: "/.well-known/oauth-protected-resource" },
  { method: "GET", path: "/authorize" },
  { method: "OPTIONS", path: "/authorize" },
  { method: "POST", path: "/token" },
  { method: "OPTIONS", path: "/token" },
  { method: "POST", path: "/register" },
  { method: "OPTIONS", path: "/register" },
  { method: "POST", path: "/revoke" },
  { method: "OPTIONS", path: "/revoke" },
  { method: "GET", path: "/oauth/consent" },
  { method: "POST", path: "/oauth/consent" },
];

const MAX_BODY = 64 * 1024;
const FORWARD_REQUEST = ["content-type", "accept", "accept-language", "user-agent"];
const FORWARD_RESPONSE = ["content-type", "location", "cache-control", "pragma", "www-authenticate", "access-control-allow-origin",
  "access-control-allow-methods", "access-control-allow-headers", "access-control-max-age", "content-security-policy"];

/** Forward one request to Python without the caller's Authorization header and without following redirects. */
export async function proxy(cfg: BackendConfig, c: Context): Promise<Response> {
  const url = new URL(c.req.url);
  const headers = new Headers();
  for (const h of FORWARD_REQUEST) {
    const v = c.req.header(h);
    if (v) headers.set(h, v);
  }
  let body: ArrayBuffer | undefined;
  if (c.req.method !== "GET" && c.req.method !== "OPTIONS") {
    body = await c.req.arrayBuffer();
    if (body.byteLength > MAX_BODY) return c.json({ error: "invalid_request", error_description: "request too large" }, 413);
  }
  let res: Response;
  try {
    res = await fetch(cfg.url + url.pathname + url.search, {
      method: c.req.method,
      headers,
      body,
      redirect: "manual",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return c.json({ error: "temporarily_unavailable" }, 503);
  }
  const out = new Headers();
  for (const h of FORWARD_RESPONSE) {
    const v = res.headers.get(h);
    if (v) out.set(h, v);
  }
  out.set("cache-control", out.get("cache-control") ?? "no-store");
  return new Response(res.status === 204 || res.status === 304 ? null : await res.arrayBuffer(), { status: res.status, headers: out });
}
