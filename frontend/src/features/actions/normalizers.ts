import type {
  AnsibleExecution,
  AnsibleScan,
  AppJob,
  HostsManagerOperation,
  NetworkMount,
  NetworkTransaction,
  Task,
  UpdateProgress,
} from "../../api";
import type { Translate } from "../../app/types";
import type {
  BackgroundAction,
  BackgroundActionSource,
  BackgroundActionStatus,
} from "./types";

const ACTIVE_EQUIVALENTS = new Set([
  "queued",
  "pending",
  "pending_confirmation",
  "waiting_for_confirmation",
  "waiting",
  "starting",
  "installing",
]);
const RUNNING_EQUIVALENTS = new Set([
  "running",
  "in_progress",
  "processing",
  "executing",
  "rollback_pending",
  "rollback_started",
  "migrating",
]);
const PAUSED_EQUIVALENTS = new Set([
  "paused",
  "cancellation_requested",
  "cancelling",
]);
const COMPLETED_EQUIVALENTS = new Set([
  "completed",
  "success",
  "succeeded",
  "confirmed",
  "rolled_back",
]);
const FAILED_EQUIVALENTS = new Set([
  "failed",
  "error",
  "unreachable",
]);
const CANCELLED_EQUIVALENTS = new Set([
  "cancelled",
  "canceled",
]);

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function safeStringArray(value: unknown): string[] {
  return safeArray(value)
    .filter((item) => ["string", "number", "boolean"].includes(typeof item))
    .map(String);
}

