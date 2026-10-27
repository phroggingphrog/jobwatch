// Renders the host guidance (initialize `instructions`, jobwatch_guide topics, skill resources) from the editable
// files in guidance/ (bundled into src/generated/guidance-bundle.ts) and the tool registry. Nothing about tools is
// typed by hand here: names, the tool table and the count come from the registry.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { GUIDANCE } from "./generated/guidance-bundle.js";
import { activeSpecs, modelSpecs, type AnySpec, type WidgetMode } from "./registry.js";

export const TOPICS = Object.keys(GUIDANCE.topics) as [string, ...string[]];
export const SKILLS: Record<string, { topics: readonly string[]; description: string }> = GUIDANCE.skills;

function render(template: string, specs: AnySpec[], mode: WidgetMode, extra: Record<string, string> = {}): string {
  const known = new Set(specs.map((s) => s.name));
  const model = modelSpecs(specs, mode);
  const vars: Record<string, string> = {
    tool_count: String(model.length),
    app_only_count: String(activeSpecs(specs, mode).filter((s) => s.access === "app").length),
    tool_table: model.map((s) => `- ${s.name}: when ${s.whenToUse}`).join("\n"),
    widget_rule: template.includes("{{widget_rule}}") ? render(GUIDANCE.widgetRules[mode], specs, mode) : "",
    ...extra,
  };
  return template.replace(/\{\{([a-z_]+)(?::([a-z_]+))?\}\}/g, (_, key: string, arg?: string) => {
    if (key === "tool") {
      if (!arg || !known.has(arg)) throw new Error(`guidance names unknown tool "${arg}"`);
      return arg;
    }
    if (!(key in vars)) throw new Error(`guidance has unknown placeholder {{${key}}}`);
    return vars[key];
  });
}

export const renderInstructions = (specs: AnySpec[], mode: WidgetMode) => render(GUIDANCE.instructions, specs, mode);

// ---- skills: optional enrichment read from the repo at runtime ---------------------------------------------------
function skillDirs(): string[] {
  const out: string[] = [];
  if (process.env.JOBWATCH_SKILLS_DIR) out.push(resolve(process.env.JOBWATCH_SKILLS_DIR));
  const roots = new Set<string>([process.cwd()]);
  try { roots.add(dirname(fileURLToPath(import.meta.url))); } catch { /* bundled without a file URL */ }
  for (const r of roots) {
    let d = r;
    for (let i = 0; i < 5; i++) {
      out.push(join(d, "pipeline", "agentic", "skills"));
      d = dirname(d);
    }
  }
  return out;
}

export function readSkill(name: string): string | null {
  if (!(name in SKILLS)) return null;
  for (const dir of skillDirs()) {
    const file = join(dir, name, "SKILL.md");
    try {
      if (existsSync(file)) return readFileSync(file, "utf8");
    } catch { /* try the next candidate */ }
  }
  return null;
}

const body = (raw: string) => raw.replace(/^---\n[\s\S]*?\n---\n?/, "").trim();

export function skillText(name: string): { text: string; source: "repo" | "bundled" } {
  const raw = readSkill(name);
  if (raw !== null) return { text: raw, source: "repo" };
  const d = SKILLS[name].description;
  return { text: `---\nname: ${name}\ndescription: ${d}\n---\n\n${d}\n(Full text unavailable on this server; this is the bundled summary.)\n`, source: "bundled" };
}

export function renderGuide(topic: string, specs: AnySpec[], mode: WidgetMode) {
  if (!(topic in GUIDANCE.topics)) throw new Error(`unknown topic ${topic}`);
  const sources: { name: string; from: "repo" | "bundled" }[] = [];
  const parts = [`JOBWATCH GUIDE: ${topic}`, render((GUIDANCE.topics as Record<string, string>)[topic], specs, mode)];
  for (const name of Object.keys(SKILLS).filter((n) => SKILLS[n].topics.includes(topic))) {
    const s = skillText(name);
    sources.push({ name, from: s.source });
    parts.push(`--- Skill "${name}" (${s.source}). Written for Jobwatch's in-app agent; tool names in it that are not on this server are internal. ---\n${body(s.text)}`);
  }
  return { text: parts.join("\n\n"), sources };
}
