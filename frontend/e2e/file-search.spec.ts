import { expect, test } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

test("mouse-selected list rows receive rename and delete keyboard shortcuts", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  const row = page.locator(".file-row").filter({ hasText: "readme.txt" });
  await row.click();
  await expect(row).toBeFocused();
  await page.keyboard.press("F2");
  const rename = page.getByRole("dialog", { name: "Rename", exact: true });
  await expect(rename.getByLabel("New name")).toHaveValue("readme.txt");
  await page.keyboard.press("Escape");
  await expect(rename).toHaveCount(0);
  await row.click();
  await page.keyboard.press("Delete");
  const deletion = page.getByRole("dialog", { name: "Confirm deletion" });
  await expect(deletion).toHaveCount(1);
  await expect(deletion.getByText("/home/e2e/readme.txt", { exact: true })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`recursive file search filters results and opens their folder at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installMockApi(page);
    const file = {
      name: "Report.TXT", path: "/home/e2e/Documents/Annual reports/Report.TXT", type: "txt", is_dir: false,
      size: 128, owner: "e2e", group: "users", mode: "0644", permissions: "-rw-r--r--", modified: 2, mtime: 2,
      mime: "text/plain", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false,
    };
    let searchParams: URLSearchParams | undefined;
    await page.route("**/api/files/search?**", async (route) => {
      searchParams = new URL(route.request().url()).searchParams;
      await route.fulfill({ json: { items: [file], scanned: 1000, skipped: 1, truncated: true, reason: "limit" } });
    });
    await page.goto("/");
    await openDesktopApp(page, "File Manager");
    await page.getByRole("button", { name: "Search subfolders", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Search subfolders", exact: true });
    await dialog.getByLabel("Name or pattern").fill("*.TXT");
    await dialog.getByLabel("Match mode").selectOption("glob");
    await dialog.getByLabel("Item type").selectOption("files");
    await dialog.getByLabel("Match case", { exact: true }).check();
    await dialog.getByRole("button", { name: "Search", exact: true }).click();
    await expect(dialog.getByText(file.path)).toBeVisible();
    expect(Object.fromEntries(searchParams!)).toEqual({ path: "/home/e2e", query: "*.TXT", match_mode: "glob", item_type: "files", case_sensitive: "true", show_hidden: "false" });
    await expect(dialog.getByText(/The result limit was reached/)).toBeVisible();
    await expect(dialog.getByText(/Skipped items: 1/)).toBeVisible();
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`file-search-${width}.png`), fullPage: true });
    const navigation = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return url.pathname === "/api/files/list" && url.searchParams.get("path") === "/home/e2e/Documents/Annual reports";
    });
    await dialog.getByRole("button", { name: "Open containing folder Report.TXT" }).click();
    await navigation;
    await expect(dialog).toHaveCount(0);
  });
}
