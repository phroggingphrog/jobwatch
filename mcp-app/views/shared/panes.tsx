import { useState } from "react";
import { useCallTool } from "mcp-use/react";
import { Status, safeUrl, metaString } from "./ui.js";

export interface Job {
  posting_id: number; found: boolean; employer?: string | null; title?: string | null; location?: string | null;
  ad_url?: string | null; score?: number | null; why_it_fits?: string | null; pros?: string[]; cons?: string[];
  state?: string; state_detail?: string; documents_ready?: boolean; draft_version?: number | null; can_submit?: boolean;
}
export interface Review {
  posting_id: number; found: boolean; ready: boolean; employer?: string | null; title?: string | null;
  state?: string; draft_version?: number | null; ad_url?: string | null;
}

export function JobPane({ d, onBack }: { d: Job; onBack?: () => void }) {
  const review = useCallTool("review_submission");
  const [shown, setShown] = useState<{ r: Review; digest?: string } | null>(null);
  if (shown) return <ReviewPane r={shown.r} digest={shown.digest} onBack={() => setShown(null)} />;
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
            <dt>State</dt><dd><Status state={d.state ?? "not started"} /></dd>
            {d.state_detail ? (<><dt>Detail</dt><dd>{d.state_detail}</dd></>) : null}
            <dt>Score</dt><dd>{d.score != null ? <span className="score" style={{ textAlign: "left" }}>{d.score}</span> : "Not scored"}</dd>
            <dt>Documents</dt><dd>{d.documents_ready ? `Ready${d.draft_version ? ` (draft v${d.draft_version})` : ""}` : "None ready"}</dd>
          </dl>
          {d.why_it_fits && (<><h2>Why it fits</h2><p>{d.why_it_fits}</p></>)}
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
                    setShown({ r: res.structuredContent as Review, digest: metaString(res._meta, "submit_digest") });
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

/** Review-before-submit. The digest lives only in this component's props (from view-only _meta), never in view state. */
export function ReviewPane({ r, digest, onBack }: { r: Review; digest?: string; onBack?: () => void }) {
  const submit = useCallTool("submit_reviewed");
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const ad = safeUrl(r.ad_url);
  const what = `${r.title || "this job"} at ${r.employer || "the employer"}`;
  return (
    <div>
      {onBack && <button type="button" className="link" onClick={onBack}>Back</button>}
      <div className="head"><div>
        <h1>Review before submit</h1>
        <p className="sub">{what}</p>
      </div></div>
      <dl>
        <dt>State</dt><dd><Status state={r.state ?? "not started"} /></dd>
        <dt>Draft</dt><dd>{r.draft_version ? `v${r.draft_version}` : "None"}</dd>
      </dl>
      {ad && <p><a className="link" href={ad} target="_blank" rel="noopener noreferrer">Open the job ad</a></p>}
      {!r.found || !r.ready || !digest ? (
        <p className="note">Nothing is ready to submit for this job. Prepare and review an application first.</p>
      ) : result ? (
        <p className="note" role="status">{result}</p>
      ) : !confirming ? (
        <div className="actions">
          <button type="button" className="btn primary" onClick={() => setConfirming(true)}>Submit application</button>
        </div>
      ) : (
        <>
          <p className="note">This sends your application for {what} exactly as filled and reviewed. Nothing is sent if the form changed.</p>
          {failed && <p className="note bad" role="alert">Not submitted. The reviewed form may have changed; open the job again.</p>}
          <div className="actions">
            <button type="button" className="btn primary" disabled={submit.isPending}
              onClick={async () => {
                setFailed(false);
                try {
                  const res = await submit.callTool({ posting_id: r.posting_id, confirm_digest: digest });
                  setResult(res.structuredContent.status === "queued"
                    ? "Queued. Jobwatch presses Submit within 15 minutes if the form is unchanged."
                    : `Submit status: ${res.structuredContent.status}.`);
                } catch { setFailed(true); }
              }}>
              {submit.isPending ? "Sending..." : "Send to employer"}
            </button>
            <button type="button" className="btn" disabled={submit.isPending} onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </>
      )}
    </div>
  );
}
