import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve("src/modules/ntp-manager/ntp-manager.css"), "utf8");

describe("NTP window layout contract", () => {
  it("uses the module width instead of only the browser viewport", () => {
    expect(css).toContain("container: ntp-manager / inline-size");
    expect(css).toContain("@container ntp-manager (max-width: 820px)");
    expect(css).toContain("@container ntp-manager (max-width: 400px)");
  });
  it("isolates styles from other infrastructure modules and inherits theme tokens", () => {
    expect(css).not.toContain(".infra-manager-app");
    expect(css).toContain("var(--surface-primary");
    expect(css).toContain("var(--text-primary");
    expect(css).toContain("var(--accent");
  });
  it("keeps content scrollable and supports keyboard focus and reduced motion", () => {
    expect(css).toMatch(/\.ntp-content\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*auto;/);
    expect(css).toContain(":focus-visible");
    expect(css).toContain("prefers-reduced-motion: reduce");
    expect(css).toContain("overflow-wrap: anywhere");
  });
});
