import { describe, expect, it } from "vitest";
import type { ModuleSummary, PackageModule } from "../../api";
import { canManagePackageJob, getPackageActions, getPackageInstalledVersion, getPackageServiceStatus, getPackageUiStatus, isPackageUpdateAvailable, matchesPackageSearch, mergePackageCatalog } from "./packageState";

function packageItem(options: { installed?: boolean; running?: boolean; update?: boolean; needsConfig?: boolean; error?: boolean } = {}): ModuleSummary {
  const installed = options.installed ?? false;
  const running = options.running ?? false;
  const serviceState = running ? "active" : "inactive";
  return {
    id: "demo",
    manifest: {
      id: "demo", name: "Demo", description: "Demo module", long_description: "Demo module description", category: "system_tools", version: "1.0.0", maintainer: "WebNAS", homepage: null, icon: "package", screenshots: [], license: "MIT",
      supported_distributions: ["debian"], supported_architectures: ["x86_64"], apt_packages: ["demo"], dnf_packages: ["demo"], systemd_services: ["demo"], ports: [], dependencies: [], conflicts: [], permissions: [], config_paths: [], data_paths: [], backup_paths: [], proxmox_safe: true, requires_reboot: false, requires_root: true, configurable: true, removable: true, changelog: [],
    },
    state: { installed, installed_version: installed ? "1.0.0" : null, available_version: options.update ? "1.1.0" : "1.0.0", update_available: options.update ?? false, requires_reboot: false, needs_configuration: options.needsConfig ?? false },
    services: { demo: serviceState },
    status: options.error ? "error" : !installed ? "available" : options.needsConfig ? "needs_config" : options.update ? "update_available" : running ? "running" : "stopped",
    compatible: true,
    blocked_by_proxmox: false,
    distribution: { id: "debian", name: "Debian", architecture: "x86_64", package_manager: "apt-get" },
    jobs: [],
    module_status: { installed, package_version: installed ? "1.0.0" : null, available_version: options.update ? "1.1.0" : "1.0.0", update_available: options.update ?? false, service_state: serviceState, service_enabled: installed, services: { demo: { state: serviceState, enabled: installed, required: true } }, configuration_valid: options.needsConfig ? false : true, health: options.error ? "failed" : installed ? "healthy" : "not_installed", health_message: "", last_action: "", last_action_status: "", last_error: options.error ? "failed" : "", metrics: {} },
    capabilities: { install: true, update: true, uninstall: true, configure: true, service_control: true, reload: true, logs: true, diagnostics: true, backups: true, import_export: true, healthcheck: true, resources: [], actions: [] },
    active_job: null,
  };
}

