import { useToolContext } from "mcp-use/react";
import { ErrorNote, Loading, Page, metaString } from "../shared/ui.js";
import { ReviewPane, type Review } from "../shared/panes.js";

export default function ReviewView() {
  const { status, toolOutput, error, meta } = useToolContext<"review_submission">();
  if (status === "pending") return <Loading label="Preparing the review" />;
  if (status === "error") return <ErrorNote message={error.message} />;
  return <Page><ReviewPane r={toolOutput as Review} keys={{ digest: metaString(meta, "submit_digest"), shown: metaString(meta, "shown_hash") }} /></Page>;
}
