import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading, Page } from "../shared/ui.js";
import { JobPane, type Job } from "../shared/panes.js";
export default function ApplicationDetail() {
  const context = useToolContext<"application_detail">();
  if (context.status === "pending") return <Loading label="Loading application" />;
  if (context.status === "error") return <ErrorNote message={context.error.message} />;
  return <Page><JobPane d={context.toolOutput as Job} /></Page>;
}
