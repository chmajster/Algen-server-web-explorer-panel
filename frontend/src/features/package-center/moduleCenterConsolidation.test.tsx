import { describe, expect, it } from "vitest";
import moduleCenterManifests from "../../modules/module-center/manifest";
import packageCenterManifest from "../../modules/package-center/manifest";
import { canRunPackageAction } from "./packageState";

describe("Module Center consolidation", () => {
  it("keeps the legacy modules app hidden and exposes Package Center to module viewers", () => {
    const legacyModules = moduleCenterManifests.find((manifest) => manifest.id === "modules");

    expect(legacyModules?.hidden).toBe(true);
    expect(legacyModules?.labelKey).toBe("app.store");
    expect(legacyModules?.permission).toBe("modules.view");
    expect(packageCenterManifest.id).toBe("store");
    expect(packageCenterManifest.permission).toBe("modules.view");
  });

  it("maps lifecycle actions to the existing granular module permissions", () => {
    const viewOnly = ["modules.view"];
    const operator = ["modules.view", "modules.configure"];
    const installer = ["modules.view", "modules.install", "modules.update"];

    expect(canRunPackageAction("install", viewOnly)).toBe(false);
    expect(canRunPackageAction("start", viewOnly)).toBe(false);
    expect(canRunPackageAction("start", operator)).toBe(true);
    expect(canRunPackageAction("install", installer)).toBe(true);
    expect(canRunPackageAction("update", installer)).toBe(true);
    expect(canRunPackageAction("uninstall", installer)).toBe(false);
  });
});
