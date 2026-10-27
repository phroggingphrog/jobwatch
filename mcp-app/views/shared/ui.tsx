import "./theme.css";
import type { ReactNode } from "react";
import { useViewTheme } from "mcp-use/react";

const TONE: Record<string, "ok" | "warn" | "bad" | "work" | ""> = {
  submitted: "ok",
  complete: "ok",
  "draft ready": "warn",
  "awaiting browser press": "warn",
  "awaiting approval": "warn",
  failed: "bad",
  expired: "bad",
  "outcome unknown": "bad",
  rejected: "",
  queued: "work",
  drafting: "work",
  executing: "work",
};

/** Status is always a dot plus the word, never colour alone. */
export function Status({ state }: { state: string }) {
  return (
    <span className="status">
      <span className={`dot ${TONE[state] ?? ""}`} aria-hidden="true" />
      {state}
    </span>
  );
}

export function Page({ children }: { children: ReactNode }) {
  const theme = useViewTheme();
  return <main className="jw" data-theme={theme}>{children}</main>;
}

export function Loading({ label }: { label: string }) {
  return (
    <Page>
      <div role="status" aria-label={label}>
        <p className="sub">{label}…</p>
        <div className="skel" style={{ width: "40%" }} />
        <div className="skel" style={{ width: "80%" }} />
        <div className="skel" style={{ width: "65%" }} />
      </div>
    </Page>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <Page>
      <p className="note bad" role="alert">{message}</p>
    </Page>
  );
}

export const safeUrl = (u?: string | null) => (u && /^https?:\/\//.test(u) ? u : undefined);
export const metaString = (meta: unknown, key: string) => {
  const v = meta && typeof meta === "object" ? (meta as Record<string, unknown>)[key] : undefined;
  return typeof v === "string" ? v : undefined;
};
