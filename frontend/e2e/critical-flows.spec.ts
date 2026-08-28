import { expect, test } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

test("authentication covers invalid login, login, logout and missing session", async ({ page }) => {
  const state = await installMockApi(page, false);
  await page.goto("/");
  await page.getByLabel("Linux user").fill("e2e");
  await page.getByLabel("Password", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid username or password");
  await page.getByLabel("Password", { exact: true }).fill("correct");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Main menu" })).toBeVisible();
  await page.getByRole("button", { name: "Main menu" }).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  state.authenticated = false;
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("desktop loads and manages multiple windows", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Main menu" })).toBeVisible();
  await openDesktopApp(page, "File Manager");
  await expect(page.getByRole("dialog", { name: "File Manager" })).toBeVisible();
  await openDesktopApp(page, "Settings");
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
  const windows = page.locator(".desktop-window");
  await expect(windows).toHaveCount(2);
  await expect(page.locator(".desktop-window.active")).toHaveCount(1);
  await expect(page.locator(".desktop-window.inactive")).toHaveCount(1);
});

test("file manager enters a directory, creates, renames, uploads, downloads and deletes", async ({ page }) => {
  const state = await installMockApi(page);
  await page.context().route("**/api/files/download?**", async (route) => {
    state.calls.push("GET /api/files/download");
    await route.fulfill({ status: 200, body: "test", headers: { "content-type": "text/plain", "content-disposition": "attachment; filename=readme.txt" } });
  });
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  await expect(page.getByText("Documents").first()).toBeVisible();
  await page.getByText("Documents").first().dblclick();
  await expect.poll(() => state.calls.filter((call) => call === "GET /api/files/list").length).toBeGreaterThan(1);

  await page.getByTitle("New folder").click();
  await page.getByLabel("Folder name").fill("e2e-folder");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect.poll(() => state.calls.some((call) => call === "POST /api/files/mkdir")).toBeTruthy();

  await page.getByLabel("Select Documents").click();
  await page.getByTitle("Rename").click();
  const renameDialog = page.getByLabel("Rename", { exact: true });
  await renameDialog.getByLabel("New name").fill("Documents-renamed");
  await renameDialog.getByRole("button", { name: "Rename", exact: true }).click();
  await expect.poll(() => state.calls.some((call) => call === "POST /api/files/rename")).toBeTruthy();

  await page.locator('input[type="file"]').first().setInputFiles({ name: "upload.txt", mimeType: "text/plain", buffer: Buffer.from("test") });
  await expect.poll(() => state.calls.some((call) => call === "POST /api/files/uploads")).toBeTruthy();
  await expect.poll(() => state.calls.some((call) => call === "PATCH /api/files/uploads/upload-e2e")).toBeTruthy();

  await page.getByLabel("Select readme.txt").click();
  const download = page.waitForEvent("download");
  await page.getByTitle("Download").click();
  await download;
  await expect.poll(() => state.calls.some((call) => call === "GET /api/files/download")).toBeTruthy();

  await page.getByTitle("Delete").click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => state.calls.some((call) => call === "POST /api/files/delete")).toBeTruthy();
});

test("DCST loads, creates Port and IPSet, validates and creates Service, then deletes a test object", async ({ page }) => {
  const state = await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "DCST");
  await expect(page.getByRole("navigation", { name: "DCST sections" })).toBeVisible();

  await page.getByRole("button", { name: /Ports/ }).click();
  await page.getByRole("button", { name: "+ Create Port Object", exact: true }).click();
  const port = page.getByRole("dialog", { name: "Create Port Object" });
  await port.getByLabel("Name").fill("E2E_HTTPS");
  await port.getByRole("button", { name: "Create Port Object", exact: true }).click();
  await expect.poll(() => state.ports.length).toBe(1);

  await page.getByRole("button", { name: /IPSets/ }).click();
  await page.getByRole("button", { name: "+ Create IP Set", exact: true }).click();
  const ipset = page.getByRole("dialog", { name: "Create IP Set" });
  await ipset.getByLabel("Name").fill("E2E_NET");
  await ipset.getByLabel("IP / CIDR entries").fill("10.20.0.0/16");
  await ipset.getByRole("button", { name: "Create IP Set", exact: true }).click();
  await expect.poll(() => state.ipsets.length).toBe(1);

  await page.getByRole("button", { name: /Services/ }).click();
  await page.getByRole("button", { name: "+ New Service", exact: true }).click();
  const service = page.getByRole("dialog", { name: /Create Communication Service/ });
  await service.getByRole("button", { name: "Create Service", exact: true }).click();
  await expect(service.locator(".dcst-field-error").first()).toBeVisible();
  await service.getByLabel("Service name").fill("E2E_SERVICE");
  const objectTypes = service.getByLabel("Object type");
  await objectTypes.nth(0).selectOption("any");
  await objectTypes.nth(1).selectOption("any");
  await service.getByRole("button", { name: "Create Service", exact: true }).click();
  await expect.poll(() => state.services.length).toBe(1);

  await page.getByRole("button", { name: /Ports/ }).click();
  await page.getByRole("button", { name: "Delete E2E_HTTPS", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(() => state.calls.some((call) => call === "DELETE /api/modules/dcst/ports/port-1")).toBeTruthy();
});

test("Package Center loads catalog and executes mocked install and uninstall", async ({ page }) => {
  const state = await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Module Center");
  await expect(page.getByText("Samba").first()).toBeVisible();
  await page.getByRole("button", { name: "Install", exact: true }).first().click();
  const installConfirm = page.getByRole("button", { name: /Confirm/ }).first();
  await expect(installConfirm).toBeVisible();
  await installConfirm.click();
  await expect.poll(() => state.calls.some((call) => call === "POST /api/apps/samba/install")).toBeTruthy();
  await expect.poll(() => state.packageInstalled).toBeTruthy();

  await page.reload();
  await openDesktopApp(page, "Module Center");
  await expect(page.getByText("Samba").first()).toBeVisible();
  await page.getByRole("button", { name: "Uninstall", exact: true }).first().click();
  const uninstallConfirm = page.getByRole("button", { name: /Confirm/ }).first();
  await expect(uninstallConfirm).toBeVisible();
  await uninstallConfirm.click();
  await expect.poll(() => state.calls.some((call) => call === "POST /api/apps/samba/uninstall")).toBeTruthy();
});
