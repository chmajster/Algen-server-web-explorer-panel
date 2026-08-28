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

const managedModuleRouterSources = import.meta.glob<string>("../../features/modules/ModuleApp.tsx", {
  eager: true,
  import: "default",
  query: "?raw",
});

describe("frontend lazy-loading architecture", () => {
  it("keeps feature implementations out of eager module manifests", () => {
    const staticFeatureImport = /(^|\n)\s*import\s+(?!type\b)(?!\()[^;]+from\s+["'][^"']*\/features\//g;

    for (const [path, source] of Object.entries(manifestSources)) {
      expect(source, `${path} must lazy-load runtime feature implementations`).not.toMatch(staticFeatureImport);
    }
  });

  it("keeps specialized managed module implementations behind dynamic imports", () => {
    const source = Object.values(managedModuleRouterSources)[0] ?? "";
    const staticSpecializedImport = /(^|\n)\s*import\s+(?!type\b)(?!\()[^;]+from\s+["'](?:\.\/ManagedModuleApp|\.\/(?:samba|ansible|hosts|apmid|os-repositories|cron|dhcp)\/|\.\.\/docker\/)/g;
    expect(source).not.toMatch(staticSpecializedImport);
  });

  it("keeps DCST styles behind the DCST lazy boundary", () => {
    const mainSource = Object.values(entrySources)[0] ?? "";
    expect(mainSource).not.toContain("styles/dcst.css");
  });
});
