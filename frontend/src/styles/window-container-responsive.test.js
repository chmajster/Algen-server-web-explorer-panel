import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

function read(relativePath) {
  return readFileSync(resolve(cwd(), relativePath), "utf8");
}

const main = read("src/main.tsx");
const responsive = read("src/styles/responsive.css");
const dsm = read("src/styles/dsm.css");
const dialogCompat = read("src/styles/dialog-compat.css");
const fileManager = read("src/styles/file-manager.css");
const rbac = read("src/features/admin/rbac-access.css");
const storage = read("src/features/storage/storage-manager.css");
const policy = read("src/modules/policy-as-code/policy-as-code.css");
const apiExplorer = read("src/styles/api-explorer.css");
const orm = read("src/features/modules/os-repositories/offline-repository-manager.css");
const designSystem = read("src/styles/design-system.css");
const identity = read("src/styles/identity.css");
const moduleApp = read("src/features/modules/ModuleApp.tsx");
const ansibleWindow = read("src/features/modules/ansible/ansible-window.css");
const dockerWindow = read("src/features/docker/docker-window.css");
const dockerApp = read("src/features/docker/DockerManagerApp.tsx");
const credentialsWindow = read("src/modules/credentials/credentials-window.css");
const credentialsManifest = read("src/modules/credentials/manifest.tsx");
const hostsCredentialPicker = read("src/features/modules/hosts/hosts-credential-module-select.css");
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

  it("keeps global responsive.css limited to viewport-owned shell behavior", () => {
    for (const selector of [
      ".settings-app",
      ".package-toolbar",
      ".docker-manager-layout",
      ".file-workspace",
      ".policy-browser",
      ".credential-field-grid",
      ".module-form-grid",
      ".modal-footer > button",
    ]) expect(responsive).not.toContain(selector);
    expect(responsive).toContain(".desktop .taskbar-primary");
    expect(responsive).toContain(".desktop .app-launcher");
    expect(responsive).toContain(".desktop .notification-center");
    expect(responsive).toContain("@media (prefers-reduced-motion: reduce)");
  });

  it("keeps shared module forms responsive in DSM", () => {
    expect(dsm).toContain("@container app-window (max-width: 47.5rem)");
    expect(dsm).toContain(".module-form-grid");
    expect(dsm).toContain("grid-template-columns: minmax(0, 1fr)");
  });

  it("keeps narrow dialog actions with the dialog owner", () => {
    expect(dialogCompat).toContain("@container app-window (max-width: 37.5rem)");
    expect(dialogCompat).toContain(".desktop .modal-footer > button");
    expect(dialogCompat).toContain("flex: 1 1 auto");
  });

  it("keeps File Manager responsive to its desktop window", () => {
    expect(fileManager).toContain("@container app-window (max-width: 57.5rem)");
    expect(fileManager).toContain("@container app-window (max-width: 37.5rem)");
    expect(fileManager).toContain("width: min(82cqw, 19.375rem);");
    expect(fileManager).toContain(".desktop .file-workspace");
  });

  it("keeps RBAC responsive and safe for long permission data", () => {
    expect(rbac).toContain(desktopWindowBreakpoint);
    expect(rbac).toContain("min-width: 0");
    expect(rbac).toContain("overflow-wrap: anywhere");
    expect(rbac).toContain("word-break: break-word");
  });

  it("keeps Storage Manager responsive and intrinsic-size safe", () => {
    expect(storage).toContain(desktopWindowBreakpoint);
    expect(storage).toContain("@container app-window (max-width: 38.75rem)");
    expect(storage).toContain("minmax(min(100%, 130px), 1fr)");
    expect(storage).toContain("max-width: 100%");
    expect(storage).toContain("overflow: auto");
  });

  it("keeps Policy-as-Code responsive in its owning stylesheet", () => {
    expect(policy).toContain(desktopWindowBreakpoint);
    expect(policy).toContain(".policy-code-grid");
    expect(policy).toContain("grid-template-columns: 1fr");
  });

  it("keeps API Explorer aligned with the current six-stat layout and app-window width", () => {
    expect(apiExplorer).toContain("grid-template-columns: repeat(3, minmax(0, 1fr))");
    expect(apiExplorer).toContain("@container app-window (max-width: 43.75rem)");
    expect(apiExplorer).toContain("@container app-window (max-width: 28.75rem)");
    expect(apiExplorer).not.toContain("@container app-window (max-width: 65.625rem)");
    expect(apiExplorer).toContain("min-width: min(100%, 10rem)");
    expect(apiExplorer).toContain("overflow-wrap: anywhere");
  });

  it("keeps Offline Repository Manager window rules next to the feature", () => {
    expect(orm).toContain("@container app-window (max-width: 51.25rem)");
    expect(orm).toContain("minmax(min(100%, 260px), 1fr)");
    expect(orm).toContain(".orm-diagnostic");
  });

  it("makes shared design-system primitives container-aware without a feature override layer", () => {
    expect(designSystem).toContain("@container app-window (max-width: 43.75rem)");
    expect(designSystem).toContain(".wn-page-header, .wn-section-header");
    expect(designSystem).toContain(".wn-table-scroll");
    expect(designSystem).toContain("max-width: 100%");
  });

  it("keeps Identity compact layout in Identity styles", () => {
    expect(identity).toContain("@container app-window (max-width: 38.75rem)");
    expect(identity).toContain("min-width: min(11.25rem, 100%)");
    expect(identity).toContain("grid-template-columns: auto minmax(0, 1fr)");
  });

  it("loads Ansible credential window rules with the module owner", () => {
    expect(moduleApp).toContain('import "./ansible/ansible-window.css"');
    expect(ansibleWindow).toContain("@container app-window (max-width: 43.75rem)");
    expect(ansibleWindow).toContain(".credential-field-grid");
    expect(ansibleWindow).toContain("grid-template-columns: minmax(0, 1fr)");
  });

  it("loads Docker window rules with Docker instead of main.tsx", () => {
    expect(dockerApp).toContain('import "./docker-window.css"');
    expect(dockerWindow).toContain(desktopWindowBreakpoint);
    expect(dockerWindow).toContain("@container app-window (max-width: 38.75rem)");
    expect(dockerWindow).toContain(".docker-manager-layout");
    expect(dockerWindow).toContain("minmax(min(100%, 18.75rem), 1fr)");
  });

  it("loads Credentials window rules with the Credentials module", () => {
    expect(credentialsManifest).toContain('import "./credentials-window.css"');
    expect(credentialsWindow).toContain("@container app-window (max-width: 70rem)");
    expect(credentialsWindow).toContain("@container app-window (max-width: 56rem)");
    expect(credentialsWindow).toContain("@container app-window (max-width: 42rem)");
    expect(credentialsWindow).toContain("min-width: min(34rem, 100%)");
  });

  it("sizes the Hosts credential picker against its owner instead of the viewport", () => {
    expect(hostsCredentialPicker).toContain("width: min(24rem, 100%)");
    expect(hostsCredentialPicker).toContain("max-width: 100%");
    expect(hostsCredentialPicker).not.toContain("min-width: min(24rem, 82vw)");
  });

  it("loads Resource Monitor sizing fixes with Monitor", () => {
    expect(monitorApp).toContain('import "./monitor-window.css"');
    expect(monitorWindow).toContain("minmax(min(100%, 10rem), 1fr)");
    expect(monitorWindow).toContain("width: min(16.25rem, 100%)");
  });

  it("loads DCST compact rules with DCST and sizes drawers from the app window", () => {
    expect(dcstApp).toContain('import "./dcst-window.css"');
    expect(dcstWindow).toContain("minmax(min(100%, 11rem), 1fr)");
    expect(dcstWindow).toContain("width: min(40.625rem, max(32.5rem, 72%))");
    expect(dcstWindow).toContain("@container app-window (max-width: 34rem)");
  });

  it("loads all Package Center window breakpoints with Package Center", () => {
    expect(packageApp).toContain('import "./package-center-window.css"');
    expect(packageWindow).toContain("@container package-center (max-width: 56.25rem)");
    expect(packageWindow).toContain("@container package-center (max-width: 38.75rem)");
    expect(packageWindow).toContain("@container package-center (max-width: 32.5rem)");
    expect(packageWindow).toContain(".package-toolbar");
    expect(packageWindow).toContain(".package-job > header");
  });

  it("loads Settings window rules from the Settings module", () => {
    expect(settingsManifest).toContain('import "../../features/settings/settings-window.css"');
    expect(settingsWindow).toContain("@container app-window (max-width: 57.5rem)");
    expect(settingsWindow).toContain("@container app-window (max-width: 43.75rem)");
    expect(settingsWindow).toContain("@container app-window (max-width: 26.25rem)");
    for (const selector of [
      ".desktop .settings-app",
      ".desktop .setting-row",
      ".desktop .policy-browser",
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
    expect(operationProgress).toContain("grid-template-columns: 4.75rem minmax(0, 1fr)");
  });
});
