import { expect, test, type Locator, type Page } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

type ViewportCase = {
  name: string;
  width: number;
  height: number;
};

type Box = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const VIEWPORTS: ViewportCase[] = [
  { name: "full-hd", width: 1920, height: 1080 },
  { name: "desktop", width: 1440, height: 900 },
  { name: "common-laptop", width: 1366, height: 768 },
  { name: "small-laptop", width: 1280, height: 720 },
  { name: "tablet-landscape", width: 1024, height: 768 },
  { name: "tablet-portrait", width: 768, height: 1024 },
  { name: "phone", width: 390, height: 844 },
];

async function requiredBox(locator: Locator): Promise<Box> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, "visible element should have a bounding box").not.toBeNull();
  return box!;
}

function expectFiniteBox(box: Box) {
  expect(Number.isFinite(box.x)).toBeTruthy();
  expect(Number.isFinite(box.y)).toBeTruthy();
  expect(Number.isFinite(box.width)).toBeTruthy();
  expect(Number.isFinite(box.height)).toBeTruthy();
  expect(box.width).toBeGreaterThan(0);
  expect(box.height).toBeGreaterThan(0);
}

async function expectInsideViewport(page: Page, locator: Locator, tolerance = 2) {
  const box = await requiredBox(locator);
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expectFiniteBox(box);
  expect(box.x, "element starts outside the left viewport edge").toBeGreaterThanOrEqual(-tolerance);
  expect(box.y, "element starts outside the top viewport edge").toBeGreaterThanOrEqual(-tolerance);
  expect(box.x + box.width, "element extends past the right viewport edge").toBeLessThanOrEqual(viewport!.width + tolerance);
  expect(box.y + box.height, "element extends past the bottom viewport edge").toBeLessThanOrEqual(viewport!.height + tolerance);
}

async function expectInsideContainer(container: Locator, child: Locator, tolerance = 2) {
  const outer = await requiredBox(container);
  const inner = await requiredBox(child);
  expect(inner.x).toBeGreaterThanOrEqual(outer.x - tolerance);
  expect(inner.y).toBeGreaterThanOrEqual(outer.y - tolerance);
  expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + tolerance);
  expect(inner.y + inner.height).toBeLessThanOrEqual(outer.y + outer.height + tolerance);
}

async function expectNoHorizontalOverflow(locator: Locator, tolerance = 1) {
  await expect(locator).toBeVisible();
  await expect.poll(async () => locator.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(tolerance);
}

async function expectDocumentNotWiderThanViewport(page: Page, tolerance = 1) {
  await expect.poll(async () => page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    return Math.max(root.scrollWidth, body.scrollWidth) - window.innerWidth;
  })).toBeLessThanOrEqual(tolerance);
}

async function expectNoOverlap(left: Locator, right: Locator, tolerance = 2) {
  const leftBox = await requiredBox(left);
  const rightBox = await requiredBox(right);
  expect(
    leftBox.x + leftBox.width <= rightBox.x + tolerance ||
      rightBox.x + rightBox.width <= leftBox.x + tolerance ||
      leftBox.y + leftBox.height <= rightBox.y + tolerance ||
      rightBox.y + rightBox.height <= leftBox.y + tolerance,
    "elements overlap",
  ).toBeTruthy();
}

async function expectWindowChromeHealthy(page: Page, windowLocator: Locator) {
  await expectInsideViewport(page, windowLocator, 3);

  const titlebar = windowLocator.locator(".window-titlebar");
  const title = titlebar.locator("strong");
  const controls = titlebar.locator(".window-controls");
  const content = windowLocator.locator(".window-content");

  await expect(titlebar).toBeVisible();
  await expect(title).toBeVisible();
  await expect(controls).toBeVisible();
  await expect(content).toBeVisible();

  await expectInsideContainer(windowLocator, titlebar, 2);
  await expectInsideContainer(windowLocator, controls, 2);
  await expectNoOverlap(title, controls, 2);

  const buttons = controls.getByRole("button");
  await expect(buttons).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    const buttonBox = await requiredBox(buttons.nth(index));
    expect(buttonBox.width, `window control ${index} is too narrow`).toBeGreaterThanOrEqual(20);
    expect(buttonBox.height, `window control ${index} is too short`).toBeGreaterThanOrEqual(20);
  }

  const contentBox = await requiredBox(content);
  expect(contentBox.width).toBeGreaterThan(40);
  expect(contentBox.height).toBeGreaterThan(40);

  const taskbar = page.locator(".taskbar");
  if (await taskbar.isVisible()) {
    const windowBox = await requiredBox(windowLocator);
    const taskbarBox = await requiredBox(taskbar);
    expect(windowBox.y + windowBox.height, "window is hidden below the taskbar").toBeLessThanOrEqual(taskbarBox.y + 3);
  }
}

async function expectShellHealthy(page: Page) {
  const desktop = page.locator(".desktop");
  const surface = page.locator(".desktop-surface");
  const taskbar = page.locator(".taskbar");
  const mainMenu = page.getByRole("button", { name: "Main menu" });

  await expect(desktop).toBeVisible();
  await expect(surface).toBeVisible();
  await expect(taskbar).toBeVisible();
  await expect(mainMenu).toBeVisible();

  await expectInsideViewport(page, desktop, 2);
  await expectInsideViewport(page, taskbar, 2);
  await expectInsideContainer(desktop, surface, 2);
  await expectInsideContainer(taskbar, mainMenu, 2);
  await expectDocumentNotWiderThanViewport(page);
}

async function capture(page: Page, name: string) {
  await test.info().attach(name, {
    body: await page.screenshot({ animations: "disabled" }),
    contentType: "image/png",
  });
}

