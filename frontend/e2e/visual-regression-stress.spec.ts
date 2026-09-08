import { expect, test, type Locator, type Page } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

type Viewport = { name: string; width: number; height: number };
type Rect = { x: number; y: number; width: number; height: number };

const STRESS_VIEWPORTS: Viewport[] = [
  { name: "qhd", width: 2560, height: 1440 },
  { name: "ultrawide", width: 3440, height: 1440 },
  { name: "legacy-desktop", width: 800, height: 600 },
  { name: "small-tablet", width: 600, height: 800 },
  { name: "large-phone", width: 430, height: 932 },
  { name: "android-phone", width: 412, height: 915 },
  { name: "compact-phone", width: 360, height: 800 },
  { name: "very-small-phone", width: 320, height: 568 },
  { name: "phone-landscape", width: 844, height: 390 },
  { name: "large-phone-landscape", width: 915, height: 412 },
];

const BUILTIN_APPS = ["File Manager", "Settings", "Module Center", "DCST"] as const;
const NATIVE_MODULES = ["Firewall Manager", "Security Center", "Network Tools"] as const;

async function box(locator: Locator): Promise<Rect> {
  await expect(locator).toBeVisible();
  const value = await locator.boundingBox();
  expect(value, "visible element must have geometry").not.toBeNull();
  return value!;
}

async function expectInViewport(page: Page, locator: Locator, tolerance = 3) {
  const value = await box(locator);
  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expect(value.x).toBeGreaterThanOrEqual(-tolerance);
  expect(value.y).toBeGreaterThanOrEqual(-tolerance);
  expect(value.x + value.width).toBeLessThanOrEqual(viewport!.width + tolerance);
  expect(value.y + value.height).toBeLessThanOrEqual(viewport!.height + tolerance);
}

async function expectInContainer(container: Locator, child: Locator, tolerance = 3) {
  const parentBox = await box(container);
  const childBox = await box(child);
  expect(childBox.x).toBeGreaterThanOrEqual(parentBox.x - tolerance);
  expect(childBox.y).toBeGreaterThanOrEqual(parentBox.y - tolerance);
  expect(childBox.x + childBox.width).toBeLessThanOrEqual(parentBox.x + parentBox.width + tolerance);
  expect(childBox.y + childBox.height).toBeLessThanOrEqual(parentBox.y + parentBox.height + tolerance);
}

async function expectNoPageOverflow(page: Page, tolerance = 2) {
  await expect.poll(async () => page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    return Math.max(root.scrollWidth, body.scrollWidth) - window.innerWidth;
  })).toBeLessThanOrEqual(tolerance);
}