describe("Package Center state matrix", () => {
  it("creates an installable Samba summary when only catalog metadata is available", () => {
    const runtime = packageItem();
    const catalog: PackageModule = {
      id: "samba",
      manifest: { ...runtime.manifest, id: "samba", name: "Samba", icon: "share-2", apt_packages: ["samba", "smbclient", "cifs-utils"] },
      state: runtime.state,
      services: { smbd: "inactive" },
      status: "available",
      compatible: true,
      blocked_by_proxmox: false,
      distribution: runtime.distribution,
      jobs: [],
    };

    const [samba] = mergePackageCatalog([catalog], []);

    expect(samba.id).toBe("samba");
    expect(samba.manifest.apt_packages).toContain("cifs-utils");
    expect(getPackageActions(samba)).toEqual(["install"]);
  });

  it("deduplicates catalog and runtime entries using the module id", () => {
    const runtime = packageItem({ installed: true, running: true });
    const catalog: PackageModule = {
      id: runtime.id,
      manifest: runtime.manifest,
      state: { ...runtime.state, installed: false },
      services: {},
      status: "available",
      compatible: true,
      blocked_by_proxmox: false,
      distribution: runtime.distribution,
      jobs: [],
    };

    const merged = mergePackageCatalog([catalog], [runtime]);

    expect(merged).toHaveLength(1);
    expect(merged[0]).toBe(runtime);
  });

  it("searches module names, descriptions and real manifest categories", () => {
    const item = packageItem();
    const t = (key: string) => key === "package.category.system_tools" ? "System tools" : key;

    expect(matchesPackageSearch(item, "demo", t)).toBe(true);
    expect(matchesPackageSearch(item, "system_tools", t)).toBe(true);
    expect(matchesPackageSearch(item, "system tools", t)).toBe(true);
    expect(matchesPackageSearch(item, "database", t)).toBe(false);
  });

  it("maps job mutation permissions to the original operation", () => {
    expect(canManagePackageJob("install", ["modules.view"])).toBe(false);
    expect(canManagePackageJob("install", ["modules.install"])).toBe(true);
    expect(canManagePackageJob("restart", ["modules.configure"])).toBe(true);
    expect(canManagePackageJob("unknown", ["modules.install", "modules.configure"])).toBe(false);
  });

  it("offers only installation for a package that is not installed", () => {
    const item = packageItem();
    expect(getPackageUiStatus(item)).toBe("not_installed");
    expect(getPackageActions(item)).toEqual(["install"]);
    expect(getPackageInstalledVersion(item)).toBe("—");
    expect(getPackageServiceStatus(item)).toBe("not_applicable");
  });

  it("opens the managed installer for an uninstalled container application", () => {
    const item = packageItem();
    item.capabilities = { ...item.capabilities, install: false, actions: ["install_container", "container_start"] };

    expect(getPackageActions(item)).toEqual(["open"]);
  });

  it("offers opening and stopping for an installed running package", () => {
    const item = packageItem({ installed: true, running: true });
    expect(getPackageUiStatus(item)).toBe("running");
    expect(getPackageActions(item)).toEqual(["open", "stop"]);
    expect(getPackageActions(item)).not.toContain("install");
  });

  it("offers start when an installed package is stopped", () => {
    const item = packageItem({ installed: true });
    expect(getPackageUiStatus(item)).toBe("stopped");
    expect(getPackageActions(item)).toEqual(["start"]);
  });

  it("offers configuration before service actions when configuration is invalid", () => {
    const item = packageItem({ installed: true, needsConfig: true });
    expect(getPackageUiStatus(item)).toBe("stopped");
    expect(getPackageActions(item)).toEqual(["configure"]);
  });

  it("adds update while preserving valid running service actions", () => {
    const item = packageItem({ installed: true, running: true, update: true });
    expect(getPackageUiStatus(item)).toBe("running");
    expect(getPackageActions(item)).toEqual(["update", "open", "stop"]);
  });

  it("does not present workload updates as a Package Center module update", () => {
    const item = packageItem({ installed: true, update: true });
    item.id = "linux-updates";
    item.capabilities = { ...item.capabilities, update: false, configure: false, service_control: false, actions: ["refresh", "upgrade_all"] };
    item.module_status.service_state = "not_applicable";

    expect(item.module_status.update_available).toBe(true);
    expect(isPackageUpdateAvailable(item)).toBe(false);
    expect(getPackageUiStatus(item)).toBe("installed");
    expect(getPackageActions(item)).toEqual(["open"]);
  });

  it("does not replace an active service status with an operation error", () => {
    const item = packageItem({ installed: true, running: true, error: true });
    item.jobs = [{ id: "job-1", module_id: "demo", action: "duplicate", status: "failed", progress: 100, created_at: 1, error: "409: UNSAFE_CONTAINER_CONFIGURATION", current_step: "Failed", log_tail: [] }];

    expect(item.module_status.health).toBe("failed");
    expect(item.module_status.last_error).toBe("failed");
    expect(getPackageServiceStatus(item)).toBe("running");
    expect(getPackageUiStatus(item)).toBe("running");
  });

  it("shows error only when a required service has failed", () => {
    const item = packageItem({ installed: true });
    item.module_status.services.demo.state = "failed";

    expect(getPackageServiceStatus(item)).toBe("error");
    expect(getPackageUiStatus(item)).toBe("error");
  });
});
