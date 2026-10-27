import { useState } from "react";
import { useCallTool } from "mcp-use/react";
import type { z } from "zod";
import type { overviewOut, applicationsOut } from "../../src/schemas.js";
import { Page, Status } from "./ui.js";
import { JobPane, type Job } from "./panes.js";
import { SettingsPanel } from "../settings/SettingsPanel.js";

export type Overview = z.infer<typeof overviewOut>;
type Applications = z.infer<typeof applicationsOut>;
type Section = "Jobs" | "Applications" | "Discovery" | "Settings";
export const labels = {stronger_match: "Stronger match", stretch: "Stretch", needs_clarification: "Needs clarification"};
const emptyCopy = {
  ok: "No current matches passed the shortlist checks. Collected postings and excluded assessments are not recommendations.",
  stale: "The shortlist needs refreshing because its inputs changed. Previous matches are hidden until checked.",
  not_built: "A shortlist has not been built yet. Refresh from stored assessments, or check Discovery for progress.",
  no_confirmed_profile: "Confirm your profile and search scope in the conversation before discovery can produce matches.",
};

export function Dashboard({initialSection = "Jobs", initialJobs, initialApplications, initialSettings}: {
  initialSection?: Section; initialJobs?: Overview; initialApplications?: Applications;
  initialSettings?: {daily_token_ceiling: number | null};
}) {
  const [section, setSection] = useState<Section>(initialSection);
  const [jobs, setJobs] = useState(initialJobs);
  const [applications, setApplications] = useState(initialApplications);
  const [opened, setOpened] = useState<Job>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const readJobs = useCallTool("jobs_overview");
  const readApplications = useCallTool("applications_overview");
  const refresh = useCallTool("refresh_shortlist");
  const detail = useCallTool("job_detail");
  const application = useCallTool("application_detail");
  const navigate = async (next: Section) => {
    if (pending) return;
    setSection(next); setOpened(undefined); setError(""); setPending(true);
    if (next === "Jobs") setJobs(undefined);
    if (next === "Applications") setApplications(undefined);
    try {
      if (next === "Jobs") setJobs((await readJobs.callTool({limit:100})).structuredContent);
      if (next === "Applications") setApplications((await readApplications.callTool({limit:100})).structuredContent);
    } catch { setError(`Could not load ${next.toLowerCase()}. Try again.`); }
    finally { setPending(false); }
  };
  const open = async (id: number) => {
    setPending(true); setError("");
    try {setOpened((await (section === "Applications" ? application : detail).callTool({posting_id:id})).structuredContent as Job);}
    catch {setError("Could not load that job. Try again.");}
    finally {setPending(false);}
  };
  return <Page>
    <header className="widget-header"><span className="widget-brand">Jobwatch</span><span className="sub">Your career workspace</span></header>
    <nav className="widget-nav" aria-label="Jobwatch">
      {(["Jobs", "Applications", "Discovery", "Settings"] as Section[]).map((item) => <button type="button" key={item}
        aria-current={section === item ? "page" : undefined} disabled={pending} onClick={() => void navigate(item)}>{item}</button>)}
    </nav>
    {error && <p role="alert" className="note bad">{error} <button className="link" onClick={() => void navigate(section)}>Reload</button></p>}
    {pending && <p role="status" className="sub">Loading {section.toLowerCase()}…</p>}
    {opened ? <JobPane d={opened} onBack={() => setOpened(undefined)} /> : <>
      {(section === "Settings" || section === "Discovery") && <SettingsPanel initial={initialSettings} mode={section === "Settings" ? "settings" : "discovery"} />}
      {section === "Jobs" && <section aria-labelledby="jobs-title">
        <div className="head"><div><h1 id="jobs-title">Your jobs</h1><p className="sub">Current matches, ranked by Jobwatch’s existing evidence and preference rules.</p></div>
          <button className="btn" disabled={pending || refresh.isPending} onClick={async () => {
            setError(""); try {setJobs((await refresh.callTool({})).structuredContent);} catch {setJobs(undefined); setError("Could not refresh the shortlist. Try again.");}
          }}>{refresh.isPending ? "Refreshing…" : "Refresh shortlist"}</button></div>
        {jobs && <>
          <p className="meaning">{jobs.meaning}</p>
          {!jobs.jobs.length ? <p className="empty" role="status">{emptyCopy[jobs.status]}</p> : <ol className="rows shortlist-rows">
            {jobs.jobs.map((j) => <li key={j.entry_id}><button className="row shortlist-row" disabled={pending} onClick={() => void open(j.posting_id)}
              aria-label={`${j.employer ?? "Unknown employer"}, ${j.title ?? "Untitled"}, ${labels[j.label]}. Open details.`}>
              <span className="rank" aria-label={`Rank ${j.rank}`}>{j.rank}</span><span className="grow">
                <span className="t">{j.title || "Untitled"}</span><span className="e">{j.employer || "Unknown employer"}</span>
                <span className="fit-label">{labels[j.label]}</span><span className="fit-summary">{j.objective_fit}</span>
                {!j.can_prepare && <span className="hold-copy">Clarification required before preparation</span>}
              </span><span className="row-action">View details</span>
            </button></li>)}
          </ol>}
        </>}
        {!jobs && !pending && !error && <button className="btn" onClick={() => void navigate("Jobs")}>Load current matches</button>}
      </section>}
      {section === "Applications" && <section><h1>Applications</h1><p className="sub">Preparation and submission history. These are not current recommendations.</p>
        {applications && (!applications.jobs.length ? <p className="empty">No application work recorded.</p> : <ul className="rows">
          {applications.jobs.map(j => <li key={j.posting_id}><button className="row" disabled={pending} onClick={() => void open(j.posting_id)}>
            <span className="grow"><span className="t">{j.title || "Untitled"}</span><span className="e">{j.employer || "Unknown employer"}</span></span><Status state={j.state} />
          </button></li>)}
        </ul>)}
      </section>}
    </>}
  </Page>;
}
