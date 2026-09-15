import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

for (const width of [1440, 390]) {
  test(`editor tools preserve the draft and work with keyboard at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installMockApi(page);
    const content = "first line\r\nsecond line\r\nthird line";
    await page.route("**/api/files/text?**", (route) => route.fulfill({ json: { path: "/home/e2e/readme.txt", content, encoding: "utf-8", size: content.length, mtime_ns: "100" } }));
    await page.goto("/");
    await openDesktopApp(page, "File Manager");
    await page.locator(".file-row").getByText("readme.txt", { exact: true }).dblclick();
    const dialog = page.getByRole("dialog", { name: "Text editor — readme.txt", exact: true });
    const editor = dialog.getByRole("textbox", { name: "File content", exact: true });
    await expect(editor).toBeVisible();
    await expect(dialog.getByLabel("Line endings")).toHaveValue("CRLF");
    await dialog.getByRole("button", { name: "Find and replace", exact: true }).click();
    await dialog.getByRole("textbox", { name: "Find", exact: true }).fill("second");
    await dialog.getByRole("textbox", { name: "Replace", exact: true }).fill("updated");
    await dialog.getByRole("button", { name: "replace all", exact: true }).click();
    await expect(editor).toContainText("updated line");
    await dialog.getByRole("textbox", { name: "Find", exact: true }).press("Escape");
    await expect(dialog.getByRole("textbox", { name: "Find", exact: true })).toHaveCount(0);
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Go to line", exact: true }).click();
    const lineInput = dialog.getByRole("textbox", { name: "Go to line:", exact: true });
    await lineInput.fill("3");
    await lineInput.press("Enter");
    await expect(dialog.getByText("Ln 3, Col 1", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Wrap lines", exact: true }).click();
    await expect(editor).toHaveClass(/cm-lineWrapping/);
    await expect(dialog.getByRole("button", { name: "Wrap lines", exact: true })).toHaveAttribute("aria-pressed", "true");
    await editor.focus();
    await page.keyboard.press("Escape");
    await page.keyboard.press("Tab");
    await expect(dialog.getByLabel("Line endings")).toBeFocused();
    await expect(dialog).toBeVisible();
    await editor.focus();
    await page.keyboard.press("Control+End");
    await page.keyboard.press("Enter");
    await page.keyboard.insertText("fourth line");
    const downloadEvent = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Download copy", exact: true }).click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toBe("readme.txt");
    expect(await readFile((await download.path())!, "utf8")).toBe("first line\r\nupdated line\r\nthird line\r\nfourth line");
    await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await dialog.locator(".text-editor").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`text-editor-${width}.png`), fullPage: true });
  });
}

test("typing while a save is in flight remains visible and unsaved", async ({ page }) => {
  await installMockApi(page);
  const writes: { content: string; expected_mtime_ns: string }[] = [];
  let completeFirstSave!: () => void;
  const firstSave = new Promise<void>((resolve) => { completeFirstSave = resolve; });
  await page.route("**/api/files/text?**", (route) => route.fulfill({ json: { path: "/home/e2e/readme.txt", content: "hello", encoding: "utf-8", size: 5, mtime_ns: "100" } }));
  await page.route("**/api/files/text", async (route) => {
    writes.push(route.request().postDataJSON());
    if (writes.length === 1) await firstSave;
    await route.fulfill({ json: { ok: true, path: "/home/e2e/readme.txt", encoding: "utf-8", size: writes.at(-1)!.content.length, mtime_ns: String(100 + writes.length) } });
  });
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  await page.locator(".file-row").getByText("readme.txt", { exact: true }).dblclick();
  const dialog = page.getByRole("dialog", { name: "Text editor — readme.txt", exact: true });
  const editor = dialog.getByRole("textbox", { name: "File content", exact: true });
  await editor.fill("first draft");
  await editor.press("Control+s");
  await expect.poll(() => writes.length).toBe(1);
  await editor.fill("newer draft");
  await expect(dialog.getByRole("button", { name: "Reload file", exact: true })).toBeDisabled();
  completeFirstSave();
  await expect(dialog.locator(".text-editor-status")).toHaveText("Unsaved changes");
  await expect(editor).toHaveText("newer draft");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog.locator(".text-editor-status")).toHaveText("File saved");
  expect(writes.map(({ content, expected_mtime_ns }) => ({ content, expected_mtime_ns }))).toEqual([
    { content: "first draft", expected_mtime_ns: "100" }, { content: "newer draft", expected_mtime_ns: "101" },
  ]);
});
