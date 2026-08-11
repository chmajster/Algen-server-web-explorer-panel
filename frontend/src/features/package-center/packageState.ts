import type { ModuleCapability, ModuleHealth, ModuleStatus, ModuleSummary, PackageModule } from "../../api";
import type { Translate } from "../../app/types";
import type { PackageAction } from "./types";

export type PackageUiStatus = "not_installed" | "installed" | "running" | "stopped" | "needs_config" | "update_available" | "error";
export type PackageDisplayAction = PackageAction | "open" | "configure";

const RUNNING_STATES = new Set(["active", "running", "started", "online"]);
const ERROR_STATES = new Set(["error", "failed", "incompatible", "blocked"]);

export function getPackageDisplayName(item: Pick<PackageModule, "id" | "manifest">, t: Translate): string {
  return item.id === "docker" ? t("app.containers") : item.manifest.name;
}

function manifestCapabilities(item: PackageModule): ModuleCapability {
  return item.manifest.capabilities || {
    install: true,
    update: true,
    uninstall: item.manifest.removable,
    configure: item.manifest.configurable,
    service_control: item.manifest.systemd_services.length > 0,
    reload: false,
    logs: item.manifest.systemd_services.length > 0,
    diagnostics: false,
    backups: item.manifest.backup_paths.length > 0,
    import_export: false,
    healthcheck: true,
    resources: [],
    actions: [],
  };
}

export function packageCatalogSummary(item: PackageModule): ModuleSummary {
  const capabilities = manifestCapabilities(item);
  const serviceDefinitions = item.manifest.services?.length ? item.manifest.services : item.manifest.systemd_services.map((name) => ({ name, required: true }));
  const serviceState = Object.values(item.services)[0] || (item.state.installed ? "unknown" : "not_installed");
  const failedJob = item.jobs.find((job) => job.status === "failed");
  const health: ModuleHealth = !item.state.installed
    ? "not_installed"
    : ERROR_STATES.has(serviceState.toLowerCase())
      ? "failed"
      : RUNNING_STATES.has(serviceState.toLowerCase())
        ? "healthy"
        : "unknown";
  const moduleStatus: ModuleStatus = {
    installed: item.state.installed,
    package_version: item.state.installed_version,
    available_version: item.state.available_version,
    update_available: item.state.update_available,
    service_state: serviceState,
    service_enabled: false,
    services: Object.fromEntries(serviceDefinitions.map((service) => [service.name, { state: item.services[service.name] || "unknown", enabled: false, required: service.required }])),
    configuration_valid: item.state.needs_configuration ? false : undefined,
    health,
    health_message: item.status,
    last_action: "",
    last_action_status: "",
    last_error: failedJob?.error || "",
    metrics: {},
  };
  return {
    ...item,
    module_status: moduleStatus,
    capabilities,
    active_job: item.jobs.find((job) => ["queued", "running", "waiting_for_confirmation"].includes(job.status)) || null,
  };
}

export function mergePackageCatalog(catalog: PackageModule[], runtime: ModuleSummary[]): ModuleSummary[] {
  const runtimeById = new Map(runtime.map((item) => [item.id, item]));
  const catalogIds = new Set(catalog.map((item) => item.id));
  return [
    ...catalog.map((item) => runtimeById.get(item.id) || packageCatalogSummary(item)),
    ...runtime.filter((item) => !catalogIds.has(item.id)),
  ];
}

export function isPackageRunning(item: ModuleSummary): boolean {
  if (RUNNING_STATES.has(item.module_status.service_state.toLowerCase())) return true;
  if (Object.values(item.services).some((state) => RUNNING_STATES.has(state.toLowerCase()))) return true;
  return Object.values(item.module_status.services).some((service) => RUNNING_STATES.has(service.state.toLowerCase()));
}

export function packageNeedsConfiguration(item: ModuleSummary): boolean {
  return item.state.needs_configuration === true || item.module_status.configuration_valid === false || item.status === "needs_config";
}

export function isPackageUpdateAvailable(item: ModuleSummary): boolean {
  return item.capabilities.update && (item.state.update_available || item.module_status.update_available);
}

export function hasPackageManagement(item: ModuleSummary): boolean {
  return item.capabilities.configure || item.capabilities.resources.length > 0 || item.capabilities.actions.length > 0;
}

export function getPackageUiStatus(item: ModuleSummary): PackageUiStatus {
  if (!item.state.installed) return "not_installed";
  const serviceStatus = getPackageServiceStatus(item);
  return serviceStatus === "not_applicable" ? "installed" : serviceStatus;
}

export function getPackageActions(item: ModuleSummary, options: { advanced?: boolean } = {}): PackageDisplayAction[] {
  if (!item.compatible || item.blocked_by_proxmox) return [];
  const controlledContainer = item.capabilities.actions.includes("install_container");
  if (!item.state.installed) return item.capabilities.install ? ["install"] : controlledContainer ? ["open"] : [];

  const actions: PackageDisplayAction[] = [];
  const advanced = options.advanced === true;
  const running = isPackageRunning(item);
  const manageable = hasPackageManagement(item);

  if (controlledContainer) return hasPackageManagement(item) ? ["open"] : [];
  if (isPackageUpdateAvailable(item)) actions.push("update");

  if (packageNeedsConfiguration(item)) {
    if (manageable) actions.push("configure");
  } else {
    if (manageable && (running || !item.capabilities.service_control)) actions.push("open");
    if (item.capabilities.service_control) {
      actions.push(running ? "stop" : "start");
      if (advanced && running) actions.push("restart");
    }
  }

  if (advanced && item.capabilities.update) actions.push("reinstall");
  if (advanced && item.manifest.removable && item.capabilities.uninstall) actions.push("uninstall");
  return actions;
}

export function getPackageServiceStatus(item: ModuleSummary): "not_applicable" | "running" | "stopped" | "error" {
  if (!item.state.installed || !item.capabilities.service_control) return "not_applicable";
  const serviceStates = Object.values(item.module_status.services)
    .filter((service) => service.required)
    .map((service) => service.state.toLowerCase());
  const states = serviceStates.length
    ? serviceStates
    : [item.module_status.service_state, ...Object.values(item.services)].map((state) => state.toLowerCase());
  if (states.some((state) => ERROR_STATES.has(state))) return "error";
  return isPackageRunning(item) ? "running" : "stopped";
}

export function normalizeServiceState(value: string): "not_applicable" | "running" | "stopped" | "error" {
  const normalized = value.toLowerCase();
  if (RUNNING_STATES.has(normalized)) return "running";
  if (ERROR_STATES.has(normalized)) return "error";
  if (["inactive", "dead", "stopped", "disabled", "exited"].includes(normalized)) return "stopped";
  return "not_applicable";
}

export function packageActionLabelKey(action: PackageDisplayAction): string {
  if (action === "open") return "action.open";
  if (action === "configure") return "package.configure";
  return `store.${action}`;
}

export function getPackageInstalledVersion(item: ModuleSummary): string {
  if (!item.state.installed) return "—";
  return item.module_status.package_version || item.state.installed_version || "—";
}
