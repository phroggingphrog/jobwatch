import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading } from "../shared/ui.js";
import { Dashboard } from "../shared/dashboard.js";
export default function ApplicationsView() {
  const context = useToolContext<"applications_overview">();
  if (context.status === "pending") return <Loading label="Loading application history" />;
  if (context.status === "error") return <ErrorNote message={context.error.message} />;
  return <Dashboard initialSection="Applications" initialApplications={context.toolOutput} />;
}
