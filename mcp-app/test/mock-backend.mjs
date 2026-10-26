// Mock of pipeline/agentic/connector_http.py with fake data. Never touches real data. Used by tests and screenshots.
import http from "node:http";

export const BACKEND_TOKEN = "b".repeat(40);
export const DIGEST = "d".repeat(64);

export function startMock(port = 0) {
  const log = [];
  const jobs = {
    1: { posting_id: 1, found: true, employer: "Acme Pty Ltd", title: "Data Analyst", location: "Melbourne VIC", ad_url: "https://example.com/ad/1", score: 4.2, why_it_fits: "Matches the SQL and reporting work in your profile.", pros: ["SQL and dashboards", "Hybrid, 3 days"], cons: ["Contract, 6 months"], state: "draft ready", state_detail: "", documents_ready: true, draft_version: 2, can_submit: true },
    2: { posting_id: 2, found: true, employer: "Globex", title: "BI Developer", location: "Sydney NSW", ad_url: null, score: 3.6, why_it_fits: null, pros: [], cons: [], state: "drafting", state_detail: "", documents_ready: false, draft_version: null, can_submit: false },
    3: { posting_id: 3, found: true, employer: "Initech", title: "Reporting Analyst", location: null, ad_url: null, score: null, state: "outcome unknown", state_detail: "Outcome unknown; retries are paused.", documents_ready: true, draft_version: 1, can_submit: false },
  };
  let queued = 0;
  let pending = null;
  const server = http.createServer(async (req, res) => {
    const send = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
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
      return send(200, { job: j, submit_digest: j.can_submit ? DIGEST : null });
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
    if (req.method === "POST" && (m = url.pathname.match(/^\/connector\/jobs\/(\d+)\/submit$/))) {
      if (body.confirm_digest !== DIGEST) return send(400, { error: "submit_digest_mismatch" });
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
