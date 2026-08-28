import type { Page, Route } from "@playwright/test";

export type E2EState = {
  authenticated: boolean;
  ports: Array<Record<string, unknown>>;
  ipsets: Array<Record<string, unknown>>;
  services: Array<Record<string, unknown>>;
  packageInstalled: boolean;
  calls: string[];
};

const permissions = [
  "files.view", "files.read", "files.download", "files.upload", "files.create", "files.edit", "files.rename", "files.delete",
  "transfers.view_own", "transfers.create", "settings.view_own", "settings.edit_own", "system.status", "modules.view", "modules.install",
  "modules.update", "modules.uninstall", "modules.configure", "dcst.read", "dcst.manage_services", "dcst.block_traffic", "dcst.sync",
  "dcst.manage_tags", "dcst.manage_ipsets", "dcst.manage_ports", "dcst.view_logs",
];

const profile = {
  language: "en-US", theme: "light", startup_windows: "none", wallpaper: "", accent_color: "blue", wallpaper_fit: "cover", taskbar_alignment: "center",
  pinned_apps: ["files", "settings"], pinned_modules: [], start_pinned_apps: ["files", "settings"], desktop_shortcut_apps: ["files", "settings"],
  show_desktop_shortcuts: true, desktop_shortcut_size: "medium", show_welcome_widget: false, show_notifications: true, show_transfer_indicator: true,
  show_background_actions_indicator: true, window_transparency: true, animations_enabled: false, clock_show_seconds: false, date_format: "short", time_format: "24",
  interface_scale: 100, interface_font: "system", larger_text: false, high_contrast: false, reduced_motion: true, strong_active_borders: false, always_show_focus: false,
  file_default_view: "list", file_compact_rows: false, file_show_hidden: false, file_confirm_delete: true, file_confirm_overwrite: true, file_page_size: 50,
  file_default_sort: "name", file_sort_direction: "asc", file_remember_last_path: false, transfer_success_notifications: true, transfer_error_notifications: true,
  transfer_open_failed_details: false, transfer_remember_filter: true, notification_transfer: true, notification_errors: true, notification_admin: true,
  notification_auto_hide: false, notification_limit: 5, first_day_of_week: "monday", widgets_enabled: false, desktop_widgets: [], username: "e2e", uid: 1000,
  gid: 1000, groups: ["users"], home: "/home/e2e", shell: "/bin/bash", gecos: "E2E User", is_admin: true, role: "admin", role_source: "test", permissions,
};

const directory = { name: "Documents", path: "/home/e2e/Documents", type: "directory", is_dir: true, size: 0, owner: "e2e", group: "users", mode: "0755", permissions: "drwxr-xr-x", modified: 1, mtime: 1, mime: "inode/directory", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false };
const textFile = { name: "readme.txt", path: "/home/e2e/readme.txt", type: "text", is_dir: false, size: 4, owner: "e2e", group: "users", mode: "0644", permissions: "-rw-r--r--", modified: 2, mtime: 2, mime: "text/plain", can_read: true, can_write: true, can_delete: true, can_rename: true, is_symlink: false };

