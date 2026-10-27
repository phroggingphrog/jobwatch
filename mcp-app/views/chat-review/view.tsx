import { useState } from "react";
import { useCallTool, useToolContext } from "mcp-use/react";
import type { ChatOut } from "../../src/schemas.js";
import { ErrorNote, Loading, Page, metaString } from "../shared/ui.js";

const readable = (value: unknown): string => typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "Not specified";

function ChatPane({ initial, meta }: { initial: ChatOut; meta: unknown }) {
  const decide = useCallTool("decide_profile");
  const [next, setNext] = useState<{ out: ChatOut; binding?: string } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const out = next?.out ?? initial;
  const approval = out.approval;
  const binding = next ? next.binding : metaString(meta, "binding");
  const answer = async (decision: "approve" | "reject") => {
    if (!approval || !binding || decide.isPending) return;
    setFailure(null);
    try {
      const result = await decide.callTool({ interaction_id: approval.interaction_id, decision, binding });
      if (result.isError || !result.structuredContent) throw new Error("Profile confirmation did not complete. Ask Jobwatch for a fresh review.");
      setNext({ out: result.structuredContent as ChatOut, binding: metaString(result._meta, "binding") });
    } catch {
      setFailure("This review may have changed or expired. Ask Jobwatch for a fresh profile review before confirming.");
    }
  };
  return <Page>
    <h1>{approval ? "Review your profile" : "Jobwatch onboarding"}</h1>
    {out.answer && <p className="note" style={{ whiteSpace: "pre-wrap" }} role="status">{out.answer}</p>}
    {out.questions?.length ? <ol>{out.questions.map((q, i) => <li key={i}>{q.question}{q.options?.length ? <p>{q.options.join(" · ")}</p> : null}</li>)}</ol> : null}
    {approval && <>
      <p className="sub">Draft revision {approval.review.revision}. {approval.summary}</p>
      <dl className="qa">{approval.review.facts.map((fact, i) => <div className="qa-row" key={i}>
        <dt>{fact.section.replaceAll("_", " ")} ({fact.basis})</dt>
        <dd>{readable(fact.value)}</dd>
      </div>)}</dl>
      {approval.review.questions.length > 0 && <><h2>Still unknown</h2><ul className="list">{approval.review.questions.map((q, i) => <li key={i}>{q.text}</li>)}</ul></>}
      <h2>Search scope</h2>
      <dl className="qa">
        <div className="qa-row"><dt>Work</dt><dd>{approval.review.scope.basis.join("; ")}</dd></div>
        <div className="qa-row"><dt>Locations</dt><dd>{approval.review.scope.locations.join("; ") || "Not specified"}</dd></div>
        <div className="qa-row"><dt>Daily limits</dt><dd>{approval.review.scope.daily_assessments} assessments; {approval.review.scope.daily_token_ceiling.toLocaleString()} tokens</dd></div>
      </dl>
      <p className="note">Authorises: {readable(approval.review.authorises)}</p>
      <p>Does not authorise: {readable(approval.review.does_not_authorise)}</p>
      <div className="actions">
        <button type="button" className="btn primary" disabled={decide.isPending || !binding || Boolean(failure)} onClick={() => answer("approve")}>{decide.isPending ? "Saving…" : "Confirm profile"}</button>
        <button type="button" className="btn" disabled={decide.isPending || !binding || Boolean(failure)} onClick={() => answer("reject")}>Keep as draft</button>
      </div>
      {!binding && <p role="alert" className="note bad">This review cannot be confirmed here. Ask Jobwatch for a fresh profile review.</p>}
    </>}
    {failure && <p role="alert" className="note bad">{failure}</p>}
  </Page>;
}

export default function View() {
  const { status, toolOutput, error, meta } = useToolContext<"career_ops_start_chat">();
  if (status === "pending") return <Loading label="Loading your profile review" />;
  if (status === "error") return <ErrorNote message={error.message} />;
  const initial = toolOutput as ChatOut;
  return <ChatPane key={`${initial.thread_id}:${initial.status}:${initial.approval?.interaction_id ?? initial.answer}`} initial={initial} meta={meta} />;
}
