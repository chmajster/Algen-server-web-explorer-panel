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
  ModuleBackup,
  ModuleCapability,
  ModuleConfig,
  ModuleConnection,
  ModuleDiagnostic,
  ModuleJob,
  ModuleLogSource,
  ModuleResource,
  ModuleStatus,
  ModuleSummary,
  ModuleValidationResult,
  PackageModule,
} from "../../../core/api/contracts";

function normalizeJob(value: unknown): AppJob {
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
  } as AppJob;
}

function normalizeStatus(value: unknown): ModuleStatus {
  const source = asRecord(value);
  const health = asString(source.health, "unknown");
  return {
    ...source,
    installed: asBoolean(source.installed),
    update_available: asBoolean(source.update_available),
    service_state: asString(source.service_state, "unknown"),
    service_enabled: asBoolean(source.service_enabled),
    services: asRecord(source.services),
    health: (["healthy", "degraded", "failed", "unknown", "not_installed"].includes(health)
      ? health
      : "unknown") as ModuleStatus["health"],
    health_message: asString(source.health_message),
    last_action: asString(source.last_action),
    last_action_status: asString(source.last_action_status),
    last_error: asString(source.last_error),
    metrics: asRecord(source.metrics),
  } as ModuleStatus;
}

function normalizeCapabilities(value: unknown): ModuleCapability {
  const source = asRecord(value);
  return {
    install: asBoolean(source.install),
    update: asBoolean(source.update),
    uninstall: asBoolean(source.uninstall),
    configure: asBoolean(source.configure),
    service_control: asBoolean(source.service_control),
    reload: asBoolean(source.reload),
    logs: asBoolean(source.logs),
    diagnostics: asBoolean(source.diagnostics),
    backups: asBoolean(source.backups),
    import_export: asBoolean(source.import_export),
    healthcheck: asBoolean(source.healthcheck),
    resources: asStringArray(source.resources),
    actions: asStringArray(source.actions),
  };
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

function normalizeSummary(value: unknown): ModuleSummary {
  const source = asRecord(value);
  return {
    ...normalizePackageModule(source),
    module_status: normalizeStatus(source.module_status),
    capabilities: normalizeCapabilities(source.capabilities),
    active_job: source.active_job ? normalizeJob(source.active_job) : null,
  } as ModuleSummary;
}

function normalizeResource(value: unknown): ModuleResource {
  const source = asRecord(value);
  const items = asRecordArray(source.items);
  return {
    ...source,
    resource: asString(source.resource),
    items,
    total: Math.max(0, Math.trunc(asFiniteNumber(source.total, items.length))),
  } as ModuleResource;
}

function normalizeLogs(value: unknown) {
  const source = asRecord(value);
  const sources = asArray<ModuleLogSource>(source.sources);
  return {
    sources,
    source: asString(source.source, sources[0]?.id || ""),
    lines: asStringArray(source.lines),
    truncated: asBoolean(source.truncated),
  };
}

function normalizeBackup(value: unknown): ModuleBackup {
  const source = asRecord(value);
  return {
    ...source,
    id: asString(source.id),
    module_id: asString(source.module_id),
    created_at: asFiniteNumber(source.created_at, 0),
    created_by: asString(source.created_by),
    description: asString(source.description),
    automatic: asBoolean(source.automatic),
    checksum: asString(source.checksum),
    package_version: asString(source.package_version),
    size: asFiniteNumber(source.size, 0),
    files: asStringArray(source.files),
  } as ModuleBackup;
}

function normalizeDiagnostics(
  value: unknown,
): { diagnostics: ModuleDiagnostic[]; job?: ModuleJob | null } {
  const source = asRecord(value);
  const diagnostics = asArray<ModuleDiagnostic>(source.diagnostics);
  if (!source.job) return { diagnostics };
  return {
    diagnostics,
    job: normalizeJob(source.job) as ModuleJob,
  };
}

export const moduleCenterClient = {
  modules: async () => asArray(await request<unknown>("/api/modules"))
    .map(normalizeSummary),

  module: async (id: string) => normalizeSummary(
    await request<unknown>(`/api/modules/${encodeURIComponent(id)}`),
  ),

  moduleStatus: async (id: string) => normalizeStatus(
    await request<unknown>(`/api/modules/${encodeURIComponent(id)}/status`),
  ),

  moduleResource: async (
    id: string,
    resource: string,
    limit = 200,
    search = "",
  ) => normalizeResource(
    await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/resources/${encodeURIComponent(resource)}?limit=${limit}&search=${encodeURIComponent(search)}`,
    ),
  ),

  moduleAction: async (
    id: string,
    action: string,
    payload: Record<string, unknown> = {},
  ) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`,
      {
        method: "POST",
        body: JSON.stringify({ confirm: true, payload }),
      },
    ));
    return { job: normalizeJob(value.job) as ModuleJob };
  },

  moduleConnection: (id: string) =>
    request<ModuleConnection>(`/api/modules/${encodeURIComponent(id)}/connection`),

  saveModuleConnection: (
    id: string,
    connection: Omit<ModuleConnection, "secret_configured"> & { secret?: string },
  ) => request<ModuleConnection>(
    `/api/modules/${encodeURIComponent(id)}/connection`,
    {
      method: "PUT",
      body: JSON.stringify({ ...connection, confirm: true }),
    },
  ),

  saveDockerCompose: (
    project: string,
    content: string,
  ) => request<{ name: string; updated_at: number; size: number }>(
    `/api/modules/docker/compose/${encodeURIComponent(project)}`,
    {
      method: "PUT",
      body: JSON.stringify({ content, confirm: true }),
    },
  ),

  dockerCompose: async (project: string) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/docker/compose/${encodeURIComponent(project)}`,
    ));
    return {
      name: asString(value.name, project),
      content: asString(value.content),
      updated_at: asFiniteNumber(value.updated_at, 0),
      size: asFiniteNumber(value.size, 0),
    };
  },

  moduleConfig: async (id: string) => asRecord(
    await request<unknown>(`/api/modules/${encodeURIComponent(id)}/config`),
  ) as ModuleConfig,

  validateModuleConfig: async (
    id: string,
    config: ModuleConfig,
  ) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/validate`,
      {
        method: "POST",
        body: JSON.stringify({ config }),
      },
    ));
    return {
      ...value,
      ok: asBoolean(value.ok),
      errors: asStringArray(value.errors),
      warnings: asStringArray(value.warnings),
      changes: asArray(value.changes),
      generated_config: asString(value.generated_config),
      validator_output: asString(value.validator_output),
      confirmations_required: asStringArray(value.confirmations_required),
    } as ModuleValidationResult;
  },

  applyModuleConfig: async (
    id: string,
    config: ModuleConfig,
    confirmations: string[] = [],
  ) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/apply`,
      {
        method: "POST",
        body: JSON.stringify({
          config,
          confirm: true,
          create_backup: true,
          confirm_smb1: confirmations.includes("smb1"),
        }),
      },
    ));
    return { job: normalizeJob(value.job) as ModuleJob };
  },

  moduleLogs: async (
    id: string,
    source = "",
    lines = 200,
    search = "",
    level = "",
  ) => {
    const query = new URLSearchParams({
      source,
      lines: String(lines),
      search,
      level,
    });
    return normalizeLogs(
      await request<unknown>(
        `/api/modules/${encodeURIComponent(id)}/logs?${query}`,
      ),
    );
  },

  moduleDiagnostics: async (id: string) => normalizeDiagnostics(
    await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/diagnostics`,
    ),
  ),

  runModuleDiagnostics: async (id: string) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/diagnostics`,
      {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      },
    ));
    return { job: normalizeJob(value.job) as ModuleJob };
  },

  moduleBackups: async (id: string) => asArray(
    await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/backups`,
    ),
  ).map(normalizeBackup),

  createModuleBackup: async (id: string, description = "") =>
    normalizeBackup(
      await request<unknown>(
        `/api/modules/${encodeURIComponent(id)}/backups`,
        {
          method: "POST",
          body: JSON.stringify({ confirm: true, description }),
        },
      ),
    ),

  restoreModuleBackup: async (id: string, backupId: string) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/backups/${encodeURIComponent(backupId)}/restore`,
      {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      },
    ));
    return { job: normalizeJob(value.job) as ModuleJob };
  },

  deleteModuleBackup: (
    id: string,
    backupId: string,
  ) => request(
    `/api/modules/${encodeURIComponent(id)}/backups/${encodeURIComponent(backupId)}`,
    {
      method: "DELETE",
      body: JSON.stringify({ confirm: true }),
    },
  ),

  moduleService: async (
    id: string,
    action: "start" | "stop" | "restart" | "reload" | "enable" | "disable",
  ) => {
    const value = asRecord(await request<unknown>(
      `/api/modules/${encodeURIComponent(id)}/service/${action}`,
      {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      },
    ));
    return { job: normalizeJob(value.job) as ModuleJob };
  },
} as const;
