import { request } from "../../../core/api/transport";
import "./container-actions.css";
import type { DockerApp, DockerAppAction, DockerAppInstall, DockerArtifact, DockerBackupRestore, DockerComposeAction, DockerComposeSave, DockerContainer, DockerContainerAction, DockerContainerCreate, DockerContainerDefaultsPolicy, DockerContainerSettings, DockerContainerSettingsUpdate, DockerDashboard, DockerDefaultBridgeConfig, DockerDefaultBridgeSave, DockerEngineAction, DockerImage, DockerImageAction, DockerNetwork, DockerNetworkAction, DockerNetworkContainer, DockerNetworkCreate, DockerPaged, DockerPrune, DockerPrunePlan, DockerRegistry, DockerRegistryCatalogResult, DockerRegistrySave, DockerRegistrySource, DockerRegistryTagsResult, DockerVolumeAction, DockerVolumeCreate, ModuleBackup, ModuleDiagnostic, ModuleJob, ModuleResource, ModuleStatus, ModuleValidationResult } from "../../../core/api/contracts";

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
    const { timeout: _ignoredTimeout, signal: _ignoredSignal, ...graceful } = payload;
    return graceful;
  }
  if (payload.action === "kill") {
    const { timeout: _ignoredTimeout, ...forced } = payload;
    return { ...forced, signal: "KILL" };
  }
  return payload;
}

function exposeHostNetwork(result: DockerPaged<DockerNetwork>): DockerPaged<DockerNetwork> {
  return {
    ...result,
    items: result.items.map((item) => String(item.Name || "") === "host"
      ? { ...item, Name: "host " }
      : item),
  };
}