function safeRecord(value: unknown): Record<string, unknown> {
  return value !== null &&
    typeof value === "object" &&
    !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function safeString(value: unknown, fallback = ""): string {
  return typeof value === "string"
    ? value
    : value === null || value === undefined
      ? fallback
      : String(value);
}

export function normalizeStatus(
  value: string,
  cancellationRequested = false,
): BackgroundActionStatus {
  const status = safeString(value).toLowerCase();
  if (cancellationRequested || PAUSED_EQUIVALENTS.has(status)) {
    return "paused";
  }
  if (RUNNING_EQUIVALENTS.has(status)) return "running";
  if (ACTIVE_EQUIVALENTS.has(status)) return "queued";
  if (COMPLETED_EQUIVALENTS.has(status)) return "completed";
  if (FAILED_EQUIVALENTS.has(status)) return "failed";
  if (CANCELLED_EQUIVALENTS.has(status)) return "cancelled";
  return "queued";
}

function safeProgress(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return Math.max(0, Math.min(100, value));
}

function actionKey(source: BackgroundActionSource, id: string) {
  return `${source}:${id}`;
}

function moduleSource(moduleId: string): BackgroundActionSource {
  if (moduleId === "docker") return "docker";
  if (moduleId === "ansible-controller") return "ansible";
  if (moduleId === "hosts-manager") return "hosts";
  if (moduleId === "linux-updates") return "system";
  return "module";
}

function translatedOperation(t: Translate, action: string) {
  const safeAction = safeString(action, "unknown");
  const key = `actions.operation.${safeAction}`;
  const translated = t(key);
  return translated === key
    ? safeAction.replace(/_/g, " ")
    : translated;
}

export function normalizeTransfer(
  task: Task,
  t: Translate,
): BackgroundAction {
  const source = task.type === "upload" ? "upload" : "transfer";
  const sourcePaths = safeStringArray(task.source_paths);
  const sourcePath = sourcePaths[sourcePaths.length - 1] || "";
  const sourceParts = sourcePath.split("/");
  const errors = safeStringArray(task.errors);
  const name =
    safeString(task.current_file) ||
    sourceParts[sourceParts.length - 1] ||
    safeString(task.destination_path);

  return {
    key: actionKey(source, safeString(task.id)),
    id: safeString(task.id),
    source,
    title: t(
      source === "upload"
        ? "actions.source.upload"
        : "actions.source.transfer",
    ),
    subtitle: name,
    status: normalizeStatus(task.status),
    progress: safeProgress(task.progress_percent ?? task.progress),
    currentStep: safeString(task.current_file) || undefined,
    error:
      safeString(task.error_message) ||
      errors[0] ||
      undefined,
    createdAt: Number(task.created_at || 0) * 1000,
    updatedAt:
      Math.max(
        Number(task.started_at || 0),
        Number(task.paused_at || 0),
        Number(task.finished_at || 0),
      ) *
        1000 ||
      undefined,
    finishedAt: task.finished_at
      ? Number(task.finished_at) * 1000
      : undefined,
    cancellable: ["queued", "running", "paused"].includes(task.status),
    retryable: ["failed", "cancelled"].includes(task.status),
    target: {
      app: "transfers",
      jobId: safeString(task.id),
      entityId: safeString(task.id),
      section: "active",
      detailType: "transfer",
    },
  };
}

export function normalizeAppJob(
  job: AppJob,
  moduleNames: Map<string, string>,
  t: Translate,
): BackgroundAction {
  const moduleId = safeString(job.module_id);
  const source = moduleSource(moduleId);
  const name = moduleNames.get(moduleId) || moduleId;
  const id = safeString(job.id);

  return {
    key: actionKey(source, id),
    id,
    source,
    title: translatedOperation(
      t,
      safeString(job.operation || job.action),
    ),
    subtitle: name,
    status: normalizeStatus(
      job.status,
      Boolean(job.cancellation_requested),
    ),
    progress: safeProgress(job.progress),
    currentStep:
      safeString(job.current_step) ||
      safeString(job.stage) ||
      undefined,
    error: safeString(job.error) || undefined,
    createdAt: Number(job.created_at || 0) * 1000,
    updatedAt: job.finished_at
      ? Number(job.finished_at) * 1000
      : undefined,
    finishedAt: job.finished_at
      ? Number(job.finished_at) * 1000
      : undefined,
    cancellable:
      job.cancellable !== false &&
      ["queued", "running"].includes(job.status),
    retryable: ["failed", "cancelled"].includes(job.status),
    target: {
      app: "operation-progress",
      moduleId,
      jobId: id,
      entityId: id,
      section: name,
      detailType: "package-job",
    },
  };
}

export function normalizeMountJob(
  mount: NetworkMount,
  job: NetworkMount["jobs"][number],
  t: Translate,
): BackgroundAction {
  const createdAt =
    Number(job.created_at || mount.last_operation_at || Date.now() / 1000) *
    1000;
  const finishedAt = job.finished_at
    ? Number(job.finished_at) * 1000
    : undefined;
  const id = safeString(job.id);

  return {
    key: actionKey("mount", id),
    id,
    source: "mount",
    title: translatedOperation(t, safeString(job.action)),
    subtitle: safeString(mount.name),
    status: normalizeStatus(job.status),
    currentStep: t("actions.source.mount"),
    error: safeString(job.error) || undefined,
    createdAt,
    updatedAt: finishedAt || createdAt,
    finishedAt: ["completed", "failed", "cancelled"].includes(job.status)
      ? finishedAt || createdAt
      : undefined,
    target: {
      app: "settings",
      initialPath: "networkResources",
      entityId: safeString(mount.id),
      jobId: id,
      section: "networkResources",
      detailType: "mount-job",
    },
  };
}

export function normalizeAnsibleExecution(
  item: AnsibleExecution,
  t: Translate,
): BackgroundAction {
  const hostIds = safeStringArray(item.host_ids);
  const id = safeString(item.id);

  return {
    key: actionKey("ansible", id),
    id,
    relatedJobId: safeString(item.package_job_id) || undefined,
    source: "ansible",
    title: t("actions.ansibleExecution"),
    subtitle:
      safeString(item.template_id) ||
      hostIds.join(", ") ||
      t("ansible.name"),
    status: normalizeStatus(item.status),
    currentStep: safeString(item.stage),
    error: safeString(item.stderr) || undefined,
    createdAt: Number(item.created_at || 0) * 1000,
    updatedAt:
      Number(
        item.finished_at ||
          item.started_at ||
          item.created_at ||
          0,
      ) * 1000,
    finishedAt: item.finished_at
      ? Number(item.finished_at) * 1000
      : undefined,
    cancellable: ["queued", "running"].includes(item.status),
    retryable: ["failed", "cancelled"].includes(item.status),
    target: {
      app: "ansible",
      moduleId: "ansible-controller",
      entityId: id,
      jobId: safeString(item.package_job_id) || id,
      section: "jobs",
      detailType: "ansible-job",
    },
  };
}

export function normalizeAnsibleScan(
  item: AnsibleScan,
  t: Translate,
): BackgroundAction {
  const request = safeRecord(item.request);
  const id = safeString(item.id);

  return {
    key: actionKey("ansible", `scan-${id}`),
    id,
    relatedJobId: safeString(item.package_job_id) || undefined,
    source: "ansible",
    title: t("actions.ansibleScan"),
    subtitle: safeString(
      request.cidr || request.target,
      t("ansible.discovery.title"),
    ),
    status: normalizeStatus(item.status),
    progress: safeProgress(item.progress),
    currentStep: t("ansible.discovery.title"),
    error: safeString(item.error) || undefined,
    createdAt: Number(item.created_at || 0) * 1000,
    updatedAt: Number(item.created_at || 0) * 1000,
    target: {
      app: "ansible",
      moduleId: "ansible-controller",
      entityId: id,
      jobId: safeString(item.package_job_id) || undefined,
      section: "discovery",
      detailType: "ansible-scan",
    },
  };
}

export function normalizeHostsOperation(
  item: HostsManagerOperation,
  t: Translate,
): BackgroundAction {
  const details = safeRecord(item.details);
  const packageJobId =
    safeString(item.package_job_id) ||
    safeString(details.package_job_id) ||
    undefined;
  const id = safeString(item.id);

  return {
    key: actionKey("hosts", id),
    id,
    relatedJobId: packageJobId,
    source: "hosts",
    title: translatedOperation(t, safeString(item.capability_id)),
    subtitle: safeString(item.host_id) || t("hosts.name"),
    status: normalizeStatus(item.status),
    progress: safeProgress(item.progress),
    currentStep: safeString(item.stage),
    error: safeString(item.error) || undefined,
    createdAt: Number(item.created_at || 0) * 1000,
    updatedAt: Number(item.updated_at || item.created_at || 0) * 1000,
    finishedAt: ["completed", "failed", "cancelled"].includes(item.status)
      ? Number(item.updated_at || item.created_at || Date.now() / 1000) *
        1000
      : undefined,
    cancellable: ["queued", "running"].includes(item.status),
    target: {
      app: "hosts",
      moduleId: "hosts-manager",
      entityId: id,
      jobId: packageJobId,
      section: "audit",
      detailType: "hosts-operation",
    },
  };
}

export function normalizeNetworkTransaction(
  item: NetworkTransaction,
  t: Translate,
): BackgroundAction {
  const status = safeString(item.status || item.state, "queued");
  const id = safeString(item.id);

  return {
    key: actionKey("network", id),
    id,
    source: "network",
    title: t("actions.networkChange"),
    subtitle: safeString(item.target),
    status: normalizeStatus(status),
    currentStep: t(`actions.network.${status}`),
    createdAt:
      Number(item.created_at || item.started_at || 0) * 1000,
    updatedAt:
      Number(
        item.current_server_time ||
          item.server_time ||
          item.started_at ||
          0,
      ) * 1000,
    finishedAt: ["confirmed", "rolled_back", "failed"].includes(status)
      ? Number(
          item.current_server_time ||
            item.server_time ||
            Date.now() / 1000,
        ) * 1000
      : undefined,
    target: {
      app: "settings",
      initialPath: "network",
      entityId: id,
      section: "network",
      detailType: "network-transaction",
    },
  };
}

export function normalizeSystemUpdate(
  item: UpdateProgress,
  t: Translate,
): BackgroundAction | null {
  if (!item.started_at) return null;
  const lines = safeStringArray(item.lines);
  const lastLine = lines[lines.length - 1];
  const id = String(item.pid || item.started_at);

  return {
    key: actionKey("system", `webnas-update-${id}`),
    id,
    source: "system",
    title: t("actions.systemUpdate"),
    subtitle: "WebNAS",
    status: item.running
      ? "running"
      : item.exit_code === 0
        ? "completed"
        : item.exit_code === null
          ? "queued"
          : "failed",
    currentStep: lastLine || undefined,
    error:
      !item.running && item.exit_code !== 0
        ? lastLine || safeString(item.log) || undefined
        : undefined,
    createdAt: Number(item.started_at) * 1000,
    updatedAt:
      Number(item.finished_at || item.started_at) * 1000,
    finishedAt: item.finished_at
      ? Number(item.finished_at) * 1000
      : undefined,
    target: {
      app: "settings",
      initialPath: "updates",
      entityId: id,
      section: "updates",
      detailType: "system-update",
    },
  };
}

const STATUS_PRIORITY: Record<BackgroundActionStatus, number> = {
  failed: 0,
  running: 1,
  paused: 2,
  queued: 3,
  completed: 4,
  cancelled: 5,
};

export function dedupeAndSortActions(
  actions: BackgroundAction[],
) {
  const safeActions = safeArray<BackgroundAction>(actions);
  const specializedJobIds = new Set(
    safeActions
      .filter((action) =>
        ["ansible", "hosts"].includes(action.source),
      )
      .map((action) => action.relatedJobId)
      .filter((id): id is string => Boolean(id)),
  );

  const unique = new Map<string, BackgroundAction>();
  for (const action of safeActions) {
    if (
      action.target.detailType === "package-job" &&
      specializedJobIds.has(action.id)
    ) {
      continue;
    }
    const previous = unique.get(action.key);
    if (
      !previous ||
      (action.updatedAt || action.createdAt) >=
        (previous.updatedAt || previous.createdAt)
    ) {
      unique.set(action.key, action);
    }
  }

  return [...unique.values()].sort(
    (left, right) =>
      STATUS_PRIORITY[left.status] -
        STATUS_PRIORITY[right.status] ||
      (right.updatedAt || right.createdAt) -
        (left.updatedAt || left.createdAt),
  );
}
