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
const followups = read("src/styles/window-responsive-followups.css");
const main = read("src/main.tsx");

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

  it("loads the follow-up responsive layer after the UI review fixes", () => {
    expect(main).toContain('import "./styles/window-responsive-followups.css"');
    expect(main.indexOf('import "./styles/window-responsive-followups.css"')).toBeGreaterThan(main.indexOf('import "./styles/ui-review-fixes.css"'));
  });

  it("makes API Explorer summary cards and filters follow the app-window width", () => {
    expect(followups).toContain("@container app-window (max-width: 65.625rem)");
    expect(followups).toContain("@container app-window (max-width: 43.75rem)");
    expect(followups).toContain("@container app-window (max-width: 28.75rem)");
    expect(followups).toContain(".desktop .api-explorer-stats");
    expect(followups).toContain(".desktop .api-explorer-filters .wn-form-field");
    expect(followups).toContain("min-width: min(100%, 10rem);");
  });

  it("makes Offline Repository Manager forms follow the app-window width", () => {
    expect(followups).toContain("@container app-window (max-width: 51.25rem)");
    expect(followups).toContain(".desktop .orm-form-grid");
    expect(followups).toContain(".desktop .orm-diagnostic");
  });

  it("makes Docker container controls follow the app-window width", () => {
    expect(followups).toContain(desktopWindowBreakpoint);
    expect(followups).toContain("@container app-window (max-width: 38.75rem)");
    expect(followups).toContain(".desktop .docker-container-summary");
    expect(followups).toContain(".desktop .docker-containers-toolbar .docker-search");
  });

  it("makes Credentials toolbar and forms follow the app-window width", () => {
    expect(followups).toContain("@container app-window (max-width: 70rem)");
    expect(followups).toContain("@container app-window (max-width: 56rem)");
    expect(followups).toContain("@container app-window (max-width: 42rem)");
    expect(followups).toContain(".desktop .credentials-toolbar");
    expect(followups).toContain(".desktop .credentials-form-grid");
    expect(followups).toContain("min-width: min(34rem, 100%);");
  });

  it("makes shared design-system headers follow app-window width", () => {
    expect(followups).toContain("@container app-window (max-width: 43.75rem)");
    expect(followups).toContain(".desktop .wn-page-header");
    expect(followups).toContain(".desktop .wn-section-header");
    expect(followups).toContain(".desktop .wn-search-input");
  });

  it("makes Identity compact controls follow app-window width", () => {
    expect(followups).toContain("@container app-window (max-width: 38.75rem)");
    expect(followups).toContain(".desktop .identity-tabs");
    expect(followups).toContain(".desktop .identity-toolbar");
    expect(followups).toContain(".desktop .identity-history article");
  });

  it("guards intrinsic grids against narrow-window overflow", () => {
    for (const selector of [
      ".desktop .orm-checkbox-grid",
      ".desktop .storage-manager__tool-grid",
      ".desktop .docker-container-detail-grid",
      ".desktop .docker-app-grid",
      ".desktop .docker-inspect-grid",
      ".desktop .docker-path-folders",
      ".desktop .dcst-app .checkbox-grid",
      ".desktop .monitor-overview-grid",
    ]) {
      expect(followups).toContain(selector);
    }
    expect(followups).toContain("minmax(min(100%, 16.25rem), 1fr)");
    expect(followups).toContain("minmax(min(100%, 18.75rem), 1fr)");
  });

  it("sizes Resource Monitor process search against its parent", () => {
    expect(followups).toContain(".desktop .monitor-process-tools input");
    expect(followups).toContain("width: min(16.25rem, 100%);");
    expect(followups).toContain("max-width: 100%;");
  });

  it("makes Package Center job cards follow package-center width", () => {
    expect(followups).toContain("@container package-center (max-width: 32.5rem)");
    expect(followups).toContain(".package-job > header");
    expect(followups).toContain(".package-job-meta");
  });

  it("stacks DCST detail pairs in compact app windows", () => {
    expect(followups).toContain("@container app-window (max-width: 34rem)");
    expect(followups).toContain(".desktop .dcst-detail-list > div");
  });

  it("mirrors narrow Settings feature pages against app-window width", () => {
    expect(followups).toContain("@container app-window (max-width: 43.75rem)");
    expect(followups).toContain("@container app-window (max-width: 26.25rem)");
    for (const selector of [
      ".desktop .settings-content.identity-content",
      ".desktop .personalization-link-card",
      ".desktop .wallpaper-hero",
      ".desktop .wallpaper-gallery",
      ".desktop .wallpaper-options > label",
      ".desktop .update-settings-status",
      ".desktop .settings-details",
    ]) {
      expect(followups).toContain(selector);
    }
  });
});
