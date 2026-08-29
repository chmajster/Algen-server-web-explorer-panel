import { request } from "../../../core/api/transport";
import type { OsRepository, OsRepositoryAssignment, OsRepositoryChannel, OsRepositoryDashboard, OsRepositoryJob, OsRepositoryKey, OsRepositoryPackage, OsRepositoryPage, OsRepositorySnapshot } from "../../../core/api/contracts";

export type OfflineRepositorySettings = {
  air_gapped_mode: boolean;
  keep_last: number;
  delete_after_days: number;
  keep_production: boolean;
  keep_signed: boolean;
};

export type OfflineRepositoryDashboard = {
  repositories: number;
  targets: number;
  packages: number;
  snapshots: number;
  bundles: number;
  air_gapped_mode: boolean;
  storage: Record<string, number>;
  last_export: Record<string, unknown> | null;
};

export type OfflineRepositoryTarget = {
  id: string;
  name: string;
  repository_id: string;
  snapshot_id: string | null;
  channel: string | null;
  distribution: string;
  distribution_version: string;
  architecture: string;
  package_names: string[];
  include_dependencies: boolean;
  signing_key_id: string | null;
  host_group_id: string | null;
};

export type OfflineRepositoryBundle = {
  id: string;
  repository_id: string;
  snapshot_id: string | null;
  base_snapshot_id: string | null;
  target_id: string | null;
  bundle_type: "full" | "selected" | "delta";
  status: "creating" | "ready" | "verified" | "imported" | "failed" | "deleted";
  architecture: string;
  package_count: number;
  size_bytes: number;
  sha256: string;
  filename: string;
  signed: boolean;
  signature_status: string;
  signing_fingerprint: string;
  pinned: boolean;
  error: string;
  created_at: number;
};

