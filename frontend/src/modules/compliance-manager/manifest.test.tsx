import { describe, expect, it } from "vitest";
import manifest from "./manifest";

describe("Compliance Manager manifest", () => {
  it("registers the installed module and RBAC boundary", () => {
    expect(manifest.id).toBe("compliance-manager");
    expect(manifest.moduleId).toBe("compliance-manager");
    expect(manifest.permission).toBe("compliance.view");
    expect(manifest.dependencies).toContain("firewall-manager");
  });
});
