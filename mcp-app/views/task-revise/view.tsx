import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading } from "../shared/ui.js";
import { TaskPane, type TaskOut } from "../shared/task.js";

export default function View() {
  const { status, toolOutput, error, meta } = useToolContext<"revise_application">();
  if (status === "pending") return <Loading label="Loading the status" />;
  if (status === "error") return <ErrorNote message={error.message} />;
  return <TaskPane initial={toolOutput as TaskOut} meta={meta} />;
}
