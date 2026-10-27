import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading } from "../shared/ui.js";
import { Dashboard } from "../shared/dashboard.js";
export default function JobsOverview() {
  const context = useToolContext<"jobs_overview">();
  if (context.status === "pending") return <Loading label="Loading current shortlist" />;
  if (context.status === "error") return <ErrorNote message={context.error.message} />;
  return <Dashboard initialJobs={context.toolOutput} />;
}
