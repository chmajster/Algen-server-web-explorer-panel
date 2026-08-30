import { describe, expect, it } from "vitest";
import manifest from "./manifest";

describe("Policy-as-Code manifest", () => {
  it("registers the module behind the policy view permission", () => {
    expect(manifest.id).toBe("policy-as-code");
    expect(manifest.moduleId).toBe("policy-as-code");
    expect(manifest.permission).toBe("policy.view");
    expect(manifest.category).toBe("security");
  });
});