export const containersClient = {
  dockerDashboard: () => request<DockerDashboard>("/api/modules/docker/dashboard"),
  dockerEngine: () => request<{ status: ModuleStatus; config: Record<string, unknown>; diagnostics: ModuleDiagnostic[] }>("/api/modules/docker/engine"),
  dockerEngineAction: (payload: DockerEngineAction) => request<{ job?: ModuleJob; diagnostics?: ModuleDiagnostic[] }>("/api/modules/docker/engine/actions", { method: "POST", body: JSON.stringify(payload) }),
  dockerDaemonConfig: () => request<{ config: Record<string, unknown>; path: string; valid: boolean; error: string }>("/api/modules/docker/daemon-config"),
  validateDockerDaemonConfig: (config: Record<string, unknown>) => request<ModuleValidationResult>("/api/modules/docker/daemon-config/validate", { method: "POST", body: JSON.stringify({ config, confirmation: "" }) }),
  saveDockerDaemonConfig: (config: Record<string, unknown>, pamPassword: string) => request<{ job: ModuleJob; validation: ModuleValidationResult }>("/api/modules/docker/daemon-config", { method: "PUT", body: JSON.stringify({ config, confirmation: "daemon.json", pam_password: pamPassword }) }),
  dockerContainers: (params: Record<string, string | number> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => query.set(key, String(value))); query.set("_refresh", String(Date.now())); return request<DockerPaged<DockerContainer>>(`/api/modules/docker/containers?${query}`, { cache: "no-store" }); },
  dockerContainer: (target: string) => request<Record<string, unknown>>(`/api/modules/docker/containers/${encodeURIComponent(target)}`),
  dockerContainerStats: (target: string, historyHours = 1) => request<{ current: Record<string, unknown> | null; history: Array<Record<string, unknown>> }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/stats?history_hours=${historyHours}`),
  dockerContainerLogs: (target: string, params: Record<string, string | number> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => query.set(key, String(value))); return request<{ lines: string[]; total: number; truncated: boolean }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/logs?${query}`); },
  dockerContainerProcesses: (target: string) => request<{ items: Array<Record<string, string>>; total: number; truncated: boolean }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/processes`),
  dockerContainerCompose: (target: string) => request<{ content: string; secrets_omitted: boolean; environment_keys: string[] }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/compose`),
  dockerContainerSettings: (target: string) => request<DockerContainerSettings>(`/api/modules/docker/containers/${encodeURIComponent(target)}/settings`),
  updateDockerContainerSettings: (target: string, payload: DockerContainerSettingsUpdate) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/settings`, { method: "PUT", body: JSON.stringify(payload) }),
  dockerContainerDefaultsPolicy: () => request<DockerContainerDefaultsPolicy>("/api/modules/docker/policy/container-defaults"),
  saveDockerContainerDefaultsPolicy: (payload: DockerContainerDefaultsPolicy) => request<DockerContainerDefaultsPolicy>("/api/modules/docker/policy/container-defaults", { method: "PUT", body: JSON.stringify(payload) }),
  createDockerContainer: (payload: DockerContainerCreate) => request<{ job: ModuleJob }>("/api/modules/docker/containers", { method: "POST", body: JSON.stringify(normalizeContainerCreate(payload)) }),
  dockerContainerAction: (target: string, payload: DockerContainerAction) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/actions`, { method: "POST", body: JSON.stringify(normalizeContainerAction(payload)) }),
  dockerContainerBackup: (target: string) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/backup?confirmation=${encodeURIComponent(target)}`, { method: "POST", body: "{}" }),
  dockerContainerExport: (target: string) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/export?confirmation=${encodeURIComponent(target)}`, { method: "POST", body: "{}" }),
  importDockerContainerFilesystem: (file: File, repository: string) => { const body = new FormData(); body.set("file", file); body.set("repository", repository); body.set("confirmation", repository); return request<{ job: ModuleJob }>("/api/modules/docker/containers/import", { method: "POST", body }); },
  dockerImages: (params: Record<string, string | number> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => query.set(key, String(value))); return request<DockerPaged<DockerImage>>(`/api/modules/docker/images?${query}`); },
  dockerImageAction: (payload: DockerImageAction) => request<{ job: ModuleJob }>("/api/modules/docker/images/actions", { method: "POST", body: JSON.stringify(payload) }),
  importDockerImage: (file: File) => { const body = new FormData(); body.set("file", file); return request<{ job: ModuleJob }>("/api/modules/docker/images/import", { method: "POST", body }); },
  dockerVolumes: (search = "") => request<DockerPaged>(`/api/modules/docker/volumes?search=${encodeURIComponent(search)}`),
  createDockerVolume: (payload: DockerVolumeCreate) => request<{ job: ModuleJob }>("/api/modules/docker/volumes", { method: "POST", body: JSON.stringify(payload) }),
  dockerVolumeAction: (target: string, payload: DockerVolumeAction) => request<{ job: ModuleJob }>(`/api/modules/docker/volumes/${encodeURIComponent(target)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  dockerNetworks: async (search = "") => exposeHostNetwork(await request<DockerPaged<DockerNetwork>>(`/api/modules/docker/networks?page_size=200&search=${encodeURIComponent(search)}`)),
  dockerNetworkContainers: (target: string) => request<{ items: DockerNetworkContainer[]; total: number; network: string }>(`/api/modules/docker/networks/${encodeURIComponent(target)}/containers`),
  dockerDefaultBridge: () => request<DockerDefaultBridgeConfig>("/api/modules/docker/networks/default-bridge"),
  saveDockerDefaultBridge: (payload: DockerDefaultBridgeSave) => request<{ job: ModuleJob; validation: ModuleValidationResult }>("/api/modules/docker/networks/default-bridge", { method: "PUT", body: JSON.stringify(payload) }),
  createDockerNetwork: (payload: DockerNetworkCreate) => request<{ job: ModuleJob }>("/api/modules/docker/networks", { method: "POST", body: JSON.stringify(payload) }),
  dockerNetworkAction: (target: string, payload: DockerNetworkAction) => request<{ job: ModuleJob }>(`/api/modules/docker/networks/${encodeURIComponent(target)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  dockerComposeProjects: () => request<ModuleResource>("/api/modules/docker/compose"),
  dockerComposeProject: (project: string) => request<{ name: string; content: string; environment: Record<string, string>; secrets_configured: boolean; history: Array<Record<string, unknown>>; plan: Record<string, unknown> }>(`/api/modules/docker/compose/${encodeURIComponent(project)}`),
  saveDockerComposeProject: (project: string, payload: DockerComposeSave) => request<Record<string, unknown>>(`/api/modules/docker/compose/${encodeURIComponent(project)}`, { method: "PUT", body: JSON.stringify(payload) }),
  validateDockerCompose: (project: string, payload: DockerComposeSave) => request<Record<string, unknown>>(`/api/modules/docker/compose/${encodeURIComponent(project)}/validate`, { method: "POST", body: JSON.stringify(payload) }),
  dockerComposeAction: (project: string, payload: DockerComposeAction) => request<{ job?: ModuleJob; valid?: boolean }>(`/api/modules/docker/compose/${encodeURIComponent(project)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  rollbackDockerCompose: (project: string, revision: string, confirmation: string) => request<Record<string, unknown>>(`/api/modules/docker/compose/${encodeURIComponent(project)}/history/${encodeURIComponent(revision)}/rollback?confirmation=${encodeURIComponent(confirmation)}`, { method: "POST", body: "{}" }),
  dockerComposeStatus: (project: string) => request<{ items: Array<Record<string, unknown>>; total: number }>(`/api/modules/docker/compose/${encodeURIComponent(project)}/status`),
  dockerComposeLogs: (project: string, service = "") => request<{ lines: string[]; total: number; truncated: boolean }>(`/api/modules/docker/compose/${encodeURIComponent(project)}/logs?tail=500&service=${encodeURIComponent(service)}`),
  dockerApps: (search = "") => request<{ items: DockerApp[]; total: number }>(`/api/modules/docker/apps?search=${encodeURIComponent(search)}`),
  installDockerApp: (id: string, payload: DockerAppInstall) => request<{ job: ModuleJob }>(`/api/modules/docker/apps/${encodeURIComponent(id)}/install`, { method: "POST", body: JSON.stringify(payload) }),
  dockerAppAction: (id: string, action: "start" | "stop" | "restart" | "update" | "remove", payload: DockerAppAction = {}) => request<{ job: ModuleJob }>(`/api/modules/docker/apps/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify(payload) }),
  dockerRegistries: () => request<{ items: DockerRegistry[] }>("/api/modules/docker/registries"),
  dockerRegistrySources: () => request<DockerRegistrySource[]>("/api/modules/docker/registries/sources"),
  dockerRegistryCatalog: (params: { registry_id: string; query: string; page?: number; page_size?: number; official?: "all" | "official" | "unofficial"; sort?: "relevance" | "name" | "stars"; direction?: "asc" | "desc" }) => {
    const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => value !== undefined && query.set(key, String(value)));
    return request<DockerRegistryCatalogResult>(`/api/modules/docker/registries/catalog?${query}`);
  },
  dockerRegistryTags: (registryId: string, repositoryName: string, page = 1, pageSize = 100) => {
    const query = new URLSearchParams({ registry_id: registryId, repository_name: repositoryName, page: String(page), page_size: String(pageSize) });
    return request<DockerRegistryTagsResult>(`/api/modules/docker/registries/tags?${query}`);
  },
  saveDockerRegistry: (payload: DockerRegistrySave, id = "") => request<{ registry: DockerRegistry; job: ModuleJob }>(id ? `/api/modules/docker/registries/${encodeURIComponent(id)}` : "/api/modules/docker/registries", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  testDockerRegistry: (id: string) => request<{ job: ModuleJob }>(`/api/modules/docker/registries/${encodeURIComponent(id)}/test`, { method: "POST", body: "{}" }),
  logoutDockerRegistry: (id: string) => request<{ job: ModuleJob }>(`/api/modules/docker/registries/${encodeURIComponent(id)}/logout`, { method: "POST", body: "{}" }),
  deleteDockerRegistry: (id: string, confirmation: string) => request<{ ok: boolean }>(`/api/modules/docker/registries/${encodeURIComponent(id)}?confirmation=${encodeURIComponent(confirmation)}`, { method: "DELETE", body: "{}" }),
  dockerBackups: () => request<{ configuration: ModuleBackup[]; artifacts: DockerArtifact[] }>("/api/modules/docker/backups"),
  restoreDockerBackup: (id: string, payload: DockerBackupRestore) => request<{ job: ModuleJob }>(`/api/modules/docker/backups/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify(payload) }),
  dockerDiagnostics: () => request<{ generated_at: number; status: ModuleStatus; checks: ModuleDiagnostic[]; config: Record<string, unknown>; prune: Record<string, unknown> }>("/api/modules/docker/diagnostics"),
  dockerEvents: () => request<{ items: Array<Record<string, unknown>>; total: number }>("/api/modules/docker/events?since_seconds=3600&limit=500"),
  dockerPrune: (payload: DockerPrune) => request<{ job: ModuleJob }>("/api/modules/docker/prune", { method: "POST", body: JSON.stringify(payload) }),
  dockerPrunePlan: (resources: DockerPrune["resources"]) => request<DockerPrunePlan>(`/api/modules/docker/prune/plan?resources=${encodeURIComponent(resources.join(","))}`)
} as const;
