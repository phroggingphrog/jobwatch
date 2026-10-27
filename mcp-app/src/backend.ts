// Thin HTTP client for the Python connector front (pipeline/agentic/connector_http.py).
// All safety logic (digest check, single-use approvals, per-person data) lives in Python; this only forwards.
export class BackendError extends Error {
  code: string;
  status: number;
  constructor(code: string, status: number) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

export interface BackendConfig {
  url: string;
  token: string;
}

export function backendConfig(env = process.env): BackendConfig {
  const token = env.JOBWATCH_CONNECTOR_TOKEN ?? "";
  if (token.length < 32) throw new Error("JOBWATCH_CONNECTOR_TOKEN (32+ chars) is required");
  const url = env.JOBWATCH_BACKEND_URL ?? "http://127.0.0.1:18940";
  const u = new URL(url);
  if (!["127.0.0.1", "localhost", "::1", "[::1]"].includes(u.hostname)) {
    throw new Error("JOBWATCH_BACKEND_URL must be loopback");
  }
  return { url: url.replace(/\/$/, ""), token };
}

export async function call<T>(
  cfg: BackendConfig,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(cfg.url + path, {
    method,
    redirect: "error",
    signal: AbortSignal.timeout(120_000),
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    // Only the fixed error code from the backend is surfaced, never a body or a token.
    let code = `backend_${res.status}`;
    try {
      const j = (await res.json()) as { error?: unknown };
      if (typeof j.error === "string" && /^[a-z_0-9]{1,64}$/.test(j.error)) code = j.error;
    } catch {
      /* keep generic code */
    }
    throw new BackendError(code, res.status);
  }
  return (await res.json()) as T;
}