export const osRepositoriesClient = {
  osRepositoriesDashboard: () => request<OsRepositoryDashboard>("/api/modules/os-repositories/dashboard"),
  osRepositories: (search = "") => request<OsRepositoryPage<OsRepository>>(`/api/modules/os-repositories/repositories?search=${encodeURIComponent(search)}`),
  osRepository: (id: string) => request<OsRepository & { filters: Array<{ active: boolean; name: string; rules: Record<string, unknown>; version: number }> }>(`/api/modules/os-repositories/repositories/${encodeURIComponent(id)}`),
  saveOsRepository: (payload: Record<string, unknown>, id = "") => request<OsRepository>(id ? `/api/modules/os-repositories/repositories/${encodeURIComponent(id)}` : "/api/modules/os-repositories/repositories", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  planOsRepository: (payload: Record<string, unknown>, id = "00000000000000000000000000000000") => request<Record<string, unknown>>(`/api/modules/os-repositories/repositories/${encodeURIComponent(id)}/plan`, { method: "POST", body: JSON.stringify(payload) }),
  deleteOsRepository: (id: string) => request<{ ok: boolean }>(`/api/modules/os-repositories/repositories/${encodeURIComponent(id)}`, { method: "DELETE" }),
  syncOsRepository: (id: string) => request<OsRepositoryJob>(`/api/modules/os-repositories/repositories/${encodeURIComponent(id)}/sync`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  previewOsRepositoryFilter: (id: string, payload: Record<string, unknown>) => request<Record<string, unknown>>(`/api/modules/os-repositories/repositories/${encodeURIComponent(id)}/filters/preview`, { method: "POST", body: JSON.stringify(payload) }),
  saveOsRepositoryFilter: (id: string, payload: Record<string, unknown>) => request<Record<string, unknown>>(`/api/modules/os-repositories/repositories/${encodeURIComponent(id)}/filters`, { method: "POST", body: JSON.stringify(payload) }),
  osRepositoryPackages: (search = "", repositoryId = "") => request<OsRepositoryPage<OsRepositoryPackage>>(`/api/modules/os-repositories/packages?search=${encodeURIComponent(search)}&repository_id=${encodeURIComponent(repositoryId)}`),
  uploadOsRepositoryPackage: (repositoryId: string, file: File) => { const body = new FormData(); body.append("file", file); return request<OsRepositoryPackage>(`/api/modules/os-repositories/packages/upload?repository_id=${encodeURIComponent(repositoryId)}`, { method: "POST", body }); },
  osRepositorySnapshots: (repositoryId = "") => request<OsRepositoryPage<OsRepositorySnapshot>>(`/api/modules/os-repositories/snapshots?repository_id=${encodeURIComponent(repositoryId)}`),
  createOsRepositorySnapshot: (repositoryId: string, name = "", description = "") => request<OsRepositorySnapshot>(`/api/modules/os-repositories/repositories/${encodeURIComponent(repositoryId)}/snapshots`, { method: "POST", body: JSON.stringify({ name, description }) }),
  osRepositoryChannels: () => request<OsRepositoryChannel[]>("/api/modules/os-repositories/channels"),
  promoteOsRepositoryChannel: (channelId: string, snapshotId: string, production = false) => request<OsRepositoryChannel>(`/api/modules/os-repositories/channels/${encodeURIComponent(channelId)}/promote`, { method: "POST", body: JSON.stringify({ snapshot_id: snapshotId, confirm: true, confirmation_text: production ? "Production" : "" }) }),
  osRepositoryChannelPlan: (channelId: string, snapshotId: string) => request<Record<string, unknown>>(`/api/modules/os-repositories/channels/${encodeURIComponent(channelId)}/plan?snapshot_id=${encodeURIComponent(snapshotId)}`),
  rollbackOsRepositoryChannel: (channelId: string, production = false) => request<OsRepositoryChannel>(`/api/modules/os-repositories/channels/${encodeURIComponent(channelId)}/rollback`, { method: "POST", body: JSON.stringify({ confirm: true, confirmation_text: production ? "Production" : "" }) }),
  osRepositoryJobs: (status = "") => request<OsRepositoryPage<OsRepositoryJob>>(`/api/modules/os-repositories/jobs?status=${encodeURIComponent(status)}`),
  osRepositoryJob: (id: string) => request<OsRepositoryJob & { logs: Array<{ id: number; stream: string; line: string; created_at: number }> }>(`/api/modules/os-repositories/jobs/${encodeURIComponent(id)}`),
  cancelOsRepositoryJob: (id: string) => request<OsRepositoryJob>(`/api/modules/os-repositories/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  retryOsRepositoryJob: (id: string) => request<OsRepositoryJob>(`/api/modules/os-repositories/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: "{}" }),
  osRepositoryBuilds: () => request<Array<{ id: string; repository_id: string; format: string; status: string; error: string; created_at: number }>>("/api/modules/os-repositories/builds"),
  buildOsRepositoryPackage: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/api/modules/os-repositories/builds", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  osRepositoryKeys: () => request<OsRepositoryKey[]>("/api/modules/os-repositories/keys"),
  saveOsRepositoryKey: (payload: Record<string, unknown>) => request<OsRepositoryKey>("/api/modules/os-repositories/keys", { method: "POST", body: JSON.stringify(payload) }),
  generateOsRepositoryKey: (payload: Record<string, unknown>) => request<OsRepositoryKey>("/api/modules/os-repositories/keys/generate", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  deleteOsRepositoryKey: (id: string) => request<{ ok: boolean }>(`/api/modules/os-repositories/keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  osRepositoryAssignments: () => request<OsRepositoryAssignment[]>("/api/modules/os-repositories/host-assignments"),
  saveOsRepositoryAssignment: (payload: Record<string, unknown>) => request<OsRepositoryAssignment>("/api/modules/os-repositories/host-assignments", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  deleteOsRepositoryAssignment: (id: string) => request<{ ok: boolean }>(`/api/modules/os-repositories/host-assignments/${encodeURIComponent(id)}`, { method: "DELETE" }),
  osRepositoryAssignmentConfiguration: (id: string) => request<{ format: string; filename: string; content: string; public_key_url: string }>(`/api/modules/os-repositories/host-assignments/${encodeURIComponent(id)}/configuration`),
  osRepositoryHistory: () => request<Array<{ id: number; actor: string; action: string; target: string; details: Record<string, unknown>; created_at: number }>>("/api/modules/os-repositories/history"),
  osRepositorySettings: () => request<{ listen_address: string; port: number; public_base_url: string; upload_limit_mb: number; max_parallel_syncs: number }>("/api/modules/os-repositories/settings"),
  saveOsRepositorySettings: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/api/modules/os-repositories/settings", { method: "PUT", body: JSON.stringify(payload) }),
  osRepositoryDiagnostics: () => request<{ checks: Array<{ id: string; status: string; message: string }> }>("/api/modules/os-repositories/diagnostics"),

  offlineRepositoryDashboard: () => request<OfflineRepositoryDashboard>("/api/modules/os-repositories/offline/dashboard"),
  offlineRepositorySettings: () => request<OfflineRepositorySettings>("/api/modules/os-repositories/offline/settings"),
  saveOfflineRepositorySettings: (payload: OfflineRepositorySettings) => request<OfflineRepositorySettings>("/api/modules/os-repositories/offline/settings", { method: "PUT", body: JSON.stringify(payload) }),
  offlineRepositoryTargets: () => request<OfflineRepositoryTarget[]>("/api/modules/os-repositories/offline/targets"),
  saveOfflineRepositoryTarget: (payload: Record<string, unknown>, id = "") => request<OfflineRepositoryTarget>(id ? `/api/modules/os-repositories/offline/targets/${encodeURIComponent(id)}` : "/api/modules/os-repositories/offline/targets", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  deleteOfflineRepositoryTarget: (id: string) => request<{ ok: boolean }>(`/api/modules/os-repositories/offline/targets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  planOfflineRepositoryExport: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/api/modules/os-repositories/offline/exports/plan", { method: "POST", body: JSON.stringify(payload) }),
  createOfflineRepositoryExport: (payload: Record<string, unknown>) => request<OsRepositoryJob>("/api/modules/os-repositories/offline/exports", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  offlineRepositoryBundles: () => request<OsRepositoryPage<OfflineRepositoryBundle>>("/api/modules/os-repositories/offline/bundles"),
  pinOfflineRepositoryBundle: (id: string, pinned: boolean) => request<OfflineRepositoryBundle>(`/api/modules/os-repositories/offline/bundles/${encodeURIComponent(id)}/pin`, { method: "PUT", body: JSON.stringify({ pinned, confirm: true }) }),
  deleteOfflineRepositoryBundle: (id: string, force = false) => request<{ ok: boolean }>(`/api/modules/os-repositories/offline/bundles/${encodeURIComponent(id)}?force=${force ? "true" : "false"}`, { method: "DELETE" }),
  stagedOfflineRepositoryBundles: () => request<{ items: Array<{ id: string; filename: string; size_bytes: number; modified_at: number }> }>("/api/modules/os-repositories/offline/imports/staged"),
  uploadOfflineRepositoryBundle: (file: File) => { const body = new FormData(); body.append("file", file); return request<{ id: string; filename: string; size_bytes: number; modified_at: number }>("/api/modules/os-repositories/offline/imports/upload", { method: "POST", body }); },
  inspectOfflineRepositoryBundle: (stagedId: string) => request<Record<string, unknown>>(`/api/modules/os-repositories/offline/imports/${encodeURIComponent(stagedId)}/inspect`),
  verifyOfflineRepositoryBundle: (stagedId: string, repositoryId: string) => request<OsRepositoryJob>(`/api/modules/os-repositories/offline/imports/${encodeURIComponent(stagedId)}/verify?repository_id=${encodeURIComponent(repositoryId)}`, { method: "POST", body: "{}" }),
  importOfflineRepositoryBundle: (stagedId: string, payload: Record<string, unknown>) => request<OsRepositoryJob>(`/api/modules/os-repositories/offline/imports/${encodeURIComponent(stagedId)}`, { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  offlineRepositoryDeltaPlan: (baseSnapshotId: string, targetSnapshotId: string, architecture: string) => request<Record<string, unknown>>(`/api/modules/os-repositories/offline/delta/plan?base_snapshot_id=${encodeURIComponent(baseSnapshotId)}&target_snapshot_id=${encodeURIComponent(targetSnapshotId)}&architecture=${encodeURIComponent(architecture)}`),
  freezeOfflineRepositorySnapshot: (snapshotId: string) => request<Record<string, unknown>>(`/api/modules/os-repositories/offline/snapshots/${encodeURIComponent(snapshotId)}/freeze`, { method: "POST", body: "{}" }),
  offlineRepositoryStorage: () => request<Record<string, number>>("/api/modules/os-repositories/offline/storage"),
  offlineRepositoryJobs: (status = "") => request<OsRepositoryPage<OsRepositoryJob>>(`/api/modules/os-repositories/offline/jobs?status=${encodeURIComponent(status)}`),
  offlineRepositoryJob: (id: string) => request<OsRepositoryJob & { logs: Array<{ id: number; stream: string; line: string; created_at: number }> }>(`/api/modules/os-repositories/offline/jobs/${encodeURIComponent(id)}`),
  cancelOfflineRepositoryJob: (id: string) => request<OsRepositoryJob>(`/api/modules/os-repositories/offline/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" }),
  retryOfflineRepositoryJob: (id: string) => request<OsRepositoryJob>(`/api/modules/os-repositories/offline/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: "{}" })
} as const;