async function closeActiveWindow(page: Page) {
  const activeWindow = page.locator(".desktop-window.active");
  await expect(activeWindow).toBeVisible();
  await activeWindow.locator(".window-close").click();
  await expect(activeWindow).toHaveCount(0);
}

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

for (const viewport of VIEWPORTS) {
  test(`visual shell and File Manager remain contained at ${viewport.name} ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await installMockApi(page);
    await page.goto("/");

    await expectShellHealthy(page);

    await page.getByRole("button", { name: "Main menu" }).click();
    const launcher = page.locator(".app-launcher");
    await expect(launcher).toBeVisible();
    await expectInsideViewport(page, launcher, 3);
    await expectNoHorizontalOverflow(launcher, 2);
    await capture(page, `${viewport.name}-launcher`);
    await page.getByRole("button", { name: "Main menu" }).click();
    await expect(launcher).toBeHidden();

    await openDesktopApp(page, "File Manager");
    const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
    await expectWindowChromeHealthy(page, fileManager);
    await expectDocumentNotWiderThanViewport(page);

    if (viewport.width <= 920) {
      await expect(fileManager).toHaveClass(/mobile-fullscreen/);
    } else {
      await expect(fileManager).not.toHaveClass(/mobile-fullscreen/);
    }

    await capture(page, `${viewport.name}-file-manager`);
  });
}

test("open desktop windows reflow correctly when the browser becomes progressively narrower", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Settings");

  const settings = page.locator('.desktop-window.active[aria-label="Settings"]');
  await expectWindowChromeHealthy(page, settings);
  await capture(page, "resize-1600x900");

  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await expectShellHealthy(page);
    await expectWindowChromeHealthy(page, settings);
    await expectDocumentNotWiderThanViewport(page);
    await capture(page, `resize-${viewport.width}x${viewport.height}`);
  }

  await expect(settings).toHaveClass(/mobile-fullscreen/);
});

test("built-in desktop applications keep valid window geometry and chrome", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await installMockApi(page);
  await page.goto("/");

  for (const appName of ["File Manager", "Settings", "Module Center", "DCST"]) {
    await openDesktopApp(page, appName);
    const appWindow = page.locator(`.desktop-window.active[aria-label="${appName}"]`);
    await expectWindowChromeHealthy(page, appWindow);
    await expectDocumentNotWiderThanViewport(page);
    await capture(page, `app-${appName.toLowerCase().replaceAll(" ", "-")}`);
    await closeActiveWindow(page);
  }
});

test("native module windows stay inside a compact laptop viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await installMockApi(page);
  await installNativeModuleCatalog(page);
  await page.goto("/");

  for (const appName of ["Firewall Manager", "Security Center", "Network Tools"]) {
    await openDesktopApp(page, appName);
    const appWindow = page.locator(`.desktop-window.active[aria-label="${appName}"]`);
    await expectWindowChromeHealthy(page, appWindow);
    await expectDocumentNotWiderThanViewport(page);
    await capture(page, `native-${appName.toLowerCase().replaceAll(" ", "-")}`);
    await closeActiveWindow(page);
  }
});

test("File Manager create and rename dialogs remain fully visible on desktop and phone layouts", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
  await expectWindowChromeHealthy(page, fileManager);

  await fileManager.getByTitle("New folder").click();
  const folderName = page.getByLabel("Folder name");
  await expect(folderName).toBeVisible();
  const createDialog = folderName.locator("xpath=ancestor::*[@role='dialog'][1]");
  await expectInsideViewport(page, createDialog, 3);
  await expectNoHorizontalOverflow(createDialog, 2);
  await capture(page, "modal-new-folder-desktop");
  await createDialog.getByRole("button", { name: "Cancel", exact: true }).filter({ hasText: "Cancel" }).click();

  await fileManager.getByLabel("Select Documents").click();
  await fileManager.getByTitle("Rename").click();
  const renameDialog = page.getByLabel("Rename", { exact: true });
  await expect(renameDialog).toBeVisible();
  await expectInsideViewport(page, renameDialog, 3);
  await expectNoHorizontalOverflow(renameDialog, 2);
  await capture(page, "modal-rename-desktop");
  await renameDialog.getByRole("button", { name: "Cancel", exact: true }).filter({ hasText: "Cancel" }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await expectWindowChromeHealthy(page, fileManager);
  await expect(fileManager).toHaveClass(/mobile-fullscreen/);

  await fileManager.getByTitle("New folder").click();
  const mobileFolderName = page.getByLabel("Folder name");
  await expect(mobileFolderName).toBeVisible();
  const mobileDialog = mobileFolderName.locator("xpath=ancestor::*[@role='dialog'][1]");
  await expectInsideViewport(page, mobileDialog, 3);
  await expectNoHorizontalOverflow(mobileDialog, 2);
  await expectDocumentNotWiderThanViewport(page);
  await capture(page, "modal-new-folder-phone");
});

test("window title and controls do not collide after opening several applications", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await installMockApi(page);
  await page.goto("/");

  await openDesktopApp(page, "File Manager");
  await openDesktopApp(page, "Settings");
  await openDesktopApp(page, "Module Center");

  const windows = page.locator(".desktop-window");
  await expect(windows).toHaveCount(3);
  await expect(page.locator(".desktop-window.active")).toHaveCount(1);
  await expect(page.locator(".desktop-window.inactive")).toHaveCount(2);

  for (let index = 0; index < 3; index += 1) {
    const windowLocator = windows.nth(index);
    await expectWindowChromeHealthy(page, windowLocator);
  }

  await expectDocumentNotWiderThanViewport(page);
  await capture(page, "three-window-stack");
});
