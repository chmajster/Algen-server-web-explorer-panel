import { expect, test } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

test("compact taskbar groups do not overlap at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await installMockApi(page);
  await page.goto("/");

  const primary = page.locator(".taskbar-primary");
  const tray = page.locator(".system-tray");
  await expect(primary).toBeVisible();
  await expect(tray).toBeVisible();

  const primaryBox = await primary.boundingBox();
  const trayBox = await tray.boundingBox();
  expect(primaryBox).not.toBeNull();
  expect(trayBox).not.toBeNull();
  expect(primaryBox!.x + primaryBox!.width).toBeLessThanOrEqual(trayBox!.x + 1);
});

test("window close hover keeps a white icon on danger background", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const close = page.locator('.desktop-window.active[aria-label="File Manager"] .window-close');
  await close.hover();

  const style = await close.evaluate((element) => {
    const computed = getComputedStyle(element);
    return { color: computed.color, backgroundColor: computed.backgroundColor };
  });

  expect(style.color).toBe("rgb(255, 255, 255)");
  expect(style.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
});

test("browser theme color tracks desktop light and dark classes", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await installMockApi(page);
  await page.goto("/");

  const desktop = page.locator(".desktop").first();
  const meta = page.locator('meta[name="theme-color"]');
  await expect(desktop).toHaveClass(/light/);
  await expect(meta).toHaveAttribute("content", "#f4f5f6");

  await desktop.evaluate((element) => {
    element.classList.remove("light");
    element.classList.add("dark");
  });
  await expect(meta).toHaveAttribute("content", "#20252a");

  await desktop.evaluate((element) => {
    element.classList.remove("dark");
    element.classList.add("light");
  });
  await expect(meta).toHaveAttribute("content", "#f4f5f6");
});
