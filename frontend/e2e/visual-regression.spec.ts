import { expect, test, type Locator, type Page } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

type Box = { x: number; y: number; width: number; height: number };

async function box(locator: Locator): Promise<Box> {
  await expect(locator).toBeVisible();
  const value = await locator.boundingBox();
  expect(value).not.toBeNull();
  return value!;
}

async function expectInsideViewport(page: Page, locator: Locator, tolerance = 3) {
  const value = await box(locator);
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expect(value.x).toBeGreaterThanOrEqual(-tolerance);
  expect(value.y).toBeGreaterThanOrEqual(-tolerance);
  expect(value.x + value.width).toBeLessThanOrEqual(viewport!.width + tolerance);
  expect(value.y + value.height).toBeLessThanOrEqual(viewport!.height + tolerance);
}

async function expectNoHorizontalOverflow(locator: Locator, tolerance = 2) {
  await expect(locator).toBeVisible();
  await expect.poll(() => locator.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(tolerance);
}

async function expectDocumentContained(page: Page, tolerance = 1) {
  await expect.poll(() => page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth)).toBeLessThanOrEqual(tolerance);
}

async function expectWindowHealthy(page: Page, windowLocator: Locator) {
  await expectInsideViewport(page, windowLocator);
  const titlebar = windowLocator.locator(".window-titlebar");
  const title = titlebar.locator("strong");
  const controls = titlebar.locator(".window-controls");
  const content = windowLocator.locator(".window-content");
  await expect(titlebar).toBeVisible();
  await expect(title).toBeVisible();
  await expect(controls).toBeVisible();
  await expect(content).toBeVisible();

  const titleBox = await box(title);
  const controlsBox = await box(controls);
  expect(titleBox.x + titleBox.width).toBeLessThanOrEqual(controlsBox.x + 2);

  const buttons = controls.getByRole("button");
  await expect(buttons).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    const buttonBox = await box(buttons.nth(index));
    expect(buttonBox.width).toBeGreaterThanOrEqual(20);
    expect(buttonBox.height).toBeGreaterThanOrEqual(20);
  }

  const contentBox = await box(content);
  expect(contentBox.width).toBeGreaterThan(40);
  expect(contentBox.height).toBeGreaterThan(40);
}

async function capture(page: Page, name: string) {
  await test.info().attach(name, { body: await page.screenshot({ animations: "disabled" }), contentType: "image/png" });
}

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1280, height: 720 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "phone", width: 390, height: 844 },
]) {
  test(`shell and File Manager stay contained at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await installMockApi(page);
    await page.goto("/");

    const desktop = page.locator(".desktop");
    const taskbar = page.locator(".taskbar");
    await expectInsideViewport(page, desktop);
    await expectInsideViewport(page, taskbar);
    await expectDocumentContained(page);

    await page.getByRole("button", { name: "Main menu" }).click();
    const launcher = page.locator(".app-launcher");
    await expectInsideViewport(page, launcher);
    await expectNoHorizontalOverflow(launcher);
    await page.getByRole("button", { name: "Main menu" }).click();
    await expect(launcher).toBeHidden();

    await openDesktopApp(page, "File Manager");
    const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
    await expectWindowHealthy(page, fileManager);
    await expectDocumentContained(page);
    if (viewport.width <= 920) await expect(fileManager).toHaveClass(/mobile-fullscreen/);
    else await expect(fileManager).not.toHaveClass(/mobile-fullscreen/);
    await capture(page, `${viewport.name}-file-manager`);
  });
}

test("Settings survives progressive viewport narrowing", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Settings");
  const settings = page.locator('.desktop-window.active[aria-label="Settings"]');

  for (const viewport of [
    { width: 1600, height: 900 },
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await expectWindowHealthy(page, settings);
    await expectDocumentContained(page);
  }
  await expect(settings).toHaveClass(/mobile-fullscreen/);
});

test("File Manager dialogs stay inside viewport on desktop and phone", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');

  await fileManager.getByTitle("New folder").click();
  const createDialog = page.getByLabel("Folder name").locator("xpath=ancestor::*[@role='dialog'][1]");
  await expectInsideViewport(page, createDialog);
  await expectNoHorizontalOverflow(createDialog);
  await createDialog.locator(".modal-footer").getByRole("button", { name: "Cancel", exact: true }).click();

  await fileManager.getByLabel("Select Documents").click();
  await fileManager.getByTitle("Rename").click();
  const renameDialog = page.getByLabel("Rename", { exact: true });
  await expectInsideViewport(page, renameDialog);
  await expectNoHorizontalOverflow(renameDialog);
  await renameDialog.locator(".modal-footer").getByRole("button", { name: "Cancel", exact: true }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(fileManager).toHaveClass(/mobile-fullscreen/);
  await fileManager.getByTitle("New folder").click();
  const mobileDialog = page.getByLabel("Folder name").locator("xpath=ancestor::*[@role='dialog'][1]");
  await expectInsideViewport(page, mobileDialog);
  await expectNoHorizontalOverflow(mobileDialog);
  await expectDocumentContained(page);
  await capture(page, "mobile-new-folder-dialog");
});

test("three open windows keep title and controls separated", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  await openDesktopApp(page, "Settings");
  await openDesktopApp(page, "Module Center");

  const windows = page.locator(".desktop-window");
  await expect(windows).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) await expectWindowHealthy(page, windows.nth(index));
  await expectDocumentContained(page);
  await capture(page, "three-window-stack");
});
