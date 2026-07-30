import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const app = read("src/styles/app.css");
const base = read("src/styles/base.css");

describe("shared form control cascade", () => {
  it("keeps default control chrome at lower specificity than component styles", () => {
    expect(app).toContain(
      ':where(input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]), select, textarea)',
    );
    expect(base).toContain(".desktop :where(");
    expect(base).not.toMatch(
      /\.desktop input:not\(\[type="checkbox"\]\):not\(\[type="radio"\]\):not\(\[type="range"\]\)/,
    );
  });

  it.each([
    ["src/styles/settings.css", ".desktop .settings-search input"],
    ["src/styles/taskbar.css", ".desktop .launcher-search input"],
    ["src/styles/app.css", ".file-search input"],
    ["src/styles/logs.css", ".logs-search input"],
    ["src/styles/identity.css", ".identity-search input"],
    ["src/styles/modules.css", ".ansible-search input"],
    ["src/styles/modules.css", ".credential-search input"],
    ["src/styles/modules.css", ".playbook-library > header input"],
    ["src/features/package-center/package-center.css", ".package-search input"],
    ["src/styles/app.css", ".text-editor textarea"],
    ["src/styles/logs.css", ".logs-export select"],
    ["src/styles/modules.css", ".ansible-code-editor textarea"],
  ])("%s keeps %s visually integrated with its wrapper", (path, selector) => {
    const styles = read(path);
    const start = styles.indexOf(`${selector} {`);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(styles.slice(start, styles.indexOf("}", start))).toContain("border: 0");
  });
});
