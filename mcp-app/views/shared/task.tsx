import { useState } from "react";
import { useCallTool } from "mcp-use/react";
import { Page, Status, metaString } from "./ui.js";

export type TaskOut = {
  posting_id: number; state: string; message?: string; reason?: string; answer?: string; declined?: string[];
  approval?: { interaction_id: string; operation: string; summary: string };
};

export function TaskPane({ initial, meta }: { initial: TaskOut; meta: unknown }) {
  const decide = useCallTool("decide");
  const [next, setNext] = useState<{ out: TaskOut; binding?: string } | null>(null);
  const out = next?.out ?? initial;
  const binding = next ? next.binding : metaString(meta, "binding");
  const answer = async (decision: "approve" | "reject") => {
    if (!out.approval || !binding) return;
    try {
      const res = await decide.callTool({ posting_id: out.posting_id, interaction_id: out.approval.interaction_id, decision, binding });
      setNext({ out: res.structuredContent as TaskOut, binding: metaString(res._meta, "binding") });
    } catch { /* decide.error */ }
  };
  return (
    <Page>
      <div className="head"><div><h1>Job #{out.posting_id}</h1><p className="sub">Work on this application</p></div></div>
      <dl><dt>State</dt><dd><Status state={out.state} /></dd></dl>
      {out.message && <p className="note">{out.message}</p>}
      {out.reason && <p className="sub">Reason: {out.reason}</p>}
      {out.answer && <p className="note">{out.answer}</p>}
      {out.declined?.length ? <p className="note">Jobwatch could not ask you about: {out.declined.join(", ")}.</p> : null}
      {decide.error && <p className="note bad" role="alert">That approval is no longer available. Ask Jobwatch again.</p>}
      {out.approval && (
        <>
          <h2>Approval needed</h2>
          <p>{out.approval.summary}</p>
          <div className="actions">
            <button type="button" className="btn primary" disabled={decide.isPending || !binding} onClick={() => answer("approve")}>Approve</button>
            <button type="button" className="btn" disabled={decide.isPending || !binding} onClick={() => answer("reject")}>Reject</button>
          </div>
        </>
      )}
    </Page>
  );
}
