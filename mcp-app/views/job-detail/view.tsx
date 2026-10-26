import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading, Page } from "../shared/ui.js";
import { JobPane, type Job } from "../shared/panes.js";

export default function JobDetail() {
  const { status, toolOutput, error } = useToolContext<"job_detail">();
  if (status === "pending") return <Loading label="Loading the job" />;
  if (status === "error") return <ErrorNote message={error.message} />;
  return <Page><JobPane d={toolOutput as Job} /></Page>;
}
