import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

function read(relativePath) {
  return readFileSync(resolve(cwd(), relativePath), "utf8");
}

const main = read("src/main.tsx");
const rbac = read("src/features/admin/rbac-access.css");
const storage = read("src/features/storage/storage-manager.css");
const policy = read("src/modules/policy-as-code/policy-as-code.css");
const apiExplorer = read("src/styles/api-explorer.css");
const orm = read("src/features/modules/os-repositories/offline-repository-manager.css");
const designSystem = read("src/styles/design-system.css");
const identity = read("src/styles/identity.css");
const dockerWindow = read("src/features/docker/docker-window.css");
const dockerApp = read("src/features/docker/DockerManagerApp.tsx");
const credentialsWindow = read("src/modules/credentials/credentials-window.css");
const credentialsManifest = read("src/modules/credentials/manifest.tsx");
const monitorWindow = read("src/features/admin/monitor-window.css");
const monitorApp = read("src/features/admin/MonitorApp.tsx");
const dcstWindow = read("src/features/dcst/dcst-window.css");
const dcstApp = read("src/features/dcst/DcstApp.tsx");
const packageWindow = read("src/features/package-center/package-center-window.css");
const packageApp = read("src/features/package-center/PackageCenterApp.tsx");
const settingsWindow = read("src/features/settings/settings-window.css");
const settingsManifest = read("src/modules/settings/manifest.tsx");
const operationProgress = read("src/features/package-center/operation-progress-window.css");

const desktopWindowBreakpoint = "@container app-window (max-width: 56.25rem)";

describe("feature-owned responsiveness inside resizable desktop windows", () => {
  it("does not route feature responsiveness through global bootstrap overrides", () => {
    expect(main).not.toContain("window-responsive-followups.css");
    expect(main).not.toContain("window-responsive-settings-gaps.css");
  });

  it("keeps RBAC responsive and safe for long permission data", () => {
    expect(rbac).toContain(desktopWindowBreakpoint);
    expect(rbac).toContain(".rbac-access { display: flex; flex-direction: column; gap: 14px; height: 100%; min-width: 0;");
    expect(rbac).toContain("overflow-wrap: anywhere; word-break: break-word;");
    expect(rbac).toContain(".rbac-effective,.rbac-audit,.rbac-ldap { min-width: 0;");
  });

  it("keeps Storage Manager responsive and intrinsic-size safe", () => {
    expect(storage).toContain(desktopWindowBreakpoint);
    expect(storage).toContain("@container app-window (max-width: 38.75rem)");
    expect(storage).toContain("minmax(min(100%, 130px), 1fr)");
    expect(storage).toContain(".storage-manager__table-wrap {\n  max-width: 100%;\n  overflow: auto;");
  });

  it("keeps Policy-as-Code responsive in its owning stylesheet", () => {
    expect(policy).toContain(desktopWindowBreakpoint);
    expect(policy).toContain(".policy-code-grid {\n    grid-template-columns: 1fr;");
  });

  it("keeps API Explorer window breakpoints next to API Explorer styles", () => {
    expect(apiExplorer).toContain("@container app-window (max-width: 65.625rem)");
    expect(apiExplorer).toContain("@container app-window (max-width: 43.75rem)");
    expect(apiExplorer).toContain("@container app-window (max-width: 28.75rem)");
    expect(apiExplorer).toContain("min-width: min(100%, 10rem);");
  });

  it("keeps Offline Repository Manager window rules next to the feature", () => {
    expect(orm).toContain("@container app-window (max-width: 51.25rem)");
    expect(orm).toContain("minmax(min(100%, 260px), 1fr)");
    expect(orm).toContain(".orm-diagnostic");
  });

  it("makes shared design-system primitives container-aware without a feature override layer", () => {
    expect(designSystem).toContain("@container app-window (max-width: 43.75rem)");
    expect(designSystem).toContain(".wn-page-header, .wn-section-header");
    expect(designSystem).toContain(".wn-table-scroll { width: 100%; max-width: 100%; overflow: auto; }");
  });

  it("keeps Identity compact layout in Identity styles", () => {
    expect(identity).toContain("@container app-window (max-width: 38.75rem)");
    expect(identity).toContain(".identity-search { min-width: min(11.25rem, 100%);");
    expect(identity).toContain(".identity-history article { grid-template-columns: auto minmax(0, 1fr);");
  });

  it("loads Docker window rules with Docker instead of main.tsx", () => {
    expect(dockerApp).toContain('import "./docker-window.css"');
    expect(dockerWindow).toContain(desktopWindowBreakpoint);
    expect(dockerWindow).toContain("@container app-window (max-width: 38.75rem)");
    expect(dockerWindow).toContain("minmax(min(100%, 18.75rem), 1fr)");
  });

  it("loads Credentials window rules with the Credentials module", () => {
    expect(credentialsManifest).toContain('import "./credentials-window.css"');
    expect(credentialsWindow).toContain("@container app-window (max-width: 70rem)");
    expect(credentialsWindow).toContain("@container app-window (max-width: 56rem)");
    expect(credentialsWindow).toContain("@container app-window (max-width: 42rem)");
    expect(credentialsWindow).toContain("min-width: min(34rem, 100%);");
  });

  it("loads Resource Monitor sizing fixes with Monitor", () => {
    expect(monitorApp).toContain('import "./monitor-window.css"');
    expect(monitorWindow).toContain("minmax(min(100%, 10rem), 1fr)");
    expect(monitorWindow).toContain("width: min(16.25rem, 100%);");
  });

  it("loads DCST compact rules with DCST", () => {
    expect(dcstApp).toContain('import "./dcst-window.css"');
    expect(dcstWindow).toContain("minmax(min(100%, 11rem), 1fr)");
    expect(dcstWindow).toContain("@container app-window (max-width: 34rem)");
  });

  it("loads Package Center container rules with Package Center", () => {
    expect(packageApp).toContain('import "./package-center-window.css"');
    expect(packageWindow).toContain("@container package-center (max-width: 32.5rem)");
    expect(packageWindow).toContain(".package-job > header");
  });

  it("loads Settings window rules from the Settings module", () => {
    expect(settingsManifest).toContain('import "../../features/settings/settings-window.css"');
    expect(settingsWindow).toContain("@container app-window (max-width: 57.5rem)");
    expect(settingsWindow).toContain("@container app-window (max-width: 43.75rem)");
    expect(settingsWindow).toContain("@container app-window (max-width: 26.25rem)");
    for (const selector of [
      ".desktop .password-settings",
      ".desktop .admin-summary-grid",
      ".desktop .network-settings-tabs",
      ".desktop .settings-content.identity-content",
      ".desktop .wallpaper-gallery",
    ]) expect(settingsWindow).toContain(selector);
  });

  it("keeps native Operation Progress responsive to its desktop window", () => {
    expect(operationProgress).toContain("@container app-window (max-width: 42rem)");
    expect(operationProgress).toContain(".desktop .operation-progress-native > footer");
    expect(operationProgress).toContain("grid-template-columns: 4.75rem minmax(0, 1fr);");
  });
});
