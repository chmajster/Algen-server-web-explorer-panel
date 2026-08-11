import { request } from "../../../core/api/transport";
import {
  asArray,
  asBoolean,
  asFiniteNumber,
  asNumberRecord,
  asOptionalFiniteNumber,
  asRecord,
  asRecordArray,
  asString,
  asStringArray,
  normalizePagination,
} from "../../../core/api/runtimeGuards";
import "./container-actions.css";
import type {
  DockerApp,
  DockerAppAction,
  DockerAppInstall,
  DockerArtifact,
  DockerBackupRestore,
  DockerComposeAction,
  DockerComposeSave,
  DockerContainer,
  DockerContainerAction,
  DockerContainerCreate,
  DockerContainerDefaultsPolicy,
  DockerContainerSettings,
  DockerContainerSettingsUpdate,
  DockerDashboard,
  DockerDefaultBridgeConfig,
  DockerDefaultBridgeSave,
  DockerEngineAction,
  DockerImage,
  DockerImageAction,
  DockerNetwork,
  DockerNetworkAction,
  DockerNetworkContainer,
  DockerNetworkCreate,
  DockerPaged,
  DockerPrune,
  DockerPrunePlan,
  DockerRegistry,
  DockerRegistryCatalogResult,
  DockerRegistrySave,
  DockerRegistrySource,
  DockerRegistryTagsResult,
  DockerVolumeAction,
  DockerVolumeCreate,
  ModuleBackup,
  ModuleDiagnostic,
  ModuleJob,
  ModuleResource,
  ModuleStatus,
  ModuleValidationResult,
} from "../../../core/api/contracts";

function normalizeContainerCreate(payload: DockerContainerCreate): DockerContainerCreate {
  if ((payload.network ?? "").trim() !== "host") return payload;
  return {
    ...payload,
    network: "host",
    ports: [],
    network_aliases: [],
  };
}

function normalizeContainerAction(payload: DockerContainerAction): DockerContainerAction {
  if (payload.action === "stop") {
    const graceful = { ...payload };
    delete graceful.timeout;
    delete graceful.signal;
    return graceful;
  }
  if (payload.action === "kill") {
    const forced = { ...payload };
    delete forced.timeout;
    return { ...forced, signal: "KILL" };
  }
  return payload;
}

