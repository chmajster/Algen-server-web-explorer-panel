import { request } from "../../../core/api/transport";
import {
  asArray,
  asBoolean,
  asFiniteNumber,
  asOptionalFiniteNumber,
  asRecord,
  asString,
  asStringArray,
} from "../../../core/api/runtimeGuards";
import type {
  AutoUpdateSettings,
  UpdateBlocker,
  UpdateCompletionNotice,
  UpdateProgress,
  UpdateStart,
  UpdateStatus,
  UpdateStep,
} from "../../../core/api/contracts";

function nullableNumber(value: unknown): number | null {
  return asOptionalFiniteNumber(value);
}

function normalizeStep(value: unknown): UpdateStep {
  const source = asRecord(value);
  const status = asString(source.status, "pending");
  return {
    id: asString(source.id),
    status: (["pending", "running", "success", "failed", "skipped"].includes(status)
      ? status
      : "pending") as UpdateStep["status"],
    message: asString(source.message),
    started_at: nullableNumber(source.started_at),
    finished_at: nullableNumber(source.finished_at),
    error: source.error === null || source.error === undefined
      ? null
      : asString(source.error),
  };
}

function normalizeBlocker(value: unknown): UpdateBlocker {
  const source = asRecord(value);
  const status = asString(source.status, "queued");
  return {
    id: asString(source.id),
    type: asString(source.type),
    status: (status === "running" ? "running" : "queued"),
    started_at: nullableNumber(source.started_at),
    progress: nullableNumber(source.progress),
    description: asString(source.description),
  };
}

function normalizeProgress(value: unknown): UpdateProgress {
  const source = asRecord(value);
  const state = asString(source.state, "idle");
  const normalizedState = ([
    "idle",
    "waiting",
    "preparing",
    "running",
    "completed",
    "failed",
  ].includes(state) ? state : "idle") as UpdateProgress["state"];

  const progress = nullableNumber(source.progress);
  return {
    ...source,
    id: source.id === null || source.id === undefined
      ? null
      : asString(source.id),
    state: normalizedState,
    phase: asString(source.phase, normalizedState),
    failed_phase: source.failed_phase === null || source.failed_phase === undefined
      ? null
      : asString(source.failed_phase),
    running: asBoolean(
      source.running,
      ["waiting", "preparing", "running"].includes(normalizedState),
    ),
    progress: progress === null
      ? null
      : Math.max(0, Math.min(100, progress)),
    pid: nullableNumber(source.pid),
    unit: source.unit === null || source.unit === undefined
      ? null
      : asString(source.unit),
    exit_code: nullableNumber(source.exit_code),
    requested_at: nullableNumber(source.requested_at),
    started_at: nullableNumber(source.started_at),
    finished_at: nullableNumber(source.finished_at),
    previous_version: source.previous_version === null || source.previous_version === undefined
      ? null
      : asString(source.previous_version),
    target_version: source.target_version === null || source.target_version === undefined
      ? null
      : asString(source.target_version),
    current_version: source.current_version === null || source.current_version === undefined
      ? null
      : asString(source.current_version),
    commit_revision: source.commit_revision === null || source.commit_revision === undefined
      ? null
      : asString(source.commit_revision),
    message: asString(source.message),
    steps: asArray(source.steps).map(normalizeStep),
    trigger: asString(source.trigger) === "automatic" ? "automatic" : "manual",
    updated_at: nullableNumber(source.updated_at),
    active_count: Math.max(0, Math.trunc(asFiniteNumber(source.active_count, 0))),
    blockers: asArray(source.blockers).map(normalizeBlocker),
    log: asString(source.log),
    lines: asStringArray(source.lines),
  } as UpdateProgress;
}

function normalizeStart(value: unknown): UpdateStart {
  const source = asRecord(value);
  return {
    ...normalizeProgress(source),
    ok: asBoolean(source.ok),
    updated: asBoolean(source.updated),
    skipped: asBoolean(source.skipped),
    reason: asString(source.reason),
  };
}

