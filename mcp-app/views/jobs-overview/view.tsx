import { useState } from "react";
import { useCallTool, useToolContext } from "mcp-use/react";
import { ErrorNote, Loading, Page, Status } from "../shared/ui.js";
import { JobPane, type Job } from "../shared/panes.js";
import { SettingsPanel } from "../settings/SettingsPanel.js";

const COUNTS = [["needs_you", "need you"], ["needs_info", "need info"], ["outcome_unknown", "outcome unknown"], ["submitted", "submitted"]] as const;
export type Overview = { counts: Record<string, number>; jobs: JobRow[] };
type JobRow = {
  posting_id: number; employer: string | null; title: string | null; score: number | null; state: string;
  assessment_state?: "current" | "stale" | "not_assessed" | "incomplete";
  assessment_reason?: string | null; assessment_summary?: string | null;
};

export function JobsList({ toolOutput, onSettings }: { toolOutput: Overview; onSettings?: () => void }) {
  const detail = useCallTool("job_detail");
  const [open, setOpen] = useState<Job | null>(null);

  const show = async (id: number) => {
    try { setOpen((await detail.callTool({ posting_id: id })).structuredContent as Job); } catch { /* detail.error */ }
  };
  if (open) return <Page><JobPane d={open} onBack={() => setOpen(null)} /></Page>;

  const counts = COUNTS.filter(([k]) => toolOutput.counts[k]).map(([k, l]) => `${toolOutput.counts[k]} ${l}`).join(" · ") || "No application actions pending";
  const next = toolOutput.jobs.find((j) => ["draft ready", "awaiting browser press", "failed", "expired", "outcome unknown"].includes(j.state));
  return (
    <Page>
      <div className="head">
        <div><h1>Your jobs</h1><p className="sub">{counts}</p></div>
        <div className="actions overview-actions" style={{ marginTop: 0 }}>
          {onSettings && <button type="button" className="btn quiet" onClick={onSettings}>Discovery settings</button>}
          {next && <button type="button" className="btn primary" onClick={() => show(next.posting_id)}>Open the one that needs you</button>}
        </div>
      </div>
      {detail.error && <p className="note bad" role="alert">Could not load that job. Try again.</p>}
      {toolOutput.jobs.length === 0 ? <p className="empty">No jobs with activity yet.</p> : (
        <ul className="rows">
          {toolOutput.jobs.map((j) => (
            <li key={j.posting_id}>
              <button type="button" className="row" onClick={() => show(j.posting_id)}
                aria-label={`${j.employer ?? "Unknown employer"}, ${j.title ?? "untitled"}, ${j.state}. Open details.`}>
                <span className="grow">
                  <div className="t">{j.title || "(untitled)"}</div>
                  <div className="e">{j.employer || "Unknown employer"}</div>
                  {j.assessment_state && <div className="e">Assessment: {{ current: "assessed", stale: "needs refresh", not_assessed: "not assessed", incomplete: "incomplete" }[j.assessment_state]}</div>}
                  {(j.assessment_reason || j.assessment_summary) && <div className="e">
                    {[j.assessment_reason, j.assessment_summary].filter((value): value is string => Boolean(value)).join(" · ")}
                  </div>}
                </span>
                {j.score != null && <span className="score">{j.score}</span>}
                <span className="status-group"><span className="sub">Application</span><Status state={j.state} /></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}

export default function JobsOverview() {
  const { status, toolOutput, error } = useToolContext<"jobs_overview">();
  const [settingsOpen, setSettingsOpen] = useState(false);
  if (status === "pending") return <Loading label="Loading your jobs" />;
  if (status === "error") return <ErrorNote message={error.message} />;
  if (settingsOpen) return <Page><SettingsPanel onBack={() => setSettingsOpen(false)} /></Page>;
  return <JobsList toolOutput={toolOutput as Overview} onSettings={() => setSettingsOpen(true)} />;
}
