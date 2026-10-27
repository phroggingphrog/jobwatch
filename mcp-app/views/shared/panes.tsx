import { useState } from "react";
import { useCallTool } from "mcp-use/react";
import { Status, safeUrl, metaString } from "./ui.js";

export interface Job {
  posting_id: number; found: boolean; employer?: string | null; title?: string | null; location?: string | null;
  ad_url?: string | null; score?: number | null; why_it_fits?: string | null; pros?: string[]; cons?: string[];
  state?: string; state_detail?: string; documents_ready?: boolean; draft_version?: number | null; can_submit?: boolean;
  assessment_state?: string | null; assessment_reason?: string | null; assessment_summary?: string | null;
}
export interface Review {
  posting_id: number; found: boolean; ready: boolean; reason?: string;
  employer?: string | null; title?: string | null; state?: string; ad_url?: string | null;
  answers: { question: string; answer: string; source: string }[];
  documents: { role: string; label: string; file: string; sha256: string }[];
}
export interface ReviewKeys { digest?: string; shown?: string }

export function JobPane({ d, onBack }: { d: Job; onBack?: () => void }) {
  const review = useCallTool("review_submission");
  const [shown, setShown] = useState<{ r: Review; keys: ReviewKeys } | null>(null);
  if (shown) return <ReviewPane r={shown.r} keys={shown.keys} onBack={() => setShown(null)} />;
  const ad = safeUrl(d.ad_url);
  return (
    <div>
      {onBack && <button type="button" className="link" onClick={onBack}>Back to jobs</button>}
      {!d.found ? <p className="empty">That job was not found.</p> : (
        <>
          <div className="head"><div>
            <h1>{d.title || "(untitled)"}</h1>
            <p className="sub">{d.employer || "Unknown employer"}{d.location ? ` · ${d.location}` : ""}</p>
          </div></div>
          <dl>
            <dt>Application</dt><dd><Status state={d.state ?? "not started"} /></dd>
            {d.assessment_state && <><dt>Assessment</dt><dd>{d.assessment_state === "current" ? "Assessed" : d.assessment_state.replaceAll("_", " ")}</dd></>}
            {d.assessment_reason && <><dt>Assessment result</dt><dd>{d.assessment_reason.replaceAll("_", " ")}</dd></>}
            {d.state_detail ? (<><dt>Detail</dt><dd>{d.state_detail}</dd></>) : null}
            <dt>Score</dt><dd>{d.score != null ? <span className="score" style={{ textAlign: "left" }}>{d.score}</span> : "Not scored"}</dd>
            <dt>Documents</dt><dd>{d.documents_ready ? `Ready${d.draft_version ? ` (draft v${d.draft_version})` : ""}` : "None ready"}</dd>
          </dl>
          {(d.assessment_summary || d.why_it_fits) && (<><h2>Assessment summary</h2><p>{d.assessment_summary || d.why_it_fits}</p></>)}
          {d.pros?.length ? (<><h2>In its favour</h2><ul className="list">{d.pros.map((t) => <li key={t}>{t}</li>)}</ul></>) : null}
          {d.cons?.length ? (<><h2>Against</h2><ul className="list">{d.cons.map((t) => <li key={t}>{t}</li>)}</ul></>) : null}
          {ad && <p style={{ marginTop: 10 }}><a className="link" href={ad} target="_blank" rel="noopener noreferrer">Open the job ad</a></p>}
          {review.error && <p className="note bad" role="alert">Could not open the review. Try again.</p>}
          {d.can_submit && (
            <div className="actions">
              <button type="button" className="btn primary" disabled={review.isPending}
                onClick={async () => {
                  try {
                    const res = await review.callTool({ posting_id: d.posting_id });
                    setShown({ r: res.structuredContent as Review, keys: { digest: metaString(res._meta, "submit_digest"), shown: metaString(res._meta, "shown_hash") } });
                  } catch { /* shown through review.error */ }
                }}>
                {review.isPending ? "Opening..." : "Review before submit"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const WHY: Record<string, string> = {
  not_prepared: "Nothing is filled in yet. Prepare the application first.",
  not_ready: "This application is not ready to submit.",
  edited_in_browser: "The form was changed after it was filled. Open the review again to see the form as it is now.",
  browser_unavailable: "Jobwatch cannot read the live application form right now. Open the application browser in Jobwatch, then review again.",
  application_changed: "The application page moved on since it was filled. Prepare it again, then review.",
  final_control_changed: "The Submit button on the page changed. Prepare the application again, then review.",
  unsupported_form_review: "This form uses controls Jobwatch cannot read back, so it cannot be reviewed here.",
  form_review_unavailable: "Jobwatch could not read the form just now. Try the review again.",
  form_review_changed: "The form changed while it was being read. Try the review again.",
  application_not_ready: "This application is not ready to submit.",
};

/** Review-before-submit: the exact form, then one primary Submit. The keys live only in props (view-only _meta), never in view state. */
export function ReviewPane({ r, keys, onBack }: { r: Review; keys: ReviewKeys; onBack?: () => void }) {
  const submit = useCallTool("submit_reviewed");
  const [result, setResult] = useState<string | null>(null);
  const [declined, setDeclined] = useState(false);
  const [failed, setFailed] = useState(false);
  const ad = safeUrl(r.ad_url);
  const employer = r.employer || "the employer";
  const canSubmit = r.found && r.ready && keys.digest && keys.shown;
  return (
    <div>
      {onBack && <button type="button" className="link" onClick={onBack}>Back</button>}
      <div className="head"><div>
        <h1>Review before submit</h1>
        <p className="sub">{r.found ? `${r.title || "(untitled)"} at ${employer}` : "That job was not found."}</p>
      </div>{r.found && <Status state={r.state ?? "not started"} />}</div>
      {r.found && r.answers.length > 0 && (
        <>
          <h2>Form answers</h2>
          <dl className="qa">{r.answers.map((a, i) => (<div key={i} className="qa-row"><dt>{a.question}</dt><dd>{a.answer || "(blank)"}</dd></div>))}</dl>
        </>
      )}
      {r.found && r.documents.length > 0 && (
        <>
          <h2>Attachments</h2>
          <ul className="rows">{r.documents.map((d) => (
            <li key={d.role}><div className="row" style={{ cursor: "default" }}>
              <span className="grow"><div className="t">{d.label}</div></span><span className="mono">{d.file}</span>
            </div></li>))}</ul>
        </>
      )}
      {ad && <p style={{ marginTop: 10 }}><a className="link" href={ad} target="_blank" rel="noopener noreferrer">Open the job ad</a></p>}
      {!canSubmit ? (
        r.found && <p className="note" role="status">{WHY[r.reason ?? "not_ready"] ?? WHY.not_ready}</p>
      ) : result ? (
        <p className="note" role="status">{result}</p>
      ) : declined ? (
        <p className="note" role="status">Not sent. Nothing was submitted.</p>
      ) : (
        <>
          <p className="note">This will send your application to {employer}.</p>
          {failed && <p className="note bad" role="alert">Not submitted. The form may have changed; open the review again.</p>}
          <div className="actions">
            <button type="button" className="btn primary" disabled={submit.isPending}
              onClick={async () => {
                setFailed(false);
                try {
                  const res = await submit.callTool({ posting_id: r.posting_id, confirm_digest: keys.digest!, shown_hash: keys.shown! });
                  setResult(res.structuredContent.status === "queued"
                    ? "Queued. Jobwatch presses Submit within 15 minutes if the form is unchanged."
                    : `Submit status: ${res.structuredContent.status}.`);
                } catch { setFailed(true); }
              }}>
              {submit.isPending ? "Sending..." : "Submit application"}
            </button>
            <button type="button" className="btn quiet" disabled={submit.isPending} onClick={() => setDeclined(true)}>Not yet</button>
          </div>
        </>
      )}
    </div>
  );
}
