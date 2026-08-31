import { expect, test, type Locator } from "@playwright/test";
import { installMockApi, openDesktopApp } from "./mockApi";

async function expectNoHorizontalOverflow(locator: Locator) {
  await expect.poll(async () => locator.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
}

async function expectSeparated(upper: Locator, lower: Locator) {
  const upperBox = await upper.boundingBox();
  const lowerBox = await lower.boundingBox();
  expect(upperBox).not.toBeNull();
  expect(lowerBox).not.toBeNull();
  expect(lowerBox!.y - (upperBox!.y + upperBox!.height)).toBeGreaterThan(4);
}

async function resizeSettingsWindow(settingsWindow: Locator, width: number) {
  await settingsWindow.evaluate((element, nextWidth) => {
    const windowElement = element as HTMLElement;
    windowElement.style.width = `${nextWidth}px`;
    windowElement.style.height = "700px";
  }, width);
}

async function chooseSettingsCategory(settingsWindow: Locator, category: "administration" | "authentication") {
  const categorySelect = settingsWindow.locator(".settings-header > select");
  await expect(categorySelect).toHaveCount(1);
  await categorySelect.evaluate((element, nextCategory) => {
    const select = element as HTMLSelectElement;
    select.value = nextCategory;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, category);
}

test("Settings Administration and PAM / LDAP stay contained in a narrow desktop window", async ({ page }) => {
  await installMockApi(page);

  await page.route("**/api/system/host-info", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      hostname: "very-long-webnas-production-server-name.example.internal",
      operating_system: "Linux E2E",
      kernel_version: "7.0.0-e2e",
      architecture: "x86_64",
      ip_addresses: ["10.0.0.12"],
      uptime_seconds: 3600,
      cpu: { model: "E2E CPU", physical_cores: 4, logical_threads: 8 },
      memory: { total: 8589934592 },
      gpus: [],
      application_version: "0.1.32",
      storage: { free: 53687091200, total: 107374182400, percent: 50 },
    }),
  }));

  const ldapSettings = {
    enabled: false,
    directory_type: "auto",
    servers: [],
    server: "",
    port: 389,
    failover_strategy: "priority",
    dns_srv_domain: "",
    security_mode: "starttls",
    verify_tls: true,
    ca_certificate: "",
    connect_timeout: 5,
    operation_timeout: 10,
    base_dn: "OU=Users,OU=Corporate,DC=example,DC=internal",
    user_search_base: "OU=Users,OU=Corporate,DC=example,DC=internal",
    user_search_filter: "(uid={username})",
    username_attribute: "uid",
    immutable_id_attribute: "entryUUID",
    bind_dn: "CN=WebNAS Service Account,OU=Service Accounts,OU=Infrastructure,DC=example,DC=internal",
    bind_password_configured: false,
    display_name_attribute: "displayName",
    email_attribute: "mail",
    group_search_base: "OU=Groups,OU=Corporate,DC=example,DC=internal",
    group_search_filter: "(member={dn})",
    group_membership_attribute: "memberOf",
    group_cache_ttl_seconds: 300,
  };

  await page.route("**/api/settings/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const respond = (value: unknown) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(value),
    });

    if (path === "/api/settings/transport") {
      return respond({
        use_https: false,
        tls_cert: "/etc/webnas/tls/certificates/production/webnas-production-certificate.crt",
        tls_key: "/etc/webnas/tls/certificates/production/webnas-production-private-key.key",
        scheme: "http",
        public_port: 5000,
      });
    }
    if (path === "/api/settings/authentication") {
      return respond({
        mode: "system",
        configured_mode: "system",
        restart_required: false,
        default_mode: "local",
        local_database_enabled: true,
        system_authentication_enabled: true,
        local_user_count: 1,
        local_enabled_admin_count: 1,
      });
    }
    if (path === "/api/settings/authentication/local-users") {
      return respond({
        users: [{
          username: "e2e-administrator-with-a-long-name",
          role: "admin",
          enabled: true,
          display_name: "WebNAS Administrator With A Long Display Name",
          home: "/home/e2e-administrator-with-a-long-name",
          posix_mapped: true,
          created_at: 1,
          updated_at: 1,
          last_login_at: 1,
          password_changed_at: 1,
        }],
      });
    }
    if (path === "/api/settings/authentication/ldap") return respond(ldapSettings);
    if (path === "/api/settings/authentication/ldap/group-mappings") return respond({ items: [] });
    if (path === "/api/settings/authentication/ldap/access-policy") {
      return respond({ mode: "allow_all", allow_groups: [], deny_groups: [] });
    }
    return route.fallback();
  });

  await page.goto("/");
  await openDesktopApp(page, "Settings");

  const settingsWindow = page.locator('.desktop-window[aria-label="Settings"]');
  await expect(settingsWindow).toBeVisible();

  await chooseSettingsCategory(settingsWindow, "administration");
  await resizeSettingsWindow(settingsWindow, 760);

  const administration = settingsWindow.locator(".administration-dashboard");
  const https = settingsWindow.getByTestId("https-settings-card");
  await expect(administration).toBeVisible();
  await expect(https).toBeVisible();
  await expectNoHorizontalOverflow(settingsWindow.locator(".settings-content"));
  await expectSeparated(administration, https);

  const httpsPath = https.locator('input[type="text"]').first();
  await expect(httpsPath).toBeVisible();
  const httpsControl = httpsPath.locator("xpath=ancestor::*[contains(@class, 'setting-control')]");
  await expectNoHorizontalOverflow(httpsControl);

  await chooseSettingsCategory(settingsWindow, "authentication");

  const authentication = settingsWindow.getByTestId("authentication-settings-card");
  const ldap = settingsWindow.locator(".ldap-settings-shell");
  await expect(authentication).toBeVisible();
  await expect(ldap).toBeVisible();
  await expectNoHorizontalOverflow(settingsWindow.locator(".settings-content"));
  await expectSeparated(authentication, ldap);

  const modeCards = authentication.locator(".auth-mode-card");
  await expect(modeCards).toHaveCount(2);
  const firstMode = await modeCards.nth(0).boundingBox();
  const secondMode = await modeCards.nth(1).boundingBox();
  expect(firstMode).not.toBeNull();
  expect(secondMode).not.toBeNull();
  expect(secondMode!.y).toBeGreaterThan(firstMode!.y + firstMode!.height - 1);

  await expect(ldap.locator(".ldap-action-bar")).toHaveCSS("position", "static");
});
