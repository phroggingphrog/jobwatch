// Fails when the tool registry, the generated guidance or the generated docs drift apart. No server needed.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
// @ts-expect-error plain JS helper shared with `npm run docs`
import { BUNDLE_PATH, ROOT, buildBundle } from "../scripts/bundle.mjs";
import { updateReadme } from "../src/docs.js";
import { SKILLS, TOPICS, renderGuide, renderInstructions } from "../src/guidance.js";
import { MAX_DESCRIPTION, activeSpecs, describeTool, lintRegistry, modelSpecs, type WidgetMode } from "../src/registry.js";
import { T, specs } from "../src/tools.js";

const MODES: WidgetMode[] = ["on_request", "off"];

describe("tool registry", () => {
  it("has no lint problems: every tool has whenToUse, whenNotToUse, next, a widget policy and annotations", () => {
    expect(lintRegistry(specs)).toEqual([]);
  });
  it("keys match names, and names are unique snake_case", () => {
    for (const [key, s] of Object.entries(T)) expect(s.name).toBe(key);
    for (const s of specs) expect(s.name).toMatch(/^[a-z]+(_[a-z]+)*$/);
  });
  it("lint actually catches a tool without the required fields", () => {
    const bad = { ...specs[1], whenToUse: "", widget: undefined, annotations: undefined, next: "nothing" };
    const problems = lintRegistry([...specs, { ...bad, name: "bad_tool" } as never]);
    expect(problems.join("\n")).toMatch(/bad_tool: missing whenToUse/);
    expect(problems.join("\n")).toMatch(/bad_tool: missing widget policy/);
    expect(problems.join("\n")).toMatch(/bad_tool: missing annotations/);
    expect(problems.join("\n")).toMatch(/bad_tool: next must name another registered tool/);
  });
  it("no read-only tool opens a view by default; only the explicit dashboard and the Submit review may", () => {
    for (const s of specs) {
      if (s.widget === "on_request") expect(s.annotations.readOnlyHint).toBe(true);
      if (s.annotations.readOnlyHint && s.widget === "none") expect(s.view).toBeUndefined();
    }
    expect(specs.filter((s) => s.widget !== "none").map((s) => `${s.name}:${s.widget}`).sort()).toEqual(["open_dashboard:on_request", "review_submission:review"]);
  });
  it("model-visible descriptions stay within the limit", () => {
    for (const s of modelSpecs(specs, "on_request")) expect(describeTool(s).length, s.name).toBeLessThanOrEqual(MAX_DESCRIPTION);
  });
  it("only model tools that never submit are model-callable; submit and decide are app-only", () => {
    const app = specs.filter((s) => s.access === "app").map((s) => s.name).sort();
    expect(app).toEqual(["decide", "submit_reviewed"]);
  });
});

describe("generated guidance", () => {
  for (const mode of MODES) {
    it(`instructions mention every tool the registry exposes (${mode}) and the count`, () => {
      const ins = renderInstructions(specs, mode);
      const model = modelSpecs(specs, mode);
      for (const s of model) expect(ins, s.name).toContain(s.name);
      expect(ins).toContain(`offers ${model.length} tools`);
      expect(ins.length).toBeLessThan(6000);
      const inactive = specs.filter((s) => !activeSpecs(specs, mode).includes(s) && s.access === "model");
      for (const s of inactive) expect(ins, s.name).not.toContain(s.name);
    });
    it(`every topic renders without unknown tools (${mode})`, () => {
      for (const t of TOPICS) expect(renderGuide(t, specs, mode).text).toContain(`JOBWATCH GUIDE: ${t}`);
    });
  }
  it("widget policy appears in the instructions", () => {
    expect(renderInstructions(specs, "on_request")).toMatch(/Never open a widget unless the person asks[\s\S]*open_dashboard/);
    expect(renderInstructions(specs, "off")).toContain("opens no widgets");
  });
  it("guidance files reference only registered tools and leave no placeholders", () => {
    const dir = join(ROOT, "guidance");
    const files = [join(dir, "instructions.md"), join(dir, "widgets-on-request.md"), join(dir, "widgets-off.md"), ...readdirSync(join(dir, "topics")).map((f) => join(dir, "topics", f))];
    const names = new Set(specs.map((s) => s.name));
    for (const f of files) {
      for (const m of readFileSync(f, "utf8").matchAll(/\{\{tool:([a-z_]+)\}\}/g)) expect(names.has(m[1]), `${f}: ${m[1]}`).toBe(true);
    }
    for (const t of TOPICS) expect(renderGuide(t, specs, "on_request").text).not.toContain("{{");
  });
  it("is agnostic: no host, person, machine or occupation specifics in guidance or tool text", () => {
    const banned = /Codex|ChatGPT|OpenAI|Claude|phrog|\/home\/|~\/|jobwatch\.example|retail|accountant|nurse|developer/i;
    const dir = join(ROOT, "guidance");
    const texts = [
      ...[join(dir, "instructions.md"), join(dir, "widgets-on-request.md"), join(dir, "widgets-off.md"), join(dir, "skills.json")].map((f) => readFileSync(f, "utf8")),
      ...readdirSync(join(dir, "topics")).map((f) => readFileSync(join(dir, "topics", f), "utf8")),
      ...specs.map((s) => [s.title, s.summary, s.whenToUse, s.whenNotToUse, s.next].join(" ")),
    ];
    for (const t of texts) expect(t).not.toMatch(banned);
  });
  it("skills have bundled descriptions and valid topics", () => {
    for (const [name, k] of Object.entries(SKILLS)) {
      expect(k.description.length, name).toBeGreaterThan(20);
      for (const t of k.topics) expect(TOPICS).toContain(t);
    }
  });
});

describe("generated files are up to date (run `npm run docs`)", () => {
  it("the guidance bundle matches guidance/", () => {
    expect(readFileSync(BUNDLE_PATH, "utf8")).toBe(buildBundle());
  });
  it("the README tool reference matches the registry", () => {
    const readme = readFileSync(join(ROOT, "README.md"), "utf8");
    expect(readme).toBe(updateReadme(readme, specs));
  });
});