async function expectNoHorizontalOverflow(locator: Locator, tolerance = 2) {
  await expect(locator).toBeVisible();
  await expect.poll(async () => locator.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(tolerance);
}

async function expectNoVerticalOverflow(locator: Locator, tolerance = 2) {
  await expect(locator).toBeVisible();
  await expect.poll(async () => locator.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(tolerance);
}

async function expectNonOverlapping(a: Locator, b: Locator, tolerance = 1) {
  const first = await box(a);
  const second = await box(b);
  const separated =
    first.x + first.width <= second.x + tolerance ||
    second.x + second.width <= first.x + tolerance ||
    first.y + first.height <= second.y + tolerance ||
    second.y + second.height <= first.y + tolerance;
  expect(separated, "elements overlap unexpectedly").toBeTruthy();
}

async function expectWindowHealthy(page: Page, windowLocator: Locator) {
  await expectInViewport(page, windowLocator, 4);
  const titlebar = windowLocator.locator(".window-titlebar");
  const title = titlebar.locator("strong");
  const controls = titlebar.locator(".window-controls");
  const content = windowLocator.locator(".window-content");

  await expectInContainer(windowLocator, titlebar, 2);
  await expectInContainer(windowLocator, controls, 2);
  await expectNonOverlapping(title, controls, 2);
  await expect(content).toBeVisible();

  const controlsButtons = controls.getByRole("button");
  await expect(controlsButtons).toHaveCount(3);
  for (let i = 0; i < 3; i += 1) {
    const control = await box(controlsButtons.nth(i));
    expect(control.width).toBeGreaterThanOrEqual(20);
    expect(control.height).toBeGreaterThanOrEqual(20);
  }

  const contentBox = await box(content);
  expect(contentBox.width).toBeGreaterThan(20);
  expect(contentBox.height).toBeGreaterThan(20);

  const taskbar = page.locator(".taskbar");
  if (await taskbar.isVisible()) {
    const windowBox = await box(windowLocator);
    const taskbarBox = await box(taskbar);
    expect(windowBox.y + windowBox.height).toBeLessThanOrEqual(taskbarBox.y + 4);
  }
}

async function expectShellHealthy(page: Page) {
  const desktop = page.locator(".desktop");
  const surface = page.locator(".desktop-surface");
  const taskbar = page.locator(".taskbar");
  const menu = page.getByRole("button", { name: "Main menu" });

  await expect(desktop).toBeVisible();
  await expect(surface).toBeVisible();
  await expect(taskbar).toBeVisible();
  await expect(menu).toBeVisible();
  await expectInViewport(page, desktop, 3);
  await expectInViewport(page, taskbar, 3);
  await expectInContainer(desktop, surface, 3);
  await expectInContainer(taskbar, menu, 3);
  await expectNoPageOverflow(page);
}

async function screenshot(page: Page, name: string) {
  await test.info().attach(name, {
    body: await page.screenshot({ animations: "disabled" }),
    contentType: "image/png",
  });
}

async function closeWindow(windowLocator: Locator) {
  await windowLocator.locator(".window-close").click();
  await expect(windowLocator).toHaveCount(0);
}

async function installNativeCatalog(page: Page) {
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

for (const viewport of STRESS_VIEWPORTS) {
  test(`stress shell geometry at ${viewport.name} ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await installMockApi(page);
    await page.goto("/");

    await expectShellHealthy(page);

    await page.getByRole("button", { name: "Main menu" }).click();
    const launcher = page.locator(".app-launcher");
    await expect(launcher).toBeVisible();
    await expectInViewport(page, launcher, 4);
    await expectNoHorizontalOverflow(launcher, 3);
    await screenshot(page, `stress-${viewport.name}-launcher`);

    await page.getByRole("button", { name: "Main menu" }).click();
    await expect(launcher).toBeHidden();

    await openDesktopApp(page, "File Manager");
    const windowLocator = page.locator('.desktop-window.active[aria-label="File Manager"]');
    await expectWindowHealthy(page, windowLocator);
    await expectNoPageOverflow(page);

    if (viewport.width <= 920) {
      await expect(windowLocator).toHaveClass(/mobile-fullscreen/);
    }

    await screenshot(page, `stress-${viewport.name}-file-manager`);
  });
}

test("desktop shortcuts and taskbar controls stay inside the shell at common edge sizes", async ({ page }) => {
  await installMockApi(page);

  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1024, height: 768 },
    { width: 800, height: 600 },
    { width: 390, height: 844 },
    { width: 320, height: 568 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expectShellHealthy(page);

    const taskbar = page.locator(".taskbar");
    const taskbarButtons = taskbar.getByRole("button").filter({ visible: true });
    const count = await taskbarButtons.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      await expectInContainer(taskbar, taskbarButtons.nth(i), 4);
      const buttonBox = await box(taskbarButtons.nth(i));
      expect(buttonBox.width).toBeGreaterThanOrEqual(20);
      expect(buttonBox.height).toBeGreaterThanOrEqual(20);
    }

    const shortcuts = page.locator(".desktop-shortcuts");
    if (await shortcuts.isVisible()) {
      await expectInViewport(page, shortcuts, 4);
      const items = shortcuts.locator("button:visible");
      const itemCount = await items.count();
      for (let i = 0; i < itemCount; i += 1) {
        await expectInViewport(page, items.nth(i), 4);
      }
    }

    await expectNoPageOverflow(page);
    await screenshot(page, `shell-controls-${viewport.width}x${viewport.height}`);
  }
});

test("all principal applications survive repeated viewport orientation changes", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installMockApi(page);
  await page.goto("/");

  for (const appName of BUILTIN_APPS) {
    await openDesktopApp(page, appName);
    const windowLocator = page.locator(`.desktop-window.active[aria-label="${appName}"]`);

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1024, height: 768 },
      { width: 768, height: 1024 },
      { width: 844, height: 390 },
      { width: 390, height: 844 },
      { width: 1280, height: 720 },
    ]) {
      await page.setViewportSize(viewport);
      await expectShellHealthy(page);
      await expectWindowHealthy(page, windowLocator);
      await expectNoPageOverflow(page);
      await screenshot(page, `rotate-${appName.replaceAll(" ", "-").toLowerCase()}-${viewport.width}x${viewport.height}`);
    }

    await closeWindow(windowLocator);
    await page.setViewportSize({ width: 1440, height: 900 });
  }
});

test("native modules survive portrait, landscape and legacy desktop sizes", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await installMockApi(page);
  await installNativeCatalog(page);
  await page.goto("/");

  for (const moduleName of NATIVE_MODULES) {
    await openDesktopApp(page, moduleName);
    const windowLocator = page.locator(`.desktop-window.active[aria-label="${moduleName}"]`);

    for (const viewport of [
      { width: 1280, height: 720 },
      { width: 800, height: 600 },
      { width: 915, height: 412 },
      { width: 412, height: 915 },
    ]) {
      await page.setViewportSize(viewport);
      await expectWindowHealthy(page, windowLocator);
      await expectNoPageOverflow(page);
      await screenshot(page, `native-stress-${moduleName.replaceAll(" ", "-").toLowerCase()}-${viewport.width}x${viewport.height}`);
    }

    await closeWindow(windowLocator);
    await page.setViewportSize({ width: 1280, height: 720 });
  }
});

test("window maximize and restore never push chrome outside the workspace", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const windowLocator = page.locator('.desktop-window.active[aria-label="File Manager"]');
  await expectWindowHealthy(page, windowLocator);
  const controls = windowLocator.locator(".window-controls button");

  for (let cycle = 0; cycle < 4; cycle += 1) {
    await controls.nth(1).click();
    await expect(windowLocator).toHaveClass(/maximized/);
    await expectWindowHealthy(page, windowLocator);
    await expectNoPageOverflow(page);
    await screenshot(page, `maximize-cycle-${cycle + 1}`);

    await controls.nth(1).click();
    await expect(windowLocator).not.toHaveClass(/maximized/);
    await expectWindowHealthy(page, windowLocator);
  }
});

test("active window focus remains unique while cycling through a dense window stack", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await installMockApi(page);
  await page.goto("/");

  for (const appName of BUILTIN_APPS) {
    await openDesktopApp(page, appName);
  }

  const windows = page.locator(".desktop-window");
  await expect(windows).toHaveCount(BUILTIN_APPS.length);

  for (let i = 0; i < BUILTIN_APPS.length; i += 1) {
    const current = windows.nth(i);
    await current.locator(".window-titlebar").click({ position: { x: 40, y: 20 } });
    await expect(page.locator(".desktop-window.active")).toHaveCount(1);
    await expect(current).toHaveClass(/active/);
    await expectWindowHealthy(page, current);
  }

  await expectNoPageOverflow(page);
  await screenshot(page, "dense-four-window-focus-stack");
});

test("opening and closing applications repeatedly leaves no ghost windows or shell overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await installMockApi(page);
  await page.goto("/");

  for (let cycle = 0; cycle < 5; cycle += 1) {
    for (const appName of BUILTIN_APPS) {
      await openDesktopApp(page, appName);
      const windowLocator = page.locator(`.desktop-window.active[aria-label="${appName}"]`);
      await expectWindowHealthy(page, windowLocator);
      await closeWindow(windowLocator);
      await expect(page.locator(".desktop-window")).toHaveCount(0);
      await expectNoPageOverflow(page);
    }
  }

  await screenshot(page, "after-twenty-open-close-cycles");
});

test("File Manager tolerates pathological long file and directory names without page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await installMockApi(page);

  const longDirectory = "directory-" + "very-long-segment-".repeat(14);
  const longFile = "report-" + "extremely-long-filename-".repeat(16) + ".txt";

  await page.route("**/api/files/list**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        path: "/home/e2e",
        current_path: "/home/e2e",
        parent_path: "/home",
        items: [
          { name: longDirectory, path: `/home/e2e/${longDirectory}`, type: "directory", is_dir: true, size: 0, owner: "e2e", group: "users", mode: "0755", permissions: "drwxr-xr-x", modified: 1, mtime: 1, mime: "inode/directory", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false },
          { name: longFile, path: `/home/e2e/${longFile}`, type: "text", is_dir: false, size: 1234, owner: "administrator-with-a-very-long-name", group: "enterprise-users-with-a-very-long-group-name", mode: "0644", permissions: "-rw-r--r--", modified: 2, mtime: 2, mime: "text/plain", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false },
        ],
        page: 1,
        page_size: 50,
        total_items: 2,
        total_pages: 1,
        sort: "name",
        direction: "asc",
        can_write: true,
        can_upload: true,
        can_delete: true,
      }),
    });
  });

  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
  await expectWindowHealthy(page, fileManager);
  await expect(fileManager.getByText(longDirectory, { exact: true })).toBeVisible();
  await expect(fileManager.getByText(longFile, { exact: true })).toBeVisible();
  await expectNoPageOverflow(page);
  await screenshot(page, "long-file-names-desktop");

  await page.setViewportSize({ width: 390, height: 844 });
  await expectWindowHealthy(page, fileManager);
  await expectNoPageOverflow(page);
  await screenshot(page, "long-file-names-mobile");
});

test("File Manager dialogs fit extremely small portrait and short landscape viewports", async ({ page }) => {
  await installMockApi(page);
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
  await expectWindowHealthy(page, fileManager);

  for (const viewport of [
    { width: 320, height: 568 },
    { width: 360, height: 640 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport);
    await expectWindowHealthy(page, fileManager);
    await fileManager.getByTitle("New folder").click();
    const input = page.getByLabel("Folder name");
    await expect(input).toBeVisible();
    const dialog = input.locator("xpath=ancestor::*[@role='dialog'][1]");
    await expectInViewport(page, dialog, 4);
    await expectNoHorizontalOverflow(dialog, 3);
    await expectNoPageOverflow(page);
    await screenshot(page, `new-folder-${viewport.width}x${viewport.height}`);
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  }
});

test("launcher search stays usable with long search text at small widths", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Main menu" }).click();
  const launcher = page.locator(".app-launcher");
  const search = launcher.locator(".launcher-search input");
  await expect(search).toBeVisible();
  await search.fill("File Manager Settings Module Center DCST Firewall Security Network very long search input");
  await expectInViewport(page, launcher, 4);
  await expectInContainer(launcher, search, 4);
  await expectNoHorizontalOverflow(launcher, 3);
  await expectNoPageOverflow(page);
  await screenshot(page, "launcher-long-search-small-phone");
});

test("browser CSS zoom stress does not create document-level horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Settings");
  const settings = page.locator('.desktop-window.active[aria-label="Settings"]');

  for (const zoom of [0.8, 1, 1.1, 1.25, 1.4]) {
    await page.evaluate((value) => {
      document.documentElement.style.zoom = String(value);
    }, zoom);
    await expect(settings).toBeVisible();
    await expectNoPageOverflow(page, 4);
    await screenshot(page, `css-zoom-${String(zoom).replace(".", "-")}`);
  }

  await page.evaluate(() => {
    document.documentElement.style.zoom = "1";
  });
});

test("rapid viewport oscillation does not leave stale window geometry", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  await openDesktopApp(page, "Settings");

  const windows = page.locator(".desktop-window");
  await expect(windows).toHaveCount(2);

  const sequence = [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
    { width: 1366, height: 768 },
    { width: 844, height: 390 },
    { width: 1024, height: 768 },
    { width: 320, height: 568 },
    { width: 1920, height: 1080 },
    { width: 412, height: 915 },
    { width: 1280, height: 720 },
  ];

  for (let round = 0; round < 2; round += 1) {
    for (const viewport of sequence) {
      await page.setViewportSize(viewport);
      await expectShellHealthy(page);
      for (let i = 0; i < 2; i += 1) {
        await expectWindowHealthy(page, windows.nth(i));
      }
      await expectNoPageOverflow(page);
    }
  }

  await screenshot(page, "rapid-viewport-oscillation-final");
});

test("window content remains scrollable where content is taller than the available mobile workspace", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 568 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Settings");

  const settings = page.locator('.desktop-window.active[aria-label="Settings"]');
  await expectWindowHealthy(page, settings);
  const content = settings.locator(".window-content");
  const metrics = await content.evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
    overflowY: getComputedStyle(element).overflowY,
  }));
  expect(metrics.scrollHeight).toBeGreaterThanOrEqual(metrics.clientHeight);
  if (metrics.scrollHeight > metrics.clientHeight + 2) {
    expect(["auto", "scroll"]).toContain(metrics.overflowY);
  }
  await expectNoPageOverflow(page);
  await screenshot(page, "settings-short-mobile-scroll");
});

test("taskbar does not cover mobile fullscreen window content", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");

  const fileManager = page.locator('.desktop-window.active[aria-label="File Manager"]');
  const taskbar = page.locator(".taskbar");
  await expect(fileManager).toHaveClass(/mobile-fullscreen/);
  const windowBox = await box(fileManager);
  const taskbarBox = await box(taskbar);
  expect(windowBox.y + windowBox.height).toBeLessThanOrEqual(taskbarBox.y + 4);
  await expectNoPageOverflow(page);
  await screenshot(page, "mobile-fullscreen-taskbar-boundary");
});

test("three application windows remain valid after maximize, focus and viewport shrink sequence", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await installMockApi(page);
  await page.goto("/");

  await openDesktopApp(page, "File Manager");
  await openDesktopApp(page, "Settings");
  await openDesktopApp(page, "Module Center");

  const windows = page.locator(".desktop-window");
  await expect(windows).toHaveCount(3);
  const active = page.locator(".desktop-window.active");
  await active.locator(".window-controls button").nth(1).click();
  await expect(active).toHaveClass(/maximized/);

  await windows.nth(0).locator(".window-titlebar").click({ position: { x: 40, y: 20 } });
  await expect(windows.nth(0)).toHaveClass(/active/);

  await page.setViewportSize({ width: 1024, height: 768 });
  for (let i = 0; i < 3; i += 1) await expectWindowHealthy(page, windows.nth(i));

  await page.setViewportSize({ width: 390, height: 844 });
  for (let i = 0; i < 3; i += 1) {
    await expectWindowHealthy(page, windows.nth(i));
    await expect(windows.nth(i)).toHaveClass(/mobile-fullscreen/);
  }

  await expectNoPageOverflow(page);
  await screenshot(page, "three-window-maximize-focus-mobile-transition");
});
