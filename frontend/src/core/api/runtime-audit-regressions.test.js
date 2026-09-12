import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

function frontendSources(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return frontendSources(path);
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.(ts|tsx)$/.test(entry.name)) return [];
    return [path];
  });
}

const sourceRoot = resolve(cwd(), "src");
const sources = frontendSources(sourceRoot).map((path) => ({ path, text: readFileSync(path, "utf8") }));

function source(path) {
  return readFileSync(resolve(cwd(), path), "utf8");
}

describe("runtime audit regressions", () => {
  it("does not open direct-origin API EventSource streams", () => {
    const offenders = sources
      .filter(({ text }) => /new\s+EventSource\(\s*["'`]\/api\//.test(text))
      .map(({ path }) => path);
    expect(offenders).toEqual([]);
  });

  it("does not keep direct-origin API download links in JSX", () => {
    const offenders = sources
      .filter(({ text }) => /href\s*=\s*(?:["']\/api\/|\{\s*`\/api\/)/.test(text))
      .map(({ path }) => path);
    expect(offenders).toEqual([]);
  });

  it("does not declare apiUrl more than once in a module", () => {
    const offenders = sources
      .filter(({ text }) => (text.match(/\bapiUrl\b/g) || []).length > 0)
      .filter(({ text }) => {
        const imported = [...text.matchAll(/import\s*\{([^}]*)\}\s*from\s*["'][^"']+["'];/g)]
          .flatMap((match) => match[1].split(",").map((name) => name.trim().replace(/^type\s+/, "")))
          .filter((name) => name === "apiUrl").length;
        return imported > 1;
      })
      .map(({ path }) => path);
    expect(offenders).toEqual([]);
  });

  it("keeps API URL resolution inside transport without a self-import", () => {
    const transport = source("src/core/api/transport.ts");
    expect(transport).toContain("export function apiUrl(path: string) { return targetUrl(path); }");
    expect(transport).not.toContain('from "./transport"');
  });

  it("routes file downloads through the configured API base URL", () => {
    const client = source("src/modules/files/api/client.ts");
    expect(client).toContain('import { apiUrl, request } from "../../../core/api/transport";');
    expect(client).toContain('return apiUrl(`/api/files/download?path=${encodeURIComponent(path)}`);');
  });

  it("keeps network-management localization calls single-layered", () => {
    const network = source("src/features/settings/NetworkManagementPanels.tsx");
    expect(network).toContain('"Konfiguracja zachowana": "Configuration kept"');
    expect(network).toContain('readStorageValue("webnas_language")');
    expect(network).not.toContain("networkText(networkText(");
  });

  it("does not access Web Storage directly outside the persistence boundary", () => {
    const offenders = sources
      .filter(({ path }) => !path.endsWith("/core/persistence.ts"))
      .filter(({ text }) => /(?:window\.)?(?:localStorage|sessionStorage)\s*\./.test(text))
      .map(({ path }) => path);
    expect(offenders).toEqual([]);
  });
});