function normalizeStatus(value: unknown): UpdateStatus {
  const source = asRecord(value);
  return {
    ...source,
    branch: asString(source.branch),
    local: asString(source.local, "unknown"),
    remote: asString(source.remote),
    installed_version: source.installed_version === null || source.installed_version === undefined
      ? null
      : asString(source.installed_version),
    available_version: source.available_version === null || source.available_version === undefined
      ? null
      : asString(source.available_version),
    update_available: asBoolean(source.update_available),
    available: asBoolean(source.available, true),
    error: asString(source.error),
    source: asString(source.source),
    source_url: asString(source.source_url),
    released_at: nullableNumber(source.released_at),
    checked_at: nullableNumber(source.checked_at) ?? undefined,
  };
}

function normalizeAutoUpdate(value: unknown): AutoUpdateSettings {
  const source = asRecord(value);
  return {
    check_enabled: asBoolean(source.check_enabled),
    enabled: asBoolean(source.enabled),
    interval_hours: Math.max(1, Math.trunc(asFiniteNumber(source.interval_hours, 12))),
    update_config: asBoolean(source.update_config),
    last_checked: nullableNumber(source.last_checked),
    last_run: nullableNumber(source.last_run),
    last_error: asString(source.last_error),
    last_pid: nullableNumber(source.last_pid),
    next_check: nullableNumber(source.next_check),
  };
}

function normalizeCompletion(value: unknown): UpdateCompletionNotice | null {
  if (value === null || value === undefined) return null;
  const source = asRecord(value);
  const id = asString(source.id);
  if (!id) return null;
  return {
    id,
    previous_version: source.previous_version === null || source.previous_version === undefined
      ? null
      : asString(source.previous_version),
    current_version: source.current_version === null || source.current_version === undefined
      ? null
      : asString(source.current_version),
    finished_at: nullableNumber(source.finished_at),
    commit_revision: source.commit_revision === null || source.commit_revision === undefined
      ? null
      : asString(source.commit_revision),
    commit_date: nullableNumber(source.commit_date),
  };
}

export const updatesClient = {
  checkUpdates: async () => normalizeStatus(
    await request<unknown>("/api/admin/system/updates/check"),
  ),

  updateProgress: async () => normalizeProgress(
    await request<unknown>("/api/admin/system/updates/progress"),
  ),

  updatePublicProgress: async () => normalizeProgress(
    await request<unknown>("/api/system/update-status"),
  ),

  downloadUpdates: async (update_config = false) => normalizeStart(
    await request<unknown>("/api/admin/system/updates/download", {
      method: "POST",
      body: JSON.stringify({ update_config }),
    }),
  ),

  autoUpdate: async () => normalizeAutoUpdate(
    await request<unknown>("/api/admin/system/updates/auto"),
  ),

  saveAutoUpdate: async (payload: {
    check_enabled: boolean;
    enabled: boolean;
    interval_hours: number;
    update_config: boolean;
  }) => normalizeAutoUpdate(
    await request<unknown>("/api/admin/system/updates/auto", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  ),

  runAutoUpdate: async (update_config = false) => normalizeStart(
    await request<unknown>("/api/admin/system/updates/auto/run", {
      method: "POST",
      body: JSON.stringify({ update_config }),
    }),
  ),

  updateCompletion: async () => {
    const value = asRecord(
      await request<unknown>("/api/admin/system/updates/completion"),
    );
    return { notice: normalizeCompletion(value.notice) };
  },

  acknowledgeUpdateCompletion: (
    updateId: string,
  ) => request<{ ok: boolean; stale: boolean }>(
    "/api/admin/system/updates/completion/acknowledge",
    {
      method: "POST",
      body: JSON.stringify({ update_id: updateId }),
    },
  ),
} as const;
