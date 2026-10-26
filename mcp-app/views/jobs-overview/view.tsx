import { useState } from "react";
import { useCallTool, useToolContext } from "mcp-use/react";
import { ErrorNote, Loading, Page, Status } from "../shared/ui.js";
import { JobPane, type Job } from "../shared/panes.js";

const COUNTS = [["needs_you", "need you"], ["needs_info", "need info"], ["outcome_unknown", "outcome unknown"], ["submitted", "submitted"]] as const;

export default function JobsOverview() {
  const { status, toolOutput, error } = useToolContext<"jobs_overview">();
  const detail = useCallTool("job_detail");
  const [open, setOpen] = useState<Job | null>(null);

  if (status === "pending") return <Loading label="Loading your jobs" />;
  if (status === "error") return <ErrorNote message={error.message} />;

  const show = async (id: number) => {
    try { setOpen((await detail.callTool({ posting_id: id })).structuredContent as Job); } catch { /* detail.error */ }
  };
  if (open) return <Page><JobPane d={open} onBack={() => setOpen(null)} /></Page>;

  const counts = COUNTS.filter(([k]) => toolOutput.counts[k]).map(([k, l]) => `${toolOutput.counts[k]} ${l}`).join(" · ") || "Nothing needs you";
  const next = toolOutput.jobs.find((j) => ["draft ready", "awaiting browser press", "failed", "expired", "outcome unknown"].includes(j.state));
  return (
    <Page>
      <div className="head">
        <div><h1>Your jobs</h1><p className="sub">{counts}</p></div>
        {next && <button type="button" className="btn primary" onClick={() => show(next.posting_id)}>Open the one that needs you</button>}
      </div>
      {detail.error && <p className="note bad" role="alert">Could not load that job. Try again.</p>}
      {toolOutput.jobs.length === 0 ? <p className="empty">No jobs with activity yet.</p> : (
        <ul className="rows">
          {toolOutput.jobs.map((j) => (
            <li key={j.posting_id}>
              <button type="button" className="row" onClick={() => show(j.posting_id)}
                aria-label={`${j.employer ?? "Unknown employer"}, ${j.title ?? "untitled"}, ${j.state}. Open details.`}>
                <span className="grow"><div className="t">{j.title || "(untitled)"}</div><div className="e">{j.employer || "Unknown employer"}</div></span>
                {j.score != null && <span className="score">{j.score}</span>}
                <Status state={j.state} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}
