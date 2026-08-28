#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "..");
const schema = resolve(frontend, "..", "openapi", "openapi.json");
const output = resolve(frontend, "src", "core", "api", "generated", "api-types.ts");
const check = process.argv.includes("--check");
const npx = process.platform === "win32" ? "npx.cmd" : "npx";

if (!existsSync(schema)) {
  console.error("OpenAPI snapshot is missing. Run: python scripts/generate-openapi.py");
  process.exit(1);
}

const generated = spawnSync(npx, ["--yes", "openapi-typescript@7.13.0", schema], {
  cwd: frontend,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "inherit"],
});
if (generated.status !== 0) process.exit(generated.status ?? 1);

const body = generated.stdout.replace(/^\uFEFF/, "").trimStart();
const expected = `/* AUTO-GENERATED FILE.\n * DO NOT EDIT MANUALLY.\n * Source: openapi/openapi.json\n * Generator: openapi-typescript@7.13.0\n */\n${body.endsWith("\n") ? body : `${body}\n`}`;

if (check) {
  if (!existsSync(output) || readFileSync(output, "utf8") !== expected) {
    console.error("Generated API types are stale. Run: npm run api:generate");
    process.exit(1);
  }
  process.exit(0);
}

mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, expected, "utf8");
console.log(output);
