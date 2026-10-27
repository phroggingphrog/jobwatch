import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading } from "../shared/ui.js";
import { Dashboard } from "../shared/dashboard.js";
export default function DiscoveryView() {
  const context = useToolContext<"discovery_status">();
  if (context.status === "pending") return <Loading label="Loading discovery progress" />;
  if (context.status === "error") return <ErrorNote message={context.error.message} />;
  return <Dashboard initialSection="Discovery" />;
}
