import { expect, test, type Page } from "@playwright/test";

type ApiResult<T> = {
  status: number;
  body: T;
};

async function browserApi<T>(
  page: Page,
  path: string,
  init: { method?: string; headers?: Record<string, string>; body?: string } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ({ path: requestPath, init: requestInit }) => {
      const response = await fetch(requestPath, requestInit);
      const text = await response.text();
      let body: unknown = null;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          body = text;
        }
      }
      return { status: response.status, body };
    },
    { path, init },
  ) as Promise<ApiResult<T>>;
}

async function currentUsername(page: Page): Promise<string> {
  const result = await browserApi<{ username: string }>(page, "/api/__e2e/meta");
  expect(result.status).toBe(200);
  return result.body.username;
}

async function login(page: Page): Promise<{ username: string; csrfToken: string }> {
  await page.goto("/");
  const username = await currentUsername(page);
  await page.getByLabel("Linux user").fill(username);
  await page.getByLabel("Password", { exact: true }).fill("correct");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Main menu" })).toBeVisible();
  const me = await browserApi<{ username: string; csrf_token: string }>(page, "/api/auth/me");
  expect(me.status).toBe(200);
  expect(me.body.username).toBe(username);
  return { username, csrfToken: me.body.csrf_token };
}

test("real FastAPI auth covers rejection, cookie session, CSRF, logout and expiry", async ({ page }) => {
  await page.goto("/");
  const username = await currentUsername(page);

  await page.getByLabel("Linux user").fill(username);
  await page.getByLabel("Password", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Invalid username or password");

  await page.getByLabel("Password", { exact: true }).fill("correct");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Main menu" })).toBeVisible();

  const me = await browserApi<{ username: string; csrf_token: string }>(page, "/api/auth/me");
  expect(me.status).toBe(200);
  expect(me.body.username).toBe(username);

  const rejectedLogout = await browserApi<{ detail: { code: string } }>(page, "/api/auth/logout", {
    method: "POST",
  });
  expect(rejectedLogout.status).toBe(403);
  expect(rejectedLogout.body.detail.code).toBe("INVALID_CSRF_TOKEN");

  const logout = await browserApi<{ ok: boolean }>(page, "/api/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": me.body.csrf_token },
  });
  expect(logout.status).toBe(200);
  expect(logout.body.ok).toBe(true);

  await page.reload();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

  const relogin = await login(page);
  expect(relogin.username).toBe(username);
  const expired = await browserApi<{ ok: boolean }>(page, "/api/__e2e/expire-session", { method: "POST" });
  expect(expired.status).toBe(200);
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  const expiredMe = await browserApi<{ detail: string }>(page, "/api/auth/me");
  expect(expiredMe.status).toBe(401);
});

test("real browser-to-FastAPI path performs CSRF-protected Hosts Manager CRUD", async ({ page }) => {
  const { csrfToken } = await login(page);
  const hostPayload = {
    name: "real-e2e-host",
    address: "10.251.0.10",
    approved: true,
    environment: "default",
  };

  const missingCsrf = await browserApi<{ detail: { code: string } }>(
    page,
    "/api/modules/hosts-manager/hosts",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(hostPayload),
    },
  );
  expect(missingCsrf.status).toBe(403);
  expect(missingCsrf.body.detail.code).toBe("INVALID_CSRF_TOKEN");

  const created = await browserApi<{ id: string; name: string; status: string }>(
    page,
    "/api/modules/hosts-manager/hosts",
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify(hostPayload),
    },
  );
  expect(created.status).toBe(200);
  expect(created.body.name).toBe("real-e2e-host");
  expect(created.body.id).toBeTruthy();

  const listed = await browserApi<Array<{ id: string; name: string }>>(
    page,
    "/api/modules/hosts-manager/hosts?limit=20",
  );
  expect(listed.status).toBe(200);
  expect(listed.body.some((item) => item.id === created.body.id)).toBe(true);

  const updated = await browserApi<{ id: string; name: string }>(
    page,
    `/api/modules/hosts-manager/hosts/${created.body.id}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ ...hostPayload, name: "real-e2e-host-updated" }),
    },
  );
  expect(updated.status).toBe(200);
  expect(updated.body.name).toBe("real-e2e-host-updated");

  const invalid = await browserApi<{ detail: unknown }>(page, "/api/modules/hosts-manager/hosts", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ ...hostPayload, name: "invalid-loopback", address: "127.0.0.1" }),
  });
  expect(invalid.status).toBe(422);
  expect(invalid.body.detail).toBeTruthy();

  const removed = await browserApi<{ ok: boolean }>(
    page,
    `/api/modules/hosts-manager/hosts/${created.body.id}`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ confirm: true, confirmation_text: "real-e2e-host-updated" }),
    },
  );
  expect(removed.status).toBe(200);
  expect(removed.body.ok).toBe(true);

  const missing = await browserApi<{ detail: unknown }>(
    page,
    `/api/modules/hosts-manager/hosts/${created.body.id}`,
  );
  expect(missing.status).toBe(404);
});
