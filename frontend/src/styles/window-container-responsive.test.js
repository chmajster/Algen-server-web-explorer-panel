import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

function read(relativePath) {
  return readFileSync(resolve(cwd(), relativePath), "utf8");
}

const rbac = read("src/features/admin/rbac-access.css");
const storage = read("src/features/storage/storage-manager.css");
const policy = read("src/modules/policy-as-code/policy-as-code.css");

const desktopWindowBreakpoint = "@container app-window (max-width: 56.25rem)";

describe("feature layouts inside resizable desktop windows", () => {
  it("makes RBAC collapse according to app-window width", () => {
    expect(rbac).toContain(".rbac-access { display: flex; flex-direction: column; gap: 14px; height: 100%; min-width: 0;");
    expect(rbac).toContain(desktopWindowBreakpoint);
  });

  it("makes Storage Manager react to medium and narrow app-window widths", () => {
    expect(storage).toContain("min-width: 0;");
    expect(storage).toContain(desktopWindowBreakpoint);
    expect(storage).toContain("@container app-window (max-width: 38.75rem)");
  });

  it("makes Policy-as-Code collapse according to app-window width", () => {
    expect(policy).toContain(desktopWindowBreakpoint);
    expect(policy).toContain(".policy-code-grid {\n    grid-template-columns: 1fr;");
  });
});
