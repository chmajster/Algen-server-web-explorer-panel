import { describe, expect, it } from "vitest";
import type { ModuleSummary, PackageModule } from "../../api";
import { getPackageActions, getPackageInstalledVersion, getPackageServiceStatus, getPackageUiStatus, mergePackageCatalog } from "./packageState";

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

  it("offers only installation for a package that is not installed", () => {
    const item = packageItem();
    expect(getPackageUiStatus(item)).toBe("not_installed");
    expect(getPackageActions(item)).toEqual(["install"]);
    expect(getPackageInstalledVersion(item)).toBe("—");
    expect(getPackageServiceStatus(item)).toBe("not_applicable");
  });

  it("offers opening and stopping for an installed running package", () => {
    const item = packageItem({ installed: true, running: true });
    expect(getPackageUiStatus(item)).toBe("running");
    expect(getPackageActions(item)).toEqual(["open", "stop"]);
    expect(getPackageActions(item)).not.toContain("install");
  });

  it("offers only start for service control when an installed package is stopped", () => {
    const item = packageItem({ installed: true });
    expect(getPackageUiStatus(item)).toBe("stopped");
    expect(getPackageActions(item)).toEqual(["start"]);
  });

  it("offers configuration before service actions when configuration is invalid", () => {
    const item = packageItem({ installed: true, needsConfig: true });
    expect(getPackageUiStatus(item)).toBe("needs_config");
    expect(getPackageActions(item)).toEqual(["configure"]);
  });

  it("adds update while preserving valid running service actions", () => {
    const item = packageItem({ installed: true, running: true, update: true });
    expect(getPackageUiStatus(item)).toBe("update_available");
    expect(getPackageActions(item)).toEqual(["update", "open", "stop"]);
  });

  it("normalizes technical failures to the user-facing error state", () => {
    expect(getPackageUiStatus(packageItem({ installed: true, error: true }))).toBe("error");
  });
});
