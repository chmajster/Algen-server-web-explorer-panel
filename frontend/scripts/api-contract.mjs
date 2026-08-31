import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import process from "node:process";

const mode = process.argv[2];
if (!new Set(["generate", "check"]).has(mode)) {
  console.error("Usage: node scripts/api-contract.mjs <generate|check>");
  process.exit(2);
}

const root = resolve(import.meta.dirname, "..");
const cache = resolve(root, "node_modules/.cache/webnas-api-contract");
const spec = resolve(cache, "openapi.json");
const candidate = resolve(cache, "api-types.ts");
const target = resolve(root, "src/generated/api-types.ts");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const marker = "// AUTO-GENERATED. DO NOT EDIT.\n";

function reportContractDrift(committed, generated) {
  const previous = committed.split("\n");
  const next = generated.split("\n");
  const limit = Math.max(previous.length, next.length);
  let shown = 0;
  for (let index = 0; index < limit && shown < 80; index += 1) {
    if (previous[index] === next[index]) continue;
    console.error(`@@ line ${index + 1} @@`);
    console.error(`- ${previous[index] ?? "<missing>"}`);
    console.error(`+ ${next[index] ?? "<missing>"}`);
    shown += 1;
  }
  if (shown === 80) console.error("... additional contract differences omitted");
}

mkdirSync(cache, { recursive: true });
const exportResult = spawnSync(python, [resolve(root, "../scripts/export_openapi.py"), "--output", spec], { stdio: "inherit" });
if (exportResult.status !== 0) process.exit(exportResult.status ?? 1);

const generation = spawnSync(npx, ["--no-install", "openapi-typescript", spec, "--output", candidate], { stdio: "inherit", cwd: root });
if (generation.status !== 0) process.exit(generation.status ?? 1);

const generated = readFileSync(candidate, "utf8").replace(/^\/\/ AUTO-GENERATED[^\n]*\n/i, "");
const finalContent = marker + generated;

if (mode === "generate") {
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, finalContent, "utf8");
  console.log(`Generated ${target}`);
} else {
  const committed = existsSync(target) ? readFileSync(target, "utf8") : "";
  if (committed !== finalContent) {
    console.error("OpenAPI TypeScript contract is stale. Run: npm run api:generate");
    reportContractDrift(committed, finalContent);
    rmSync(candidate, { force: true });
    process.exit(1);
  }
  console.log("OpenAPI TypeScript contract is current.");
}

rmSync(candidate, { force: true });
