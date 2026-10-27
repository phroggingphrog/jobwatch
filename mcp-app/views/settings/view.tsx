import { useState } from "react";
import { useCallTool, useToolContext } from "mcp-use/react";
import { ErrorNote, Loading, Page } from "../shared/ui.js";
import { JobsList, type Overview } from "../jobs-overview/view.js";
import { SettingsPanel } from "./SettingsPanel.js";

export default function SettingsView() {
  const { status, toolOutput, error } = useToolContext<"get_discovery_settings">();
  const overview = useCallTool("jobs_overview");
  const [jobs, setJobs] = useState<Overview>();
  const [navigationError, setNavigationError] = useState(false);
  if (status === "pending") return <Loading label="Loading discovery settings" />;
  if (status === "error") return <ErrorNote message={error.message} />;
  if (jobs) return <JobsList toolOutput={jobs} onSettings={() => setJobs(undefined)} />;
  return <Page>
    {navigationError && <p className="note bad" role="alert">Could not open your jobs. Try again.</p>}
    <SettingsPanel initial={toolOutput} onBack={async () => {
      setNavigationError(false);
      try { setJobs((await overview.callTool({ limit: 50 })).structuredContent as Overview); }
      catch { setNavigationError(true); }
    }} />
  </Page>;
}
