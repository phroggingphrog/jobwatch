// Mock of pipeline/agentic/connector_http.py with fake data. Never touches real data. Used by tests and screenshots.
import http from "node:http";

export const BACKEND_TOKEN = "b".repeat(40);
export const DIGEST = "d".repeat(64);
export const SHOWN = "e".repeat(64);
export const OAUTH_TOKEN = "oauth-access-token-from-python";

export function startMock(port = 0) {
  const log = [];
  const jobs = {
    1: { posting_id: 1, found: true, employer: "Acme Pty Ltd", title: "Data Analyst", location: "Melbourne VIC", ad_url: "https://example.com/ad/1", score: 4.2, why_it_fits: "Matches the SQL and reporting work in your profile.", pros: ["SQL and dashboards", "Hybrid, 3 days"], cons: ["Contract, 6 months"], state: "draft ready", state_detail: "", documents_ready: true, draft_version: 2, can_submit: true },
    2: { posting_id: 2, found: true, employer: "Globex", title: "BI Developer", location: "Sydney NSW", ad_url: null, score: 3.6, why_it_fits: null, pros: [], cons: [], state: "drafting", state_detail: "", documents_ready: false, draft_version: null, can_submit: false },
    4: { posting_id: 4, found: true, employer: "Hooli", title: "Data Engineer", location: null, ad_url: null, score: 3.9, state: "draft ready", state_detail: "", documents_ready: true, draft_version: 1, can_submit: false },
    3: { posting_id: 3, found: true, employer: "Initech", title: "Reporting Analyst", location: null, ad_url: null, score: null, state: "outcome unknown", state_detail: "Outcome unknown; retries are paused.", documents_ready: true, draft_version: 1, can_submit: false },
  };
  let queued = 0;
  let pending = null;
  const server = http.createServer(async (req, res) => {
    const send = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
    // public OAuth paths: Python serves these without any bearer (the TypeScript server must not forward its own)
    const early = new URL(req.url, "http://x");
    if (["/authorize", "/token", "/register", "/revoke", "/oauth/consent", "/.well-known/oauth-protected-resource"].includes(early.pathname)) {
      const raw = []; for await (const c of req) raw.push(c);
      log.push({ method: req.method, path: early.pathname + early.search, auth: req.headers.authorization ?? null, body: Buffer.concat(raw).toString(), type: req.headers["content-type"] ?? null });
      if (early.pathname === "/authorize") { res.writeHead(302, { location: "https://jobwatch.example.test/oauth/consent?txn=abc" }); return res.end(); }
      return send(200, { proxied: early.pathname, method: req.method });
    }
    if (req.method === "POST" && early.pathname === "/connector/oauth/verify" && req.headers.authorization === `Bearer ${BACKEND_TOKEN}`) {
      const raw = []; for await (const c of req) raw.push(c);
      const { token } = JSON.parse(Buffer.concat(raw).toString());
      log.push({ method: "POST", path: "/connector/oauth/verify" });
      return send(200, token === OAUTH_TOKEN ? { valid: true, person: "owner", expires_at: Math.floor(Date.now() / 1000) + 600 } : { valid: false });
    }
    if (req.headers.authorization !== `Bearer ${BACKEND_TOKEN}`) return send(401, { detail: "authentication_required" });
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
    const url = new URL(req.url, "http://x");
    log.push({ method: req.method, path: url.pathname, body });
    let m;
    if (req.method === "GET" && url.pathname === "/connector/overview") {
      const rows = Object.values(jobs).map((j) => ({ posting_id: j.posting_id, employer: j.employer, title: j.title, score: j.score ?? null, state: j.state, detail: j.state_detail }));
      return send(200, { view: "list", counts: { needs_you: 2, needs_info: 0, outcome_unknown: 1, submitted: 0 }, jobs: rows });
    }
    if (req.method === "GET" && (m = url.pathname.match(/^\/connector\/jobs\/(\d+)$/))) {
      const j = jobs[m[1]] ?? { posting_id: Number(m[1]), found: false };
      return send(200, { job: j });
    }
    if (req.method === "GET" && (m = url.pathname.match(/^\/connector\/jobs\/(\d+)\/review$/))) {
      const j = jobs[m[1]];
      if (!j) return send(200, { review: { posting_id: Number(m[1]), found: false, ready: false, answers: [], documents: [] }, submit_digest: null });
      const base = { posting_id: j.posting_id, found: true, employer: j.employer, title: j.title, ad_url: j.ad_url, state: j.state, answers: [], documents: [] };
      if (j.posting_id === 1) return send(200, { review: { ...base, ready: true, shown_hash: SHOWN,
        answers: [
          { question: "Full name", answer: "Alex Example", source: "profile" },
          { question: "Right to work in Australia?", answer: "Yes", source: "profile" },
          { question: "Salary expectation", answer: "$85,000", source: "saved_answer" },
          { question: "Why this role", answer: "I enjoy turning messy reporting data into dashboards people trust, and this role is mostly that.", source: "agent_draft" },
        ], documents: [{ role: "cv", label: "CV", file: "cv.pdf", sha256: "a1b2c3d4e5f6" }, { role: "letter", label: "Cover letter", file: "letter.pdf", sha256: "f6e5d4c3b2a1" }] }, submit_digest: DIGEST });
      if (j.posting_id === 4) return send(200, { review: { ...base, ready: false, reason: "edited_in_browser" }, submit_digest: null });
      return send(200, { review: { ...base, ready: false, reason: j.posting_id === 2 ? "not_prepared" : "not_ready" }, submit_digest: null });
    }
    if (req.method === "GET" && (m = url.pathname.match(/^\/connector\/jobs\/(\d+)\/status$/))) {
      const j = jobs[m[1]];
      return send(200, { posting_id: Number(m[1]), state: j ? j.state : "not started", ...(j?.state === "outcome unknown" ? { message: j.state_detail } : {}) });
    }
    if (req.method === "POST" && (m = url.pathname.match(/^\/connector\/jobs\/(\d+)\/(prepare|revise)$/))) {
      pending = { interaction_id: "i-1", binding: "bind-1" };
      return send(200, { data: { view: "work", posting_id: Number(m[1]), thread_id: "t", status: "awaiting_approval", interaction_id: "i-1", operation: "prepare_application", summary: `Jobwatch wants to prepare application for job ${m[1]}. This may use paid model calls and save drafts. It will not submit.` }, meta: { binding: "bind-1" } });
    }
    if (req.method === "POST" && url.pathname === "/connector/decide") {
      if (!pending || body.interaction_id !== pending.interaction_id || body.binding !== pending.binding) return send(400, { error: "approval_not_found" });
      pending = null;
      return send(200, { data: { view: "work", status: "complete", answer: body.decision === "approve" ? "Prepared. The draft is ready for your review." : "", decision: body.decision }, meta: {} });
    }
    if (req.method === "POST" && url.pathname === "/connector/chat/start") {
      if (/which city/i.test(body.message)) return send(200, { type: "assistant_message", status: "needs_answer", thread_id: "thread-1", questions: [{ question: "Which city do you want to work in?", options: ["Melbourne", "Sydney"] }], note: "Show the question(s) to the person and wait for their answer.", tools: [] });
      if (/submit/i.test(body.message)) return send(200, { type: "assistant_message", status: "complete", thread_id: "thread-2", answer: "Understood.", declined: ["submit_application"], todos: [], tools: [] });
      return send(200, { type: "assistant_message", status: "complete", thread_id: "thread-3", answer: "Two jobs need you.", todos: [], tools: ["jobs_overview"] });
    }
    if (req.method === "POST" && url.pathname === "/connector/chat/continue") {
      if (body.thread_id === "thread-1") return send(200, { type: "assistant_message", status: "complete", thread_id: "thread-1", answer: `Letter tailored for ${body.message}.`, todos: [], tools: [] });
      return send(400, { error: "invalid_request" });
    }
    if (req.method === "POST" && (m = url.pathname.match(/^\/connector\/jobs\/(\d+)\/submit$/))) {
      if (body.confirm_digest !== DIGEST) return send(400, { error: "submit_digest_mismatch" });
      if (body.shown_hash !== SHOWN) return send(400, { error: "review_changed" });
      if (queued) return send(400, { error: "submit_already_queued" });
      queued += 1;
      return send(200, { view: "submit", posting_id: Number(m[1]), status: "queued" });
    }
    return send(404, { detail: "nf" });
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve({ server, log, port: server.address().port, queuedCount: () => queued })));
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  const { port } = await startMock(Number(process.env.MOCK_PORT ?? 18941));
  console.log("mock backend on", port);
}