function normalizeModuleStatus(value: unknown): ModuleStatus {
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

function normalizePaged<T>(value: unknown): DockerPaged<T> {
  const source = asRecord(value);
  const items = asArray<T>(source.items);
  const page = Math.max(1, Math.trunc(asFiniteNumber(source.page, 1)));
  const pageSize = Math.max(1, Math.trunc(asFiniteNumber(source.page_size, items.length || 50)));
  const total = Math.max(0, Math.trunc(asFiniteNumber(source.total, items.length)));
  const pages = Math.max(1, Math.trunc(asFiniteNumber(source.pages, Math.ceil(total / pageSize) || 1)));
  return {
    ...source,
    items,
    total,
    page,
    page_size: pageSize,
    pages,
  } as DockerPaged<T>;
}

function normalizeContainerRow(value: unknown): DockerContainer {
  const source = asRecord(value);
  return {
    ...source,
    Networks: asStringArray(source.Networks),
    Mounts: asRecordArray(source.Mounts),
  } as DockerContainer;
}

function normalizeImage(value: unknown): DockerImage {
  const source = asRecord(value);
  return {
    ...source,
    consumers: asStringArray(source.consumers),
  } as DockerImage;
}

function normalizeNetwork(value: unknown): DockerNetwork {
  const source = asRecord(value);
  return {
    ...source,
    Name: asString(source.Name),
    Driver: asString(source.Driver),
    subnets: asStringArray(source.subnets),
    gateways: asStringArray(source.gateways),
    ip_ranges: asStringArray(source.ip_ranges),
    options: asRecord(source.options) as Record<string, string>,
    labels: asRecord(source.labels) as Record<string, string>,
  } as DockerNetwork;
}

function normalizeDockerApp(value: unknown): DockerApp {
  const source = asRecord(value);
  return {
    ...source,
    id: asString(source.id),
    name: asString(source.name),
    description: asString(source.description),
    image: asString(source.image),
    container: asString(source.container),
    category: asString(source.category),
    panel_port: asFiniteNumber(source.panel_port, 0),
    ports: asStringArray(source.ports),
    version: asString(source.version),
    required_secrets: asStringArray(source.required_secrets),
    architectures: asStringArray(source.architectures),
    healthcheck: asString(source.healthcheck),
    dependencies: asStringArray(source.dependencies),
    minimum_memory_mb: asFiniteNumber(source.minimum_memory_mb, 0),
    documentation_url: asString(source.documentation_url),
    update_strategy: asString(source.update_strategy),
    backup_strategy: asString(source.backup_strategy),
    uninstall_strategy: asString(source.uninstall_strategy),
    installed: asBoolean(source.installed),
    running: asBoolean(source.running),
    managed: asBoolean(source.managed),
    status: asString(source.status, "unknown"),
  } as DockerApp;
}

function normalizeModuleBackup(value: unknown): ModuleBackup {
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

function normalizeArtifact(value: unknown): DockerArtifact {
  const source = asRecord(value);
  const metadata = asRecord(source.metadata);
  return {
    ...source,
    id: asString(source.id),
    kind: asString(source.kind),
    display_name: asString(source.display_name),
    checksum: asString(source.checksum),
    size: asFiniteNumber(source.size, 0),
    created_at: asFiniteNumber(source.created_at, 0),
    created_by: asString(source.created_by),
    metadata: {
      ...metadata,
      environment_keys: asStringArray(metadata.environment_keys),
    },
  } as DockerArtifact;
}

function normalizeDashboard(value: unknown): DockerDashboard {
  const source = asRecord(value);
  const security = asRecordArray(source.security).map((item) => ({
    level: asString(item.level, "info"),
    message: asString(item.message),
  }));
  return {
    ...source,
    status: normalizeModuleStatus(source.status),
    counts: asNumberRecord(source.counts),
    storage: asRecordArray(source.storage),
    security,
    engine: asRecord(source.engine),
    usage: {
      cpu_percent: asFiniteNumber(asRecord(source.usage).cpu_percent, 0),
      memory_bytes: asFiniteNumber(asRecord(source.usage).memory_bytes, 0),
    },
    events: asRecordArray(source.events),
    updates: asRecordArray(source.updates),
    prune_preview: asRecord(source.prune_preview),
  } as DockerDashboard;
}

function normalizeContainerDetails(value: unknown): Record<string, unknown> {
  const source = asRecord(value);
  return {
    ...source,
    state: asRecord(source.state),
    health: asRecord(source.health),
    limits: asRecord(source.limits),
    ports: asRecord(source.ports),
    networks: asRecord(source.networks),
    mounts: asRecordArray(source.mounts),
    labels: asRecord(source.labels),
    environment_keys: asStringArray(source.environment_keys),
  };
}

function normalizeContainerStats(value: unknown) {
  const source = asRecord(value);
  return {
    current: source.current === null ? null : asRecord(source.current),
    history: asRecordArray(source.history),
  };
}

function normalizeLines(value: unknown) {
  const source = asRecord(value);
  const lines = asStringArray(source.lines);
  return {
    ...source,
    lines,
    total: Math.max(0, Math.trunc(asFiniteNumber(source.total, lines.length))),
    truncated: asBoolean(source.truncated),
  };
}

function normalizeItems(value: unknown) {
  const source = asRecord(value);
  const items = asRecordArray(source.items);
  return {
    ...source,
    items,
    total: Math.max(0, Math.trunc(asFiniteNumber(source.total, items.length))),
  };
}

function normalizeContainerCompose(value: unknown) {
  const source = asRecord(value);
  return {
    content: asString(source.content),
    secrets_omitted: asBoolean(source.secrets_omitted),
    environment_keys: asStringArray(source.environment_keys),
  };
}

function normalizeContainerSettings(value: unknown): DockerContainerSettings {
  const source = asRecord(value);
  const availablePorts = asRecordArray(source.available_ports)
    .map((item) => {
      const protocol = asString(item.protocol, "tcp");
      const target = asOptionalFiniteNumber(item.target);
      const published = asOptionalFiniteNumber(item.published);
      if (
        target === null ||
        published === null ||
        !["tcp", "udp"].includes(protocol)
      ) {
        return null;
      }
      return {
        target,
        published,
        protocol: protocol as "tcp" | "udp",
        host_ip: item.host_ip === null || item.host_ip === undefined
          ? null
          : asString(item.host_ip),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  const priority = asString(source.cpu_priority, "medium");
  const portalProtocol = asString(source.portal_protocol, "http");
  return {
    name: asString(source.name),
    resource_limits_enabled: asBoolean(source.resource_limits_enabled),
    cpu_priority: (["low", "medium", "high"].includes(priority)
      ? priority
      : "medium") as DockerContainerSettings["cpu_priority"],
    memory_mb: asOptionalFiniteNumber(source.memory_mb),
    auto_restart: asBoolean(source.auto_restart),
    restart_policy: asString(source.restart_policy, "no"),
    portal_enabled: asBoolean(source.portal_enabled),
    portal_port: asOptionalFiniteNumber(source.portal_port),
    portal_published_port: asOptionalFiniteNumber(source.portal_published_port),
    portal_protocol: (portalProtocol === "https" ? "https" : "http"),
    compose_managed: asBoolean(source.compose_managed),
    available_ports: availablePorts,
  };
}

function normalizeModuleResource(value: unknown): ModuleResource {
  const source = asRecord(value);
  const items = asRecordArray(source.items);
  return {
    ...source,
    resource: asString(source.resource),
    items,
    total: Math.max(0, Math.trunc(asFiniteNumber(source.total, items.length))),
  } as ModuleResource;
}

function normalizeComposeProject(value: unknown) {
  const source = asRecord(value);
  const environmentSource = asRecord(source.environment);
  const environment: Record<string, string> = {};
  for (const [key, item] of Object.entries(environmentSource)) {
    environment[key] = asString(item);
  }
  return {
    name: asString(source.name),
    content: asString(source.content),
    environment,
    secrets_configured: asBoolean(source.secrets_configured),
    history: asRecordArray(source.history),
    plan: asRecord(source.plan),
  };
}

function normalizeRegistryCatalog(value: unknown): DockerRegistryCatalogResult {
  const source = asRecord(value);
  return {
    items: asArray<DockerRegistryCatalogResult["items"][number]>(source.items),
    pagination: normalizePagination(source.pagination) as DockerRegistryCatalogResult["pagination"],
    source: asRecord(source.source) as DockerRegistrySource,
  };
}

function normalizeRegistryTags(value: unknown): DockerRegistryTagsResult {
  const source = asRecord(value);
  return {
    repository: asString(source.repository),
    pull_reference: asString(source.pull_reference),
    tags: asStringArray(source.tags),
    pagination: normalizePagination(source.pagination) as DockerRegistryTagsResult["pagination"],
    source: asRecord(source.source) as DockerRegistrySource,
  };
}

function normalizeBackups(value: unknown) {
  const source = asRecord(value);
  return {
    configuration: asArray(source.configuration).map(normalizeModuleBackup),
    artifacts: asArray(source.artifacts).map(normalizeArtifact),
  };
}

function normalizeDiagnostics(value: unknown) {
  const source = asRecord(value);
  return {
    generated_at: asFiniteNumber(source.generated_at, 0),
    status: normalizeModuleStatus(source.status),
    checks: asArray<ModuleDiagnostic>(source.checks),
    config: asRecord(source.config),
    prune: asRecord(source.prune),
  };
}

function normalizePrunePlan(value: unknown): DockerPrunePlan {
  const source = asRecord(value);
  return {
    resources: asStringArray(source.resources),
    items: asRecordArray(source.items) as DockerPrunePlan["items"],
    total: Math.max(0, Math.trunc(asFiniteNumber(source.total, 0))),
    estimated_reclaimable: Math.max(0, asFiniteNumber(source.estimated_reclaimable, 0)),
  };
}

function exposeHostNetwork(value: unknown): DockerPaged<DockerNetwork> {
  const result = normalizePaged<DockerNetwork>(value);
  return {
    ...result,
    items: result.items
      .map(normalizeNetwork)
      .map((item) => item.Name === "host"
        ? { ...item, Name: "host " }
        : item),
  };
}

export const containersClient = {
  dockerDashboard: async () => normalizeDashboard(
    await request<unknown>("/api/modules/docker/dashboard"),
  ),

  dockerEngine: async () => {
    const value = asRecord(await request<unknown>("/api/modules/docker/engine"));
    return {
      status: normalizeModuleStatus(value.status),
      config: asRecord(value.config),
      diagnostics: asArray<ModuleDiagnostic>(value.diagnostics),
    };
  },

  dockerEngineAction: async (payload: DockerEngineAction) => {
    const value = asRecord(await request<unknown>("/api/modules/docker/engine/actions", {
      method: "POST",
      body: JSON.stringify(payload),
    }));
    return {
      ...value,
      job: value.job as ModuleJob | undefined,
      diagnostics: asArray<ModuleDiagnostic>(value.diagnostics),
    } as { job?: ModuleJob; diagnostics?: ModuleDiagnostic[] };
  },

  dockerDaemonConfig: async () => {
    const value = asRecord(await request<unknown>("/api/modules/docker/daemon-config"));
    return {
      config: asRecord(value.config),
      path: asString(value.path),
      valid: asBoolean(value.valid),
      error: asString(value.error),
    };
  },

  validateDockerDaemonConfig: (config: Record<string, unknown>) =>
    request<ModuleValidationResult>("/api/modules/docker/daemon-config/validate", {
      method: "POST",
      body: JSON.stringify({ config, confirmation: "" }),
    }),

  saveDockerDaemonConfig: (
    config: Record<string, unknown>,
    pamPassword: string,
  ) => request<{ job: ModuleJob; validation: ModuleValidationResult }>(
    "/api/modules/docker/daemon-config",
    {
      method: "PUT",
      body: JSON.stringify({
        config,
        confirmation: "daemon.json",
        pam_password: pamPassword,
      }),
    },
  ),

  dockerContainers: async (params: Record<string, string | number> = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => query.set(key, String(value)));
    query.set("_refresh", String(Date.now()));
    const page = normalizePaged<DockerContainer>(
      await request<unknown>(`/api/modules/docker/containers?${query}`, {
        cache: "no-store",
      }),
    );
    return {
      ...page,
      items: page.items.map(normalizeContainerRow),
    };
  },

  dockerContainer: async (target: string) => normalizeContainerDetails(
    await request<unknown>(`/api/modules/docker/containers/${encodeURIComponent(target)}`),
  ),

  dockerContainerStats: async (target: string, historyHours = 1) =>
    normalizeContainerStats(
      await request<unknown>(
        `/api/modules/docker/containers/${encodeURIComponent(target)}/stats?history_hours=${historyHours}`,
      ),
    ),

  dockerContainerLogs: async (
    target: string,
    params: Record<string, string | number> = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => query.set(key, String(value)));
    return normalizeLines(
      await request<unknown>(
        `/api/modules/docker/containers/${encodeURIComponent(target)}/logs?${query}`,
      ),
    );
  },

  dockerContainerProcesses: async (target: string) => normalizeItems(
    await request<unknown>(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/processes`,
    ),
  ) as { items: Array<Record<string, string>>; total: number; truncated: boolean },

  dockerContainerCompose: async (target: string) => normalizeContainerCompose(
    await request<unknown>(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/compose`,
    ),
  ),

  dockerContainerSettings: async (target: string) => normalizeContainerSettings(
    await request<unknown>(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/settings`,
    ),
  ),

  updateDockerContainerSettings: (
    target: string,
    payload: DockerContainerSettingsUpdate,
  ) => request<{ job: ModuleJob }>(
    `/api/modules/docker/containers/${encodeURIComponent(target)}/settings`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  ),

  dockerContainerDefaultsPolicy: () =>
    request<DockerContainerDefaultsPolicy>("/api/modules/docker/policy/container-defaults"),

  saveDockerContainerDefaultsPolicy: (payload: DockerContainerDefaultsPolicy) =>
    request<DockerContainerDefaultsPolicy>("/api/modules/docker/policy/container-defaults", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  createDockerContainer: (payload: DockerContainerCreate) =>
    request<{ job: ModuleJob }>("/api/modules/docker/containers", {
      method: "POST",
      body: JSON.stringify(normalizeContainerCreate(payload)),
    }),

  dockerContainerAction: (target: string, payload: DockerContainerAction) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/actions`,
      {
        method: "POST",
        body: JSON.stringify(normalizeContainerAction(payload)),
      },
    ),

  dockerContainerBackup: (target: string) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/backup?confirmation=${encodeURIComponent(target)}`,
      { method: "POST", body: "{}" },
    ),

  dockerContainerExport: (target: string) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/export?confirmation=${encodeURIComponent(target)}`,
      { method: "POST", body: "{}" },
    ),

  importDockerContainerFilesystem: (file: File, repository: string) => {
    const body = new FormData();
    body.set("file", file);
    body.set("repository", repository);
    body.set("confirmation", repository);
    return request<{ job: ModuleJob }>("/api/modules/docker/containers/import", {
      method: "POST",
      body,
    });
  },

  dockerImages: async (params: Record<string, string | number> = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => query.set(key, String(value)));
    const page = normalizePaged<DockerImage>(
      await request<unknown>(`/api/modules/docker/images?${query}`),
    );
    return {
      ...page,
      items: page.items.map(normalizeImage),
    };
  },

  dockerImageAction: (payload: DockerImageAction) =>
    request<{ job: ModuleJob }>("/api/modules/docker/images/actions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  importDockerImage: (file: File) => {
    const body = new FormData();
    body.set("file", file);
    return request<{ job: ModuleJob }>("/api/modules/docker/images/import", {
      method: "POST",
      body,
    });
  },

  dockerVolumes: async (search = "") => normalizePaged<Record<string, unknown>>(
    await request<unknown>(
      `/api/modules/docker/volumes?search=${encodeURIComponent(search)}`,
    ),
  ),

  createDockerVolume: (payload: DockerVolumeCreate) =>
    request<{ job: ModuleJob }>("/api/modules/docker/volumes", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  dockerVolumeAction: (target: string, payload: DockerVolumeAction) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/volumes/${encodeURIComponent(target)}/actions`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  dockerNetworks: async (search = "") => exposeHostNetwork(
    await request<unknown>(
      `/api/modules/docker/networks?page_size=200&search=${encodeURIComponent(search)}`,
    ),
  ),

  dockerNetworkContainers: async (target: string) => {
    const raw = await request<unknown>(
      `/api/modules/docker/networks/${encodeURIComponent(target)}/containers`,
    );
    const value = normalizeItems(raw);
    return {
      ...value,
      items: value.items as DockerNetworkContainer[],
      network: asString(asRecord(raw).network, target),
    };
  },

  dockerDefaultBridge: () =>
    request<DockerDefaultBridgeConfig>("/api/modules/docker/networks/default-bridge"),

  saveDockerDefaultBridge: (payload: DockerDefaultBridgeSave) =>
    request<{ job: ModuleJob; validation: ModuleValidationResult }>(
      "/api/modules/docker/networks/default-bridge",
      { method: "PUT", body: JSON.stringify(payload) },
    ),

  createDockerNetwork: (payload: DockerNetworkCreate) =>
    request<{ job: ModuleJob }>("/api/modules/docker/networks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  dockerNetworkAction: (target: string, payload: DockerNetworkAction) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/networks/${encodeURIComponent(target)}/actions`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  dockerComposeProjects: async () => normalizeModuleResource(
    await request<unknown>("/api/modules/docker/compose"),
  ),

  dockerComposeProject: async (project: string) => normalizeComposeProject(
    await request<unknown>(
      `/api/modules/docker/compose/${encodeURIComponent(project)}`,
    ),
  ),

  saveDockerComposeProject: (
    project: string,
    payload: DockerComposeSave,
  ) => request<Record<string, unknown>>(
    `/api/modules/docker/compose/${encodeURIComponent(project)}`,
    { method: "PUT", body: JSON.stringify(payload) },
  ),

  validateDockerCompose: (project: string, payload: DockerComposeSave) =>
    request<Record<string, unknown>>(
      `/api/modules/docker/compose/${encodeURIComponent(project)}/validate`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  dockerComposeAction: (project: string, payload: DockerComposeAction) =>
    request<{ job?: ModuleJob; valid?: boolean }>(
      `/api/modules/docker/compose/${encodeURIComponent(project)}/actions`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  rollbackDockerCompose: (
    project: string,
    revision: string,
    confirmation: string,
  ) => request<Record<string, unknown>>(
    `/api/modules/docker/compose/${encodeURIComponent(project)}/history/${encodeURIComponent(revision)}/rollback?confirmation=${encodeURIComponent(confirmation)}`,
    { method: "POST", body: "{}" },
  ),

  dockerComposeStatus: async (project: string) => normalizeItems(
    await request<unknown>(
      `/api/modules/docker/compose/${encodeURIComponent(project)}/status`,
    ),
  ),

  dockerComposeLogs: async (project: string, service = "") => normalizeLines(
    await request<unknown>(
      `/api/modules/docker/compose/${encodeURIComponent(project)}/logs?tail=500&service=${encodeURIComponent(service)}`,
    ),
  ),

  dockerApps: async (search = "") => {
    const value = normalizeItems(
      await request<unknown>(
        `/api/modules/docker/apps?search=${encodeURIComponent(search)}`,
      ),
    );
    return {
      ...value,
      items: value.items.map(normalizeDockerApp),
    };
  },

  installDockerApp: (id: string, payload: DockerAppInstall) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/apps/${encodeURIComponent(id)}/install`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  dockerAppAction: (
    id: string,
    action: "start" | "stop" | "restart" | "update" | "remove",
    payload: DockerAppAction = {},
  ) => request<{ job: ModuleJob }>(
    `/api/modules/docker/apps/${encodeURIComponent(id)}/${action}`,
    { method: "POST", body: JSON.stringify(payload) },
  ),

  dockerRegistries: async () => {
    const value = normalizeItems(
      await request<unknown>("/api/modules/docker/registries"),
    );
    return { items: value.items as DockerRegistry[] };
  },

  dockerRegistrySources: async () => asArray<DockerRegistrySource>(
    await request<unknown>("/api/modules/docker/registries/sources"),
  ),

  dockerRegistryCatalog: async (params: {
    registry_id: string;
    query: string;
    page?: number;
    page_size?: number;
    official?: "all" | "official" | "unofficial";
    sort?: "relevance" | "name" | "stars";
    direction?: "asc" | "desc";
  }) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) query.set(key, String(value));
    });
    return normalizeRegistryCatalog(
      await request<unknown>(`/api/modules/docker/registries/catalog?${query}`),
    );
  },

  dockerRegistryTags: async (
    registryId: string,
    repositoryName: string,
    page = 1,
    pageSize = 100,
  ) => {
    const query = new URLSearchParams({
      registry_id: registryId,
      repository_name: repositoryName,
      page: String(page),
      page_size: String(pageSize),
    });
    return normalizeRegistryTags(
      await request<unknown>(`/api/modules/docker/registries/tags?${query}`),
    );
  },

  saveDockerRegistry: (payload: DockerRegistrySave, id = "") =>
    request<{ registry: DockerRegistry; job: ModuleJob }>(
      id
        ? `/api/modules/docker/registries/${encodeURIComponent(id)}`
        : "/api/modules/docker/registries",
      {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(payload),
      },
    ),

  testDockerRegistry: (id: string) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/registries/${encodeURIComponent(id)}/test`,
      { method: "POST", body: "{}" },
    ),

  logoutDockerRegistry: (id: string) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/registries/${encodeURIComponent(id)}/logout`,
      { method: "POST", body: "{}" },
    ),

  deleteDockerRegistry: (id: string, confirmation: string) =>
    request<{ ok: boolean }>(
      `/api/modules/docker/registries/${encodeURIComponent(id)}?confirmation=${encodeURIComponent(confirmation)}`,
      { method: "DELETE", body: "{}" },
    ),

  dockerBackups: async () => normalizeBackups(
    await request<unknown>("/api/modules/docker/backups"),
  ),

  restoreDockerBackup: (id: string, payload: DockerBackupRestore) =>
    request<{ job: ModuleJob }>(
      `/api/modules/docker/backups/${encodeURIComponent(id)}/restore`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  dockerDiagnostics: async () => normalizeDiagnostics(
    await request<unknown>("/api/modules/docker/diagnostics"),
  ),

  dockerEvents: async () => normalizeItems(
    await request<unknown>("/api/modules/docker/events?since_seconds=3600&limit=500"),
  ),

  dockerPrune: (payload: DockerPrune) =>
    request<{ job: ModuleJob }>("/api/modules/docker/prune", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  dockerPrunePlan: async (resources: DockerPrune["resources"]) =>
    normalizePrunePlan(
      await request<unknown>(
        `/api/modules/docker/prune/plan?resources=${encodeURIComponent(resources.join(","))}`,
      ),
    ),
} as const;