function respond(route: Route, value: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

export async function installMockApi(page: Page, authenticated = true): Promise<E2EState> {
  const state: E2EState = { authenticated, ports: [], ipsets: [], services: [], packageInstalled: false, calls: [] };
  await page.addInitScript(() => localStorage.setItem("webnas_language", "en-US"));
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (!path.startsWith("/api/")) return route.continue();
    const method = request.method();
    state.calls.push(`${method} ${path}`);

    if (path === "/api/auth/me") return state.authenticated ? respond(route, { username: "e2e", home: "/home/e2e", csrf_token: "csrf" }) : respond(route, { detail: "Not authenticated" }, 401);
    if (path === "/api/auth/login") {
      const body = request.postDataJSON() as { username?: string; password?: string };
      if (body.username !== "e2e" || body.password !== "correct") return respond(route, { detail: "Invalid username or password" }, 401);
      state.authenticated = true;
      return respond(route, { username: "e2e", home: "/home/e2e", csrf_token: "csrf" });
    }
    if (path === "/api/auth/logout") { state.authenticated = false; return respond(route, { ok: true }); }
    if (path === "/api/settings/me") return respond(route, profile);
    if (path.includes("tasks")) return respond(route, []);
    if (path.includes("updates/progress") || path === "/api/system/update-status") return respond(route, { state: "idle", running: false, progress: 0, steps: [], blockers: [], lines: [], log: "", message: "", active_count: 0 });
    if (path.includes("updates/completion")) return respond(route, { notice: null });
    if (path === "/api/files/local-disks" || path === "/api/mounts" || path === "/api/mounts/roots") return respond(route, []);
    if (path === "/api/files/tree") return respond(route, { path: url.searchParams.get("path") || "/home/e2e", items: [directory] });
    if (path === "/api/files/list") return respond(route, { path: url.searchParams.get("path") || "/home/e2e", current_path: url.searchParams.get("path") || "/home/e2e", parent_path: "/home/e2e", items: [directory, textFile], page: 1, page_size: 50, total_items: 2, total_pages: 1, sort: "name", direction: "asc", can_write: true, can_upload: true, can_delete: true });
    if (path === "/api/files/uploads" && method === "POST") return respond(route, { upload_id: "upload-e2e", offset: 0, size: 4, path: "/home/e2e/upload.txt", completed: false });
    if (path === "/api/files/uploads/upload-e2e" && method === "PATCH") return respond(route, { upload_id: "upload-e2e", offset: 4, size: 4, path: "/home/e2e/upload.txt", completed: true });
    if (path === "/api/files/download") return route.fulfill({ status: 200, body: "test", headers: { "content-type": "text/plain", "content-disposition": "attachment; filename=readme.txt" } });
    if (path === "/api/files/mkdir" || path === "/api/files/rename") return respond(route, { ok: true });
    if (path === "/api/files/delete") return respond(route, { task_id: "delete-e2e" });
    if (path.startsWith("/api/files/")) return respond(route, { ok: true });
    if (path === "/api/apps/samba/config") return respond(route, { shares: [] });

    if (path === "/api/modules/dcst/overview") return respond(route, { services: state.services.length, active_services: state.services.length, blocked_services: 0, ports: state.ports.length, ipsets: state.ipsets.length, tags: 1, firewall_rules: state.services.length, firewall: {}, last_inventory_sync: { at: 1 }, last_firewall_sync: {}, recent_changes: [] });
    if (path === "/api/modules/dcst/tags") return respond(route, [{ id: "tag-1", name: "APP.PROD", apmid: "APP", environment: "PROD", provider_name: "test", sync_status: "ok", vm_count: 1, addresses: ["10.0.0.10"], hosts: [] }]);
    if (path === "/api/modules/dcst/ports" && method === "GET") return respond(route, state.ports);
    if (path === "/api/modules/dcst/ports" && method === "POST") { const item = { id: `port-${state.ports.length + 1}`, dependencies: [], ...(request.postDataJSON() as object) }; state.ports.push(item); return respond(route, item); }
    if (path === "/api/modules/dcst/ipsets" && method === "GET") return respond(route, state.ipsets);
    if (path === "/api/modules/dcst/ipsets" && method === "POST") { const body = request.postDataJSON() as { name: string; description: string; entries: string[] }; const item = { id: `ipset-${state.ipsets.length + 1}`, name: body.name, description: body.description, type: "manual", provider_name: "test", sync_status: "ok", last_error: "", entries: body.entries.map((address, id) => ({ id: String(id), address, comment: "" })), dependencies: [] }; state.ipsets.push(item); return respond(route, item); }
    if (path.startsWith("/api/modules/dcst/services") && method === "GET") return respond(route, state.services);
    if (path === "/api/modules/dcst/services" && method === "POST") { const item = { id: `service-${state.services.length + 1}`, blocked: false, system_service: false, sync_status: "ok", state: "ACTIVE", last_error: "", ...(request.postDataJSON() as object) }; state.services.push(item); return respond(route, item); }
    if (path.startsWith("/api/modules/dcst/")) return respond(route, { ok: true });

    const module = { id: "samba", manifest: { id: "samba", name: "Samba", description: "File sharing", long_description: "Samba test package", category: "file_sharing", version: "1.0.0", maintainer: "WebNAS", homepage: null, icon: "share-2", screenshots: [], license: "GPL", supported_distributions: ["debian"], supported_architectures: ["x86_64"], apt_packages: ["samba"], dnf_packages: [], systemd_services: ["smbd"], ports: ["445/tcp"], dependencies: [], conflicts: [], permissions: [], config_paths: [], data_paths: [], backup_paths: [], changelog: [], removable: true, configurable: true }, state: { installed: state.packageInstalled, installed_version: state.packageInstalled ? "1.0.0" : null, available_version: "1.0.0", update_available: false, requires_reboot: false, needs_configuration: false }, services: { smbd: state.packageInstalled ? "active" : "inactive" }, status: state.packageInstalled ? "running" : "available", compatible: true, blocked_by_proxmox: false, distribution: { id: "debian", name: "Debian", architecture: "x86_64", package_manager: "apt-get" }, jobs: [], module_status: { installed: state.packageInstalled, package_version: state.packageInstalled ? "1.0.0" : null, available_version: "1.0.0", update_available: false, service_state: state.packageInstalled ? "active" : "inactive", service_enabled: state.packageInstalled, services: {}, health: state.packageInstalled ? "healthy" : "not_installed", health_message: "", last_action: "", last_action_status: "", last_error: "", metrics: {} }, capabilities: { install: true, update: true, uninstall: true, configure: true, service_control: true, reload: true, logs: true, diagnostics: true, backups: true, import_export: true, healthcheck: true, resources: [], actions: [] }, active_job: null };
    if (path === "/api/apps" || path === "/api/modules") return respond(route, [module]);
    if (path === "/api/apps/categories") return respond(route, ["file_sharing"]);
    if (path === "/api/apps/jobs" || path === "/api/apps/history" || path === "/api/apps/sources") return respond(route, []);
    if (path.includes("/api/apps/samba/plan")) return respond(route, { module_id: "samba", action: url.searchParams.get("action") || "install", distribution: { id: "debian", name: "Debian", version_id: "12", architecture: "x86_64", package_manager: "apt-get" }, compatible: true, blocked_by_proxmox: false, packages: ["samba"], services: ["smbd"], ports: [], config_paths: [], data_paths: [], permissions: [], dependencies: [], conflicts: [], warnings: [], requires_reboot: false, remove_data: false, target_version: "1.0.0", steps: ["apt-get install -y samba"] });
    if (path === "/api/apps/samba/install" && method === "POST") { state.packageInstalled = true; return respond(route, { job: { id: "job-install", module_id: "samba", action: "install", status: "completed", progress: 100, created_at: 1, finished_at: 2, log_tail: [], error: "", warnings: [], result: {} } }); }
    if (path === "/api/apps/samba/uninstall" && method === "POST") { state.packageInstalled = false; return respond(route, { job: { id: "job-uninstall", module_id: "samba", action: "uninstall", status: "completed", progress: 100, created_at: 1, finished_at: 2, log_tail: [], error: "", warnings: [], result: {} } }); }
    return respond(route, {});
  });
  return state;
}

export async function openDesktopApp(page: Page, name: string) {
  await page.getByRole("button", { name: "Main menu" }).click();
  const launcher = page.locator(".app-launcher");
  await launcher.locator(".launcher-search input").fill(name);
  await launcher.getByRole("button", { name, exact: true }).first().click();
}
