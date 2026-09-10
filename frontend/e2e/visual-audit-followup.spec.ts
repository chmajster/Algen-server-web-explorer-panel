import { expect, test, type Locator, type Page } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

async function installNativeModuleCatalog(page: Page) {
  await page.route("**/api/modules", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "firewall-manager", state: { installed: true } },
        { id: "security-center", state: { installed: true } },
        { id: "network-tools", state: { installed: true } },
      ]),
    });
  });
}

async function box(locator: Locator) {
  await expect(locator).toBeVisible();
  const result = await locator.boundingBox();
  expect(result).not.toBeNull();
  return result!;
}

async function contrastRatio(locator: Locator) {
  return locator.evaluate((element) => {
    function rgb(value: string) {
      const match = value.match(/rgba?\((\d+),?\s*(\d+),?\s*(\d+)/i);
      if (!match) throw new Error(`Unsupported computed color: ${value}`);
      return [Number(match[1]), Number(match[2]), Number(match[3])];
    }
    function luminance(parts: number[]) {
      const converted = parts.map((part) => {
        const value = part / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * converted[0] + 0.7152 * converted[1] + 0.0722 * converted[2];
    }
    const style = getComputedStyle(element);
    const foreground = luminance(rgb(style.color));
    const background = luminance(rgb(style.backgroundColor));
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
}

test("compact Settings hides the desktop sidebar and uses the full app width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Settings");

  const window = page.locator('.desktop-window.active[aria-label="Settings"]');
  const app = window.locator(".settings-app");
  const sidebar = window.locator(".settings-sidebar");

  await expect(sidebar).toBeHidden();
  const windowBox = await box(window.locator(".window-content"));
  const appBox = await box(app);
  expect(appBox.width).toBeGreaterThanOrEqual(windowBox.width - 2);
});

test("light-theme Network Tools keeps readable foreground/background contrast", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await installMockApi(page);
  await installNativeModuleCatalog(page);
  await page.goto("/");
  await openDesktopApp(page, "Network Tools");

  const app = page.locator('.desktop-window.active[aria-label="Network Tools"] .security-tool-app');
  const result = app.locator(".security-panel pre");
  await expect(app).toBeVisible();
  await expect(result).toBeVisible();
  expect(await contrastRatio(app)).toBeGreaterThanOrEqual(4.5);
  expect(await contrastRatio(result)).toBeGreaterThanOrEqual(4.5);
});

test("phone File Manager tree does not cover the file list", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
  const tree = fileManager.locator(".directory-tree");
  const content = fileManager.locator(".file-content");
  const workspace = fileManager.locator(".file-workspace");

  const treeBox = await box(tree);
  const contentBox = await box(content);
  const workspaceBox = await box(workspace);
  expect(treeBox.y + treeBox.height).toBeLessThanOrEqual(contentBox.y + 2);
  expect(contentBox.width).toBeGreaterThanOrEqual(workspaceBox.width - 2);
});

test("simple File Manager input dialog stays content-sized on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
  await fileManager.getByTitle("New folder").click();
  const input = page.getByLabel("Folder name");
  await expect(input).toBeVisible();
  const dialog = input.locator("xpath=ancestor::*[@role='dialog'][1]");
  const dialogBox = await box(dialog);

  expect(dialogBox.height).toBeLessThan(420);
  expect(dialogBox.width).toBeLessThanOrEqual(382);
  expect(dialogBox.y).toBeGreaterThanOrEqual(0);
  expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(844);
});
