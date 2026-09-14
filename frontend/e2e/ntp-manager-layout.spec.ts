import { expect, test, type Page } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";
import type { NtpConfiguration, NtpDiagnostics } from "../src/modules/ntp-manager/api/client";

const config: NtpConfiguration = {
  mode: "client_server", backend: "chrony", sources: [{ server: "ntp-primary.long-infrastructure-name.example.internal", kind: "server", enabled: true }],
  allowed_networks: [], local_time_when_unsynced: false, local_stratum: 10, managed_path: "/etc/chrony/chrony.conf", unmanaged_config_detected: false,
};
const data: NtpDiagnostics = {
  available: true, backend: "chrony", role: "client_server", synchronized: true, health: "healthy", timezone: "Europe/Warsaw",
  system_time: 1700000000, collected_at: 1700000000, source: config.sources[0].server, offset: "0.02 ms", stratum: 2,
  reachability: "377", jitter: "0.01 ms", service: "chrony", service_state: "active", enabled: true,
  sources: [{ ...config.sources[0], selected: true, state: "selected", stratum: 2, reach: 377 }],
  summary: { source_count: 1, selected_count: 1, reachable_count: 1, client_count: 0 },
  firewall: { backend: "ufw", status: "unknown", managed_by_webnas: false }, metrics: {}, warnings: [],
};

async function installNtpApi(page: Page, theme: "light" | "dark") {
  await installMockApi(page);
  // Reuse the complete shared profile, adding only NTP-specific permissions.
  await page.goto("/");
  const profile = await page.evaluate(async () => {
    const response = await fetch("/api/settings/me");
    return response.json() as Promise<{ permissions: string[]; [key: string]: unknown }>;
  });
  await page.route("**/api/settings/me", (route) => route.fulfill({ json: {
    ...profile, theme, permissions: [...profile.permissions, "ntp.view", "ntp.manage", "ntp.sync", "ntp.service.control", "ntp.firewall.manage"],
  } }));
  await page.route("**/api/modules", (route) => route.fulfill({ json: [{ id: "ntp-manager", state: { installed: true } }] }));
  await page.route("**/api/modules/ntp-manager/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/dashboard") || path.endsWith("/diagnostics")) return route.fulfill({ json: data });
    if (path.endsWith("/config")) return route.fulfill({ json: config });
    return route.fulfill({ json: { items: [], total: 0 } });
  });
  await page.reload();
  await openDesktopApp(page, "NTP Manager");
}

for (const theme of ["light", "dark"] as const) {
  test(`NTP workspace uses window width and stays scrollable in the ${theme} desktop`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installNtpApi(page, theme);
    const window = page.locator('.desktop-window.active[aria-label="NTP Manager"]');
    const app = window.locator(".ntp-manager-app");
    const content = app.locator(".ntp-content");
    const nav = app.getByRole("navigation", { name: "Sekcje NTP Manager" });
    await expect(app.getByRole("heading", { name: "Czas zsynchronizowany" })).toBeVisible();
    await expect(page.locator(".desktop").first()).toHaveClass(new RegExp(theme));

    for (const width of [975, 720, 390]) {
      // The viewport stays wide: only the actual desktop window is resized.
      await window.evaluate((element, size) => {
        const node = element as HTMLElement;
        node.style.setProperty("width", `${size}px`, "important");
        node.style.setProperty("min-width", "0", "important");
        node.style.setProperty("height", "640px", "important");
        node.style.setProperty("left", "20px", "important");
        node.style.setProperty("top", "20px", "important");
      }, width);
      await expect.poll(() => nav.evaluate((element) => getComputedStyle(element).flexDirection)).toBe(width <= 820 ? "row" : "column");
      for (const target of [app, content]) {
        expect(await target.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      }
      await nav.getByRole("button", { name: "Serwer NTP" }).click();
      const save = app.getByRole("button", { name: "Zapisz konfigurację serwera" });
      await save.scrollIntoViewIfNeeded();
      await expect(save).toBeInViewport();
      await expect(app.getByLabel("Tryb NTP")).toHaveValue("client_server");
      await nav.getByRole("button", { name: /^Źródła czasu/ }).click();
      await expect(app.getByRole("table", { name: "Źródła czasu NTP" })).toBeVisible();
      expect(await content.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      await nav.getByRole("button", { name: "Przegląd" }).click();
      await expect(nav.getByRole("button", { name: "Przegląd" })).toHaveAttribute("aria-current", "page");
      await testInfo.attach(`ntp-${theme}-${width}`, { body: await window.screenshot(), contentType: "image/png" });
    }
  });
}
