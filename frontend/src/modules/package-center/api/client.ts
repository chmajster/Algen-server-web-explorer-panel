import { request } from "../../../core/api/transport";
import {
  asArray,
  asBoolean,
  asFiniteNumber,
  asRecord,
  asRecordArray,
  asString,
  asStringArray,
} from "../../../core/api/runtimeGuards";
import type {
  AppJob,
  PackageHistoryItem,
  PackageModule,
  PackagePlan,
  PackageSource,
  SambaConfig,
  StorePlugin,
} from "../../../core/api/contracts";

function normalizeAppJob(value: unknown): AppJob {
  const source = asRecord(value);
  const status = asString(source.status, "queued");
  const logTail = asRecordArray(source.log_tail).map((entry, index) => ({
    id: Math.trunc(asFiniteNumber(entry.id, index + 1)),
    created_at: asFiniteNumber(entry.created_at, 0),
    stream: asString(entry.stream, "stdout"),
    line: asString(entry.line),
  }));
  return {
    ...source,
    id: asString(source.id),
    module_id: asString(source.module_id),
    action: asString(source.action),
    status: (["queued", "running", "completed", "failed", "cancelled"].includes(status)
      ? status
      : "queued") as AppJob["status"],
    progress: Math.max(0, Math.min(100, asFiniteNumber(source.progress, 0))),
    created_at: asFiniteNumber(source.created_at, 0),
    finished_at: source.finished_at === null || source.finished_at === undefined
      ? null
      : asFiniteNumber(source.finished_at, 0),
    log_tail: logTail,
    error: asString(source.error),
    warnings: asStringArray(source.warnings),
    result: asRecord(source.result),
    cancellation_requested: asBoolean(source.cancellation_requested),
    cancellable: source.cancellable === undefined
      ? true
      : asBoolean(source.cancellable),
    requires_reboot: asBoolean(source.requires_reboot),
  } as AppJob;
}

function normalizePackageModule(value: unknown): PackageModule {
  const source = asRecord(value);
  const manifest = asRecord(source.manifest);
  const state = asRecord(source.state);
  return {
    ...source,
    id: asString(source.id, asString(manifest.id)),
    manifest: {
      ...manifest,
      id: asString(manifest.id, asString(source.id)),
      name: asString(manifest.name, asString(source.id)),
      description: asString(manifest.description),
      long_description: asString(manifest.long_description),
      category: asString(manifest.category),
      version: asString(manifest.version),
      maintainer: asString(manifest.maintainer),
      homepage: manifest.homepage === null || manifest.homepage === undefined
        ? null
        : asString(manifest.homepage),
      icon: asString(manifest.icon),
      screenshots: asStringArray(manifest.screenshots),
      license: asString(manifest.license),
      supported_distributions: asStringArray(manifest.supported_distributions),
      supported_architectures: asStringArray(manifest.supported_architectures),
      apt_packages: asStringArray(manifest.apt_packages),
      dnf_packages: asStringArray(manifest.dnf_packages),
      systemd_services: asStringArray(manifest.systemd_services),
      ports: asStringArray(manifest.ports),
      dependencies: asStringArray(manifest.dependencies),
      conflicts: asStringArray(manifest.conflicts),
      permissions: asStringArray(manifest.permissions),
      config_paths: asStringArray(manifest.config_paths),
      data_paths: asStringArray(manifest.data_paths),
      backup_paths: asStringArray(manifest.backup_paths),
    } as PackageModule["manifest"],
    state: {
      ...state,
      installed: asBoolean(state.installed),
      installed_version: state.installed_version === null || state.installed_version === undefined
        ? null
        : asString(state.installed_version),
      available_version: asString(state.available_version),
      update_available: asBoolean(state.update_available),
      requires_reboot: asBoolean(state.requires_reboot),
      needs_configuration: asBoolean(state.needs_configuration),
    } as PackageModule["state"],
    services: asRecord(source.services) as PackageModule["services"],
    status: asString(source.status, "unknown"),
  } as PackageModule;
}

function normalizePlan(value: unknown): PackagePlan {
  const source = asRecord(value);
  const arrayFields = [
    "packages",
    "apt_packages",
    "dnf_packages",
    "services",
    "ports",
    "dependencies",
    "conflicts",
    "permissions",
    "warnings",
    "steps",
    "config_paths",
    "data_paths",
    "backup_paths",
    "confirmations_required",
  ];
  const normalized: Record<string, unknown> = { ...source };
  for (const key of arrayFields) {
    if (key in source) normalized[key] = asArray(source[key]);
  }
  normalized.distribution = asRecord(source.distribution);
  return normalized as PackagePlan;
}

