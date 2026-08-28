import { describe, expect, it } from "vitest";

const manifestSources = import.meta.glob<string>("../../modules/*/manifest.tsx", {
  eager: true,
  import: "default",
  query: "?raw",
});

const entrySources = import.meta.glob<string>("../../main.tsx", {
  eager: true,
  import: "default",
  query: "?raw",
});

describe("frontend lazy-loading architecture", () => {
  it("keeps feature implementations out of eager module manifests", () => {
    const staticFeatureImport = /(^|\n)\s*import\s+(?!type\b)(?!\()[\s\S]*?\sfrom\s+["'][^"']*\/features\//g;

    for (const [path, source] of Object.entries(manifestSources)) {
      expect(source, `${path} must lazy-load runtime feature implementations`).not.toMatch(staticFeatureImport);
    }
  });

  it("keeps DCST styles behind the DCST lazy boundary", () => {
    const mainSource = Object.values(entrySources)[0] ?? "";
    expect(mainSource).not.toContain("styles/dcst.css");
  });
});
