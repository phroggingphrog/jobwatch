import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading } from "../shared/ui.js";
import { Dashboard } from "../shared/dashboard.js";

const SECTION = { jobs: "Jobs", applications: "Applications", discovery: "Discovery", settings: "Settings" } as const;

// Opened only by the open_dashboard tool, i.e. only when the person asks for the interactive view.
export default function DashboardView() {
  const context = useToolContext<"open_dashboard">();
  if (context.status === "pending") return <Loading label="Opening the dashboard" />;
  if (context.status === "error") return <ErrorNote message={context.error.message} />;
  const d = context.toolOutput;
  return <Dashboard initialSection={SECTION[d.tab]} initialJobs={d.jobs} initialApplications={d.applications} initialSettings={d.settings} />;
}
