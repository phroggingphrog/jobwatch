// `npm run docs`: regenerates everything derived from guidance/ and the tool registry.
//   src/generated/guidance-bundle.ts  (guidance/*.md bundled for the server)
//   README.md tool reference          (from src/tools.ts)
// Pass --check to fail instead of writing when something is stale.
import * as nodeModule from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { BUNDLE_PATH, ROOT, buildBundle } from "./bundle.mjs";

const check = process.argv.includes("--check");
const stale = [];
function sync(path, next) {
  let current = "";
  try { current = readFileSync(path, "utf8"); } catch { /* missing */ }
  if (current === next) return;
  if (check) stale.push(path);
  else writeFileSync(path, next);
}

sync(BUNDLE_PATH, buildBundle());               // before the registry is imported: it reads the bundle
if (nodeModule.registerHooks) {
  // synchronous hooks (Node >= 22.15)
  nodeModule.registerHooks({
    resolve(specifier, context, next) {
      try { return next(specifier, context); }
      catch (e) {
        if (specifier.startsWith(".") && specifier.endsWith(".js")) return next(specifier.slice(0, -3) + ".ts", context);
        throw e;
      }
    },
  });
} else {
  nodeModule.register("./resolve-ts.mjs", import.meta.url);
}
const { specs } = await import("../src/tools.ts");
const { updateReadme } = await import("../src/docs.ts");
const readmePath = join(ROOT, "README.md");
sync(readmePath, updateReadme(readFileSync(readmePath, "utf8"), specs));

if (stale.length) {
  console.error(`Stale generated files (run \`npm run docs\`):\n${stale.join("\n")}`);
  process.exit(1);
}
console.log(check ? "generated files are up to date" : "generated files written");
