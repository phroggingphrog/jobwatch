import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading } from "../shared/ui.js";
import { Dashboard } from "../shared/dashboard.js";
export default function SettingsView() {
  const context = useToolContext<"get_discovery_settings">();
  if (context.status === "pending") return <Loading label="Loading discovery settings" />;
  if (context.status === "error") return <ErrorNote message={context.error.message} />;
  return <Dashboard initialSection="Settings" initialSettings={context.toolOutput} />;
}
