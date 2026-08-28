import { gzipSync } from "node:zlib";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const distDir = resolve("dist");
const assetsDir = join(distDir, "assets");
const checkBudget = process.argv.includes("--check");
const budgetPath = resolve("bundle-budget.json");

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

function metrics(path) {
  const content = readFileSync(path);
  return {
    file: relative(distDir, path).replaceAll("\\", "/"),
    raw: content.length,
    gzip: gzipSync(content, { level: 9 }).length,
  };
}

function formatBytes(value) {
  return `${(value / 1024).toFixed(2)} KiB`;
}

const html = readFileSync(join(distDir, "index.html"), "utf8");
const entryMatch = html.match(/<script[^>]+src=["']([^"']+\.js)["']/);
if (!entryMatch) throw new Error("Could not determine the JavaScript entry chunk from dist/index.html");

const entryPath = join(distDir, entryMatch[1].replace(/^\//, ""));
if (!statSync(entryPath).isFile()) throw new Error(`Entry chunk does not exist: ${entryPath}`);

const assets = filesUnder(assetsDir)
  .filter((path) => path.endsWith(".js") || path.endsWith(".css"))
  .map(metrics)
  .sort((left, right) => right.raw - left.raw);
const entry = metrics(entryPath);
const jsChunks = assets.filter((asset) => asset.file.endsWith(".js"));
const cssChunks = assets.filter((asset) => asset.file.endsWith(".css"));

console.log("Bundle report");
console.log(`Entry: ${entry.file} | raw ${formatBytes(entry.raw)} | gzip ${formatBytes(entry.gzip)}`);
console.log(`JavaScript chunks: ${jsChunks.length}; CSS chunks: ${cssChunks.length}; assets: ${assets.length}`);
console.log("Largest assets:");
for (const asset of assets.slice(0, 12)) {
  console.log(`- ${asset.file}: raw ${formatBytes(asset.raw)} | gzip ${formatBytes(asset.gzip)}`);
}

if (checkBudget) {
  const budget = JSON.parse(readFileSync(budgetPath, "utf8"));
  const failures = [];
  if (entry.raw > budget.entryRawBytes) failures.push(`entry raw ${entry.raw} > ${budget.entryRawBytes}`);
  if (entry.gzip > budget.entryGzipBytes) failures.push(`entry gzip ${entry.gzip} > ${budget.entryGzipBytes}`);
  if (failures.length) {
    console.error(`Bundle budget exceeded: ${failures.join(", ")}`);
    process.exitCode = 1;
  } else {
    console.log(`Bundle budget OK: raw <= ${formatBytes(budget.entryRawBytes)}, gzip <= ${formatBytes(budget.entryGzipBytes)}`);
  }
}
