import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const styles = readFileSync(resolve(cwd(), "src/styles/dsm.css"), "utf8");
const main = readFileSync(resolve(cwd(), "src/main.tsx"), "utf8");

describe("DSM shared responsive layer", () => {
  it("loads after the legacy styles so shared patterns cover every module", () => {
    expect(main.indexOf('import "./styles/dsm.css"')).toBeGreaterThan(main.indexOf('import "./styles/app.css"'));
  });

  it.each([
    ".module-navigation",
    ".package-tabs",
    ".docker-manager-layout > nav",
    ".settings-sidebar",
    ".logs-sidebar",
    ".module-form-grid",
    ".module-table-wrap",
    ".cron-table-wrap",
    ".identity-table-wrap",
    ".file-toolbar",
  ])("covers the shared application pattern %s", (selector) => {
    expect(styles).toContain(selector);
  });

  it("uses window container queries for narrow desktop windows and phones", () => {
    expect(styles).toContain("@container app-window (max-width: 47.5rem)");
    expect(styles).toContain("@container app-window (max-width: 40rem)");
    expect(styles).toContain("@container app-window (max-width: 30rem)");
    expect(styles).toContain("@container package-center (max-width: 48rem)");
  });

  it("keeps phone chrome within dynamic viewport and safe-area bounds", () => {
    expect(styles).toContain("width: 100dvw");
    expect(styles).toContain("height: 100dvh");
    expect(styles).toContain("env(safe-area-inset-top)");
    expect(styles).toContain("env(safe-area-inset-bottom)");
    expect(styles).toContain("min-height: 2.75rem");
  });

  it("makes every custom dialog family full screen on phones", () => {
    for (const selector of [
      ".desktop .network-modal",
      ".docker-wizard",
      ".ansible-details",
      ".modal-panel.update-progress-dialog",
      ".modal-panel.update-completion-dialog",
      ".modal-panel.modal-wide.hosts-enrollment-dialog",
    ]) expect(styles).toContain(selector);
  });
});
