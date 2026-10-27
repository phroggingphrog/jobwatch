import { MCPServer, type ToolRef } from "mcp-use";
import type { z } from "zod";
import { SKILLS, renderInstructions, skillText } from "./src/guidance.js";
import { activeSpecs, describeTool, lintRegistry, widgetMode } from "./src/registry.js";
import { T, specs } from "./src/tools.js";

const publicHost = new URL(process.env.JOBWATCH_MCP_PUBLIC_URL ?? "").hostname;
const mode = widgetMode();

const problems = lintRegistry(specs);
if (problems.length) throw new Error(`Jobwatch tool registry is invalid:\n${problems.join("\n")}`);

const server = new MCPServer({
  name: "jobwatch",
  title: "Jobwatch",
  version: "2.2.0",
  description:
    "Current canonical job matches, evidence questions, application history, discovery progress and per-person settings. Text first; interactive views only on request.",
  // Generated from the tool registry and guidance/*.md; see GUIDANCE.md.
  instructions: renderInstructions(specs, mode),
  allowedHosts: [publicHost],
});

// Every tool is registered from its spec. A view is attached only where the spec's widget policy allows it
// and the widget mode (JOBWATCH_MCP_WIDGETS) is not "off".
const refs = new Map<string, unknown>();
for (const s of activeSpecs(specs, mode)) {
  refs.set(
    s.name,
    server.tool(
      {
        name: s.name,
        title: s.title,
        description: describeTool(s),
        inputSchema: s.inputSchema,
        outputSchema: s.outputSchema,
        annotations: s.annotations,
        ...(s.widget !== "none" && mode !== "off" ? { view: { name: s.view! } } : {}),
        ...(s.access === "app" ? { visibility: "app" as const } : {}),
      },
      (input: unknown, ctx: unknown) => s.handler(input, ctx as never) as never,
    ),
  );
}

// Typed handles for the tools the views call (mcp-use derives the views' tool types from these exports).
type Ref<K extends keyof typeof T> = ToolRef<K, z.input<(typeof T)[K]["inputSchema"]>, z.output<(typeof T)[K]["outputSchema"]>>;
const ref = <K extends keyof typeof T>(name: K) => refs.get(name) as Ref<K>;
export const jobsOverview = ref("jobs_overview");
export const jobDetail = ref("job_detail");
export const applicationsOverview = ref("applications_overview");
export const applicationDetail = ref("application_detail");
export const refreshShortlist = ref("refresh_shortlist");
export const reviewSubmission = ref("review_submission");
export const prepareApplication = ref("prepare_application");
export const submitReviewed = ref("submit_reviewed");
export const discoveryStatus = ref("discovery_status");
export const startDiscovery = ref("start_discovery");
export const retryAssessment = ref("retry_assessment");
export const getDiscoverySettings = ref("get_discovery_settings");
export const setDiscoverySettings = ref("set_discovery_settings");
export const openDashboard = ref("open_dashboard");

// Skills as MCP resources: optional reading for hosts that support resources.
for (const name of Object.keys(SKILLS)) {
  server.resource(
    {
      name: `skill-${name}`,
      uri: `skill://jobwatch/${name}/SKILL.md`,
      title: `Jobwatch skill: ${name}`,
      description: SKILLS[name].description,
      mimeType: "text/markdown",
    },
    async (uri) => ({ contents: [{ uri: uri.href, mimeType: "text/markdown", text: skillText(name).text }] }),
  );
}

export default server;
