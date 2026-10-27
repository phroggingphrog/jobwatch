import { useEffect, useRef, useState } from "react";
import { useCallTool } from "mcp-use/react";
import { ErrorNote, Loading, Status } from "../shared/ui.js";
import "./settings.css";

type Settings = { daily_token_ceiling: number | null };
type Incident = {
  incident_id: string; posting_id: number | null; run_id: string; reason: string;
  phase: string | null; last_successful_phase: string | null; state: string;
  notification_state: string; notification_error: string | null; retry_context?: string | null;
};
type DiscoveryStatus = {
  enabled: boolean; postings: number; assessments_today: number; charged_tokens_today: number;
  scope: { daily_assessments: number; daily_token_ceiling: number | null } | null;
  incidents: Incident[]; latest_run: Record<string, unknown> | null;
  invocations: Record<string, unknown>[];
};

const message = (error: unknown) => error instanceof Error ? error.message : "Could not reach Jobwatch. Try again.";
const valueText = (value: unknown) => typeof value === "string" && value ? value : undefined;

export function SettingsPanel({ initial, onBack }: { initial?: Settings; onBack?: () => void }) {
  const get = useCallTool("get_discovery_settings");
  const save = useCallTool("set_discovery_settings");
  const readStatus = useCallTool("discovery_status");
  const readStatusTool = readStatus.callTool;
  const start = useCallTool("start_discovery");
  const retry = useCallTool("retry_assessment");
  const [settings, setSettings] = useState<Settings | undefined>(initial);
  const [mode, setMode] = useState<"unlimited" | "limited">(initial?.daily_token_ceiling == null ? "unlimited" : "limited");
  const [limit, setLimit] = useState(initial?.daily_token_ceiling == null ? "" : String(initial.daily_token_ceiling));
  const [status, setStatus] = useState<DiscoveryStatus | undefined>();
  const [loading, setLoading] = useState(initial === undefined);
  const [refreshError, setRefreshError] = useState("");
  const [formError, setFormError] = useState("");
  const [saved, setSaved] = useState(false);
  const [queued, setQueued] = useState("");
  const [acceptedRun, setAcceptedRun] = useState<{ id: string; state: string }>();
  const [retryingIncident, setRetryingIncident] = useState("");
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});
  const startRequestId = useRef<string | null>(null);
  const retryRequestIds = useRef(new Map<string, string>());

  const applySettings = (next: Settings) => {
    setSettings(next);
    setMode(next.daily_token_ceiling === null ? "unlimited" : "limited");
    setLimit(next.daily_token_ceiling === null ? "" : String(next.daily_token_ceiling));
  };

  const refresh = async () => {
    setLoading(true);
    setRefreshError("");
    try {
      const results = await Promise.all([get.callTool({}), readStatus.callTool({})]);
      applySettings(results[0].structuredContent as Settings);
      setStatus(results[1].structuredContent as DiscoveryStatus);
    } catch (error) {
      setRefreshError(message(error));
    } finally {
      setLoading(false);
    }
  };

  const latestRun = status?.latest_run;
  const invocations = status?.invocations ?? [];
  const latestState = valueText(latestRun?.state);
  const acceptedBusy = acceptedRun?.state === "running" || acceptedRun?.state === "queued";
  const assessmentPhases = new Set(["liveness", "evidence_snapshot", "assessment", "candidate_assessment", "evaluation"]);
  const activeAssessment = invocations.find((entry) => entry.state === "running" && assessmentPhases.has(String(entry.phase)));
  const current = (acceptedBusy ? { id: acceptedRun.id, state: acceptedRun.state } : undefined)
    ?? (latestState === "running" || latestState === "queued" ? latestRun : undefined)
    ?? activeAssessment
    ?? invocations.find((entry) => entry.state === "running" || entry.state === "queued") ?? latestRun;
  const currentState = valueText(current?.state);
  const currentId = valueText(current?.run_id) ?? valueText(current?.id);
  const currentPhase = valueText(current?.phase);
  const currentPosting = typeof current?.posting_id === "number" ? current.posting_id : undefined;
  const incidents = status?.incidents ?? [];
  const discoveryBusy = latestState === "queued" || latestState === "running" || acceptedBusy || activeAssessment !== undefined;
  const busyState = activeAssessment ? "running" : acceptedBusy ? acceptedRun.state
    : latestState === "queued" || latestState === "running" ? latestState : "running";

  useEffect(() => {
    if (initial === undefined) void refresh();
    else {
      setLoading(false);
      void readStatus.callTool({}).then((result) => setStatus(result.structuredContent as DiscoveryStatus))
        .catch((error: unknown) => setRefreshError(message(error)));
    }
  // The panel's initial payload is fixed for one mount; refresh is user driven afterwards.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!discoveryBusy) return;
    const timer = setInterval(() => {
      void readStatusTool({}).then((result) => {
        setStatus(result.structuredContent as DiscoveryStatus);
        setRefreshError("");
      }).catch((error: unknown) => setRefreshError(message(error)));
    }, 12_000);
    return () => clearInterval(timer);
  }, [discoveryBusy, readStatusTool]);

  useEffect(() => {
    if (!acceptedRun || valueText(latestRun?.id) !== acceptedRun.id) return;
    if (latestState !== "queued" && latestState !== "running") setAcceptedRun(undefined);
  }, [acceptedRun, latestRun, latestState]);

  const saveSettings = async () => {
    setFormError(""); setSaved(false);
    const ceiling = mode === "unlimited" ? null : Number(limit);
    if (mode === "limited" && (ceiling === null || !Number.isSafeInteger(ceiling) || ceiling <= 0)) {
      setFormError("Enter a whole number greater than zero.");
      return;
    }
    try {
      applySettings((await save.callTool({ daily_token_ceiling: ceiling })).structuredContent as Settings);
      setSaved(true);
    } catch (error) { setFormError(message(error)); }
  };

  const startRun = async () => {
    setQueued(""); setRefreshError("");
    try {
      startRequestId.current ??= crypto.randomUUID();
      const result = await start.callTool({ request_id: startRequestId.current });
      startRequestId.current = null;
      setQueued(`Discovery ${result.structuredContent.state}.`);
      if (result.structuredContent.state === "queued" || result.structuredContent.state === "running") {
        setAcceptedRun({ id: result.structuredContent.run_id, state: result.structuredContent.state });
      }
      await refresh();
    } catch (error) { setRefreshError(message(error)); }
  };

  const retryIncident = async (incident: Incident) => {
    if (incident.posting_id === null || !incident.retry_context || discoveryBusy) return;
    setRetryErrors((previous) => ({ ...previous, [incident.incident_id]: "" }));
    setRetryingIncident(incident.incident_id);
    try {
      let requestId = retryRequestIds.current.get(incident.incident_id);
      if (!requestId) {
        requestId = crypto.randomUUID();
        retryRequestIds.current.set(incident.incident_id, requestId);
      }
      const result = await retry.callTool({ request_id: requestId, incident_id: incident.incident_id,
        posting_id: incident.posting_id, expected_context: incident.retry_context });
      retryRequestIds.current.delete(incident.incident_id);
      setQueued(`Assessment retry ${result.structuredContent.state}.`);
      if (result.structuredContent.state === "queued" || result.structuredContent.state === "running") {
        setAcceptedRun({ id: result.structuredContent.run_id, state: result.structuredContent.state });
      }
      await refresh();
    } catch (error) {
      setRetryErrors((previous) => ({ ...previous, [incident.incident_id]: message(error) }));
    } finally {
      setRetryingIncident("");
    }
  };

  if (loading && !settings) return <Loading label="Loading discovery settings and progress" />;
  if (refreshError && !settings && !status) return <ErrorNote message={refreshError} />;

  return (
    <section className="discovery-settings" aria-labelledby="settings-title">
      {onBack && <button type="button" className="link settings-back" onClick={onBack}>Back to jobs</button>}
      <div className="settings-head">
        <div><h1 id="settings-title">Discovery settings</h1><p className="sub">Your daily allowance and current collection progress.</p></div>
        <div className="settings-tools">
          <button type="button" className="btn quiet" disabled={loading} onClick={() => void refresh()}>{loading ? "Refreshing…" : "Refresh"}</button>
          <button type="button" className="btn primary" disabled={start.isPending || loading || discoveryBusy || !status?.enabled}
            onClick={() => void startRun()}>{start.isPending ? "Starting…" : discoveryBusy ? `Discovery ${busyState}…` : status?.enabled ? "Start discovery" : "Confirm profile to start"}</button>
        </div>
      </div>

      <section className="settings-section" aria-labelledby="allowance-title">
        <h2 id="allowance-title">Daily token allowance</h2>
        <p className="settings-copy">Changes apply to the next discovery pass; an active run keeps its current allowance. Per-job and per-run limits, and the 40-assessment daily limit, still apply.</p>
        <div className="allowance-options" role="group" aria-label="Daily token allowance mode">
          <button type="button" className="choice" aria-pressed={mode === "unlimited"} disabled={save.isPending}
            onClick={() => { setMode("unlimited"); setFormError(""); setSaved(false); }}>Unlimited</button>
          <button type="button" className="choice" aria-pressed={mode === "limited"} disabled={save.isPending}
            onClick={() => { setMode("limited"); setFormError(""); setSaved(false); }}>Limit daily tokens</button>
        </div>
        {mode === "limited" && <div className="limit-field">
          <label htmlFor="daily-token-limit">Tokens per day</label>
          <input id="daily-token-limit" type="number" inputMode="numeric" min="1" step="1" value={limit}
            aria-describedby="daily-token-help" onChange={(event) => { setLimit(event.target.value); setFormError(""); setSaved(false); }} />
          <p id="daily-token-help" className="sub">Use a positive whole number.</p>
        </div>}
        {(formError || save.error) && <p className="note bad" role="alert">{formError || message(save.error)}</p>}
        {saved && <p className="note" role="status">Saved: {settings?.daily_token_ceiling === null ? "Unlimited daily tokens" : `${settings?.daily_token_ceiling?.toLocaleString()} tokens per day`}.</p>}
        <div className="actions"><button type="button" className="btn primary" disabled={save.isPending || (mode === "limited" && (!limit || !Number.isSafeInteger(Number(limit)) || Number(limit) <= 0))}
          onClick={() => void saveSettings()}>{save.isPending ? "Saving…" : "Save allowance"}</button></div>
      </section>

      <section className="settings-section" aria-labelledby="progress-title">
        <h2 id="progress-title">Discovery progress</h2>
        {refreshError && <p className="note bad" role="alert">{refreshError}</p>}
        {!status ? <p className="sub" role="status">Progress is not available yet. Refresh to try again.</p> : <>
          <dl className="progress-grid">
            <dt>Discovery</dt><dd><Status state={status.enabled ? "enabled" : "disabled"} /></dd>
            <dt>Collected postings</dt><dd>{status.postings.toLocaleString()}</dd>
            <dt>Assessment attempts today</dt><dd>{status.assessments_today} of {status.scope?.daily_assessments ?? 40}</dd>
            <dt>Tokens charged today</dt><dd>{status.charged_tokens_today.toLocaleString()}</dd>
            <dt>Current run</dt><dd>{currentState ? `${activeAssessment && current === activeAssessment ? "Scheduled assessment · " : ""}${currentState}${currentPhase ? ` · ${currentPhase.replaceAll("_", " ")}` : ""}${currentPosting ? ` · Job #${currentPosting}` : ""}${currentId ? ` · ${currentId}` : ""}` : "No active run"}</dd>
          </dl>
          {queued && <p className="note" role="status">{queued}</p>}
          {!status.enabled && <p className="note" role="status">Confirm your profile and search scope before starting discovery.</p>}
          {incidents.length > 0 && <div className="incident-list">
            <h3>Paused work</h3>
            <ul className="rows">{incidents.map((incident) => <li key={incident.incident_id}>
              <div className="incident-row"><Status state={incident.state} />
                <span className="incident-job">{incident.posting_id === null ? `Discovery run ${incident.run_id}` : `Job #${incident.posting_id}`}</span>
                <span className="incident-reason">{incident.reason.replaceAll("_", " ")}</span>
                {incident.phase && <span className="sub">at {incident.phase.replaceAll("_", " ")}</span>}
                <span className="sub">Last successful phase: {incident.last_successful_phase?.replaceAll("_", " ") || "Not recorded"}</span>
                <span className="sub">Hermes handoff: {incident.notification_state.replaceAll("_", " ")}{incident.notification_error ? ` (${incident.notification_error.replaceAll("_", " ")})` : ""}</span>
                {retryErrors[incident.incident_id] && <p className="note bad" role="alert">{retryErrors[incident.incident_id]}</p>}
                {incident.posting_id !== null && incident.retry_context && <button type="button" className="btn quiet"
                  disabled={discoveryBusy || retry.isPending || retryingIncident !== ""}
                  onClick={() => void retryIncident(incident)}>
                  {retryingIncident === incident.incident_id ? "Requesting retry…" : discoveryBusy ? "Retry unavailable while discovery is active" : "Retry this assessment"}
                </button>}
                {incident.state === "paused" && !(incident.posting_id !== null && incident.retry_context) &&
                  <span className="sub">Retry unavailable until current job inputs are available.</span>}
              </div>
            </li>)}</ul>
          </div>}
        </>}
      </section>
    </section>
  );
}
