import { HardDrive } from "lucide-react";
import { describe, expect, it } from "vitest";
import type { FrontendModuleManifest } from "./moduleRegistry";
import { ModuleRegistry } from "./moduleRegistry";
import { builtinModules, moduleRegistry } from "./builtinModules";

const item = (id: FrontendModuleManifest["id"], extra: Partial<FrontendModuleManifest> = {}): FrontendModuleManifest => ({
  id, labelKey: `app.${id}`, icon: <HardDrive />, render: () => null, ...extra,
});

describe("frontend ModuleRegistry", () => {
  it("is the canonical launcher catalog", () => {
    expect(moduleRegistry.apps()).toHaveLength(builtinModules.length);
    expect(moduleRegistry.visibleApps().map((module) => module.id)).toContain("files");
    expect(moduleRegistry.visibleApps().map((module) => module.id)).not.toContain("module");
  });

  it("rejects duplicate ids and missing dependencies", () => {
    expect(() => new ModuleRegistry([item("files"), item("files")])).toThrow(/Duplicate/);
    expect(() => new ModuleRegistry([item("files", { dependencies: ["logs"] })])).toThrow(/missing module/);
  });

  it("applies permissions consistently for launcher, desktop and taskbar", () => {
    const registry = new ModuleRegistry([item("files", { permission: "files.view" })]);
    expect(registry.availableFor("files", ["files.view"], false)).toBe(true);
    expect(registry.availableFor("files", [], true)).toBe(false);
  });
});