export const packageCenterClient = {
  apps: async (params: Record<string, string | boolean> = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== "") query.set(key, String(value));
    });
    return asArray(await request<unknown>(
      `/api/apps${query.size ? `?${query}` : ""}`,
    )).map(normalizePackageModule);
  },

  app: async (id: string) => normalizePackageModule(
    await request<unknown>(`/api/apps/${encodeURIComponent(id)}`),
  ),

  appCategories: async () => asStringArray(
    await request<unknown>("/api/apps/categories"),
  ),

  appInstalled: async () => asArray(
    await request<unknown>("/api/apps/installed"),
  ).map(normalizePackageModule),

  appUpdates: async () => asArray(
    await request<unknown>("/api/apps/updates"),
  ).map(normalizePackageModule),

  appPlan: async (
    id: string,
    action: PackagePlan["action"],
    remove_data = false,
  ) => normalizePlan(
    await request<unknown>(
      `/api/apps/${encodeURIComponent(id)}/plan?action=${encodeURIComponent(action)}&remove_data=${remove_data}`,
      { method: "POST", body: "{}" },
    ),
  ),

  appJobs: async (status = "", moduleId = "") => {
    const query = new URLSearchParams();
    if (status) query.set("status", status);
    if (moduleId) query.set("module_id", moduleId);
    return asArray(
      await request<unknown>(
        `/api/apps/jobs${query.size ? `?${query}` : ""}`,
      ),
    ).map(normalizeAppJob);
  },

  appJob: async (id: string) => normalizeAppJob(
    await request<unknown>(`/api/apps/jobs/${encodeURIComponent(id)}`),
  ),

  cancelAppJob: async (id: string) => normalizeAppJob(
    await request<unknown>(
      `/api/apps/jobs/${encodeURIComponent(id)}/cancel`,
      {
        method: "POST",
        body: JSON.stringify({ confirm_plan: true }),
      },
    ),
  ),

  retryAppJob: async (id: string) => normalizeAppJob(
    await request<unknown>(
      `/api/apps/jobs/${encodeURIComponent(id)}/retry`,
      {
        method: "POST",
        body: JSON.stringify({ confirm_plan: true }),
      },
    ),
  ),

  appHistory: async () => asArray<PackageHistoryItem>(
    await request<unknown>("/api/apps/history"),
  ),

  packageSources: async () => asArray<PackageSource>(
    await request<unknown>("/api/apps/sources"),
  ),

  createPackageSource: (
    payload: Omit<
      PackageSource,
      "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata"
    >,
  ) => request<PackageSource>("/api/apps/sources", {
    method: "POST",
    body: JSON.stringify(payload),
  }),

  updatePackageSource: (
    id: string,
    payload: Omit<
      PackageSource,
      "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata"
    >,
  ) => request<PackageSource>(
    `/api/apps/sources/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  ),

  deletePackageSource: (id: string) => request(
    `/api/apps/sources/${encodeURIComponent(id)}`,
    { method: "DELETE", body: "{}" },
  ),

  syncPackageSource: (id: string) => request<PackageSource>(
    `/api/apps/sources/${encodeURIComponent(id)}/sync`,
    { method: "POST", body: "{}" },
  ),

  appAction: async (
    id: string,
    action: "install" | "reinstall" | "uninstall" | "update" | "start" | "stop" | "restart",
    remove_data = false,
  ) => {
    const value = asRecord(await request<unknown>(
      `/api/apps/${encodeURIComponent(id)}/${action}`,
      {
        method: "POST",
        body: JSON.stringify({ confirm_plan: true, remove_data }),
      },
    ));
    return {
      ...value,
      job: value.job ? normalizeAppJob(value.job) : undefined,
      ok: asBoolean(value.ok),
    } as { job?: AppJob; ok?: boolean };
  },

  appLogs: async (id: string) => {
    const value = asRecord(await request<unknown>(
      `/api/apps/${encodeURIComponent(id)}/logs`,
    ));
    return { lines: asStringArray(value.lines) };
  },

  appConfig: async (id: string) => asRecord(
    await request<unknown>(`/api/apps/${encodeURIComponent(id)}/config`),
  ) as SambaConfig,

  storePlugins: async () => {
    const value = asRecord(await request<unknown>("/api/apps/plugins"));
    return {
      plugins: asArray<StorePlugin>(value.plugins),
      codex_template: asString(value.codex_template),
    };
  },

  createStorePlugin: (
    plugin: Partial<StorePlugin>,
  ) => request<StorePlugin>("/api/apps/plugins", {
    method: "POST",
    body: JSON.stringify(plugin),
  }),

  updateStorePlugin: (
    id: string,
    plugin: Partial<StorePlugin>,
  ) => request<StorePlugin>(
    `/api/apps/plugins/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      body: JSON.stringify(plugin),
    },
  ),

  deleteStorePlugin: (id: string) => request(
    `/api/apps/plugins/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  ),
} as const;
