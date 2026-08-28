import { expect, test } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

test("authentication covers invalid login, login, logout and missing session", async ({ page }) => {
  const state = await installMockApi(page, false);
  await page.goto("/");
  await page.getByLabel("Linux user").fill("e2e");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid username or password");
  await page.getByLabel("Password").fill("correct");
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
  await windows.first().click();
  await expect(windows.first()).toHaveClass(/active/);
  await windows.first().getByRole("button", { name: "Close" }).click();
  await expect(windows).toHaveCount(1);
});

test("file manager enters a directory and exposes create, rename, upload, download and delete actions", async ({ page }) => {
  const state = await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "File Manager");
  await expect(page.getByText("Documents").first()).toBeVisible();
  await page.getByText("Documents").first().dblclick();
  await expect.poll(() => state.calls.some((call) => call === "GET /api/files/list")).toBeTruthy();
  await expect(page.getByTitle("New folder")).toBeVisible();
  await expect(page.getByTitle("Upload")).toBeVisible();
  await expect(page.getByTitle("Rename")).toBeVisible();
  await expect(page.getByTitle("Download")).toBeVisible();
  await expect(page.getByTitle("Delete")).toBeVisible();
});

test("DCST loads, creates Port and IPSet, validates Service and submits a valid Service", async ({ page }) => {
  const state = await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "DCST");
  await expect(page.getByRole("navigation", { name: "DCST sections" })).toBeVisible();

  await page.getByRole("button", { name: /Ports/ }).click();
  await page.getByRole("button", { name: "+ Create Port Object" }).click();
  const port = page.getByRole("dialog", { name: "Create Port Object" });
  await port.getByLabel("Name").fill("E2E_HTTPS");
  await port.getByRole("button", { name: "Create Port Object" }).click();
  await expect.poll(() => state.ports.length).toBe(1);

  await page.getByRole("button", { name: /IPSets/ }).click();
  await page.getByRole("button", { name: "+ Create IP Set" }).click();
  const ipset = page.getByRole("dialog", { name: "Create IP Set" });
  await ipset.getByLabel("Name").fill("E2E_NET");
  await ipset.getByLabel("IP / CIDR entries").fill("10.20.0.0/16");
  await ipset.getByRole("button", { name: "Create IP Set" }).click();
  await expect.poll(() => state.ipsets.length).toBe(1);

  await page.getByRole("button", { name: /Services/ }).click();
  await page.getByRole("button", { name: "+ New Service" }).click();
  const service = page.getByRole("dialog", { name: /Create Communication Service/ });
  await service.getByRole("button", { name: "Create Service" }).click();
  await expect(service.locator(".dcst-field-error").first()).toBeVisible();
  await service.getByLabel("Service name").fill("E2E_SERVICE");
  const objectTypes = service.getByLabel("Object type");
  await objectTypes.nth(0).selectOption("any");
  await objectTypes.nth(1).selectOption("any");
  await service.getByRole("button", { name: "Create Service" }).click();
  await expect.poll(() => state.services.length).toBe(1);
});

test("Package Center loads catalog and starts mocked install", async ({ page }) => {
  const state = await installMockApi(page);
  await page.goto("/");
  await openDesktopApp(page, "Module Center");
  await expect(page.getByText("Samba").first()).toBeVisible();
  await page.getByRole("button", { name: "Install" }).first().click();
  await expect(page.getByText("apt-get install -y samba")).toBeVisible();
  await page.getByRole("button", { name: /Confirm/ }).click();
  await expect.poll(() => state.calls.some((call) => call === "POST /api/apps/samba/install")).toBeTruthy();
});
