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
const PAUSED_EQUIVALENTS = new Set(["paused", "cancellation_requested", "cancelling"]);
const COMPLETED_EQUIVALENTS = new Set(["completed", "success", "succeeded", "confirmed", "rolled_back"]);
const FAILED_EQUIVALENTS = new Set(["failed", "error", "unreachable"]);
const CANCELLED_EQUIVALENTS = new Set(["cancelled", "canceled"]);

export function normalizeStatus(value: string, cancellationRequested = false): BackgroundActionStatus {
  const status = value.toLowerCase();
  if (cancellationRequested || PAUSED_EQUIVALENTS.has(status)) return "paused";
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
  const key = `actions.operation.${action}`;
  const translated = t(key);
  return translated === key ? action.replaceAll("_", " ") : translated;
}

export function normalizeTransfer(task: Task, t: Translate): BackgroundAction {
  const source = task.type === "upload" ? "upload" : "transfer";
  const name = task.current_file || task.source_paths.at(-1)?.split("/").at(-1) || task.destination_path;
  return {
    key: actionKey(source, task.id),
    id: task.id,
    source,
    title: t(source === "upload" ? "actions.source.upload" : "actions.source.transfer"),
    subtitle: name,
    status: normalizeStatus(task.status),
    progress: safeProgress(task.progress_percent ?? task.progress),
    currentStep: task.current_file || undefined,
    error: task.error_message || task.errors?.[0] || undefined,
    createdAt: task.created_at * 1000,
    updatedAt: Math.max(task.started_at || 0, task.paused_at || 0, task.finished_at || 0) * 1000 || undefined,
    finishedAt: task.finished_at ? task.finished_at * 1000 : undefined,
    cancellable: ["queued", "running", "paused"].includes(task.status),
    retryable: ["failed", "cancelled"].includes(task.status),
    target: {
      app: "transfers",
      jobId: task.id,
      entityId: task.id,
      section: "active",
      detailType: "transfer",
    },
  };
}

export function normalizeAppJob(job: AppJob, moduleNames: Map<string, string>, t: Translate): BackgroundAction {
  const source = moduleSource(job.module_id);
  const name = moduleNames.get(job.module_id) || job.module_id;
  return {
    key: actionKey(source, job.id),
    id: job.id,
    source,
    title: translatedOperation(t, job.operation || job.action),
    subtitle: name,
    status: normalizeStatus(job.status, job.cancellation_requested),
    progress: safeProgress(job.progress),
    currentStep: job.current_step || job.stage,
    error: job.error || undefined,
    createdAt: job.created_at * 1000,
    updatedAt: job.finished_at ? job.finished_at * 1000 : undefined,
    finishedAt: job.finished_at ? job.finished_at * 1000 : undefined,
    cancellable: job.cancellable !== false && ["queued", "running"].includes(job.status),
    retryable: ["failed", "cancelled"].includes(job.status),
    target: {
      app: "module",
      moduleId: job.module_id,
      jobId: job.id,
      entityId: job.module_id,
      section: "overview",
      detailType: "package-job",
    },
  };
}

export function normalizeMountJob(mount: NetworkMount, job: NetworkMount["jobs"][number], t: Translate): BackgroundAction {
  const createdAt = (mount.last_operation_at || Date.now() / 1000) * 1000;
  return {
    key: actionKey("mount", job.id),
    id: job.id,
    source: "mount",
    title: translatedOperation(t, job.action),
    subtitle: mount.name,
    status: normalizeStatus(job.status),
    currentStep: t("actions.source.mount"),
    error: job.error || undefined,
    createdAt,
    updatedAt: createdAt,
    finishedAt: ["completed", "failed", "cancelled"].includes(job.status) ? createdAt : undefined,
    target: {
      app: "settings",
      initialPath: "networkResources",
      entityId: mount.id,
      jobId: job.id,
      section: "networkResources",
      detailType: "mount-job",
    },
  };
}

export function normalizeAnsibleExecution(item: AnsibleExecution, t: Translate): BackgroundAction {
  return {
    key: actionKey("ansible", item.id),
    id: item.id,
    relatedJobId: item.package_job_id || undefined,
    source: "ansible",
    title: t("actions.ansibleExecution"),
    subtitle: item.template_id || item.host_ids.join(", ") || t("ansible.name"),
    status: normalizeStatus(item.status),
    currentStep: item.stage,
    error: item.stderr || undefined,
    createdAt: item.created_at * 1000,
    updatedAt: (item.finished_at || item.started_at || item.created_at) * 1000,
    finishedAt: item.finished_at ? item.finished_at * 1000 : undefined,
    cancellable: ["queued", "running"].includes(item.status),
    retryable: ["failed", "cancelled"].includes(item.status),
    target: {
      app: "ansible",
      moduleId: "ansible-controller",
      entityId: item.id,
      jobId: item.package_job_id || item.id,
      section: "jobs",
      detailType: "ansible-job",
    },
  };
}

export function normalizeAnsibleScan(item: AnsibleScan, t: Translate): BackgroundAction {
  return {
    key: actionKey("ansible", `scan-${item.id}`),
    id: item.id,
    relatedJobId: item.package_job_id || undefined,
    source: "ansible",
    title: t("actions.ansibleScan"),
    subtitle: String(item.request.cidr || item.request.target || t("ansible.discovery.title")),
    status: normalizeStatus(item.status),
    progress: safeProgress(item.progress),
    currentStep: t("ansible.discovery.title"),
    error: item.error || undefined,
    createdAt: item.created_at * 1000,
    updatedAt: item.created_at * 1000,
    target: {
      app: "ansible",
      moduleId: "ansible-controller",
      entityId: item.id,
      jobId: item.package_job_id || undefined,
      section: "discovery",
      detailType: "ansible-scan",
    },
  };
}

export function normalizeHostsOperation(item: HostsManagerOperation, t: Translate): BackgroundAction {
  const packageJobId = item.package_job_id || (typeof item.details.package_job_id === "string" ? item.details.package_job_id : undefined);
  return {
    key: actionKey("hosts", item.id),
    id: item.id,
    relatedJobId: packageJobId,
    source: "hosts",
    title: translatedOperation(t, item.capability_id),
    subtitle: item.host_id || t("hosts.name"),
    status: normalizeStatus(item.status),
    progress: safeProgress(item.progress),
    currentStep: item.stage,
    error: item.error || undefined,
    createdAt: item.created_at * 1000,
    updatedAt: item.updated_at * 1000,
    finishedAt: ["completed", "failed", "cancelled"].includes(item.status) ? item.updated_at * 1000 : undefined,
    cancellable: ["queued", "running"].includes(item.status),
    target: {
      app: "hosts",
      moduleId: "hosts-manager",
      entityId: item.id,
      jobId: packageJobId,
      section: "audit",
      detailType: "hosts-operation",
    },
  };
}

export function normalizeNetworkTransaction(item: NetworkTransaction, t: Translate): BackgroundAction {
  return {
    key: actionKey("network", item.id),
    id: item.id,
    source: "network",
    title: t("actions.networkChange"),
    subtitle: item.target,
    status: normalizeStatus(item.status || item.state),
    currentStep: t(`actions.network.${item.status || item.state}`),
    createdAt: (item.created_at || item.started_at) * 1000,
    updatedAt: (item.current_server_time || item.server_time || item.started_at) * 1000,
    finishedAt: ["confirmed", "rolled_back", "failed"].includes(item.status || item.state) ? (item.current_server_time || item.server_time || Date.now() / 1000) * 1000 : undefined,
    target: {
      app: "settings",
      initialPath: "network",
      entityId: item.id,
      section: "network",
      detailType: "network-transaction",
    },
  };
}

export function normalizeSystemUpdate(item: UpdateProgress, t: Translate): BackgroundAction | null {
  if (!item.started_at) return null;
  const id = String(item.pid || item.started_at);
  return {
    key: actionKey("system", `webnas-update-${id}`),
    id,
    source: "system",
    title: t("actions.systemUpdate"),
    subtitle: "WebNAS",
    status: item.running ? "running" : item.exit_code === 0 ? "completed" : item.exit_code === null ? "queued" : "failed",
    currentStep: item.lines.at(-1) || undefined,
    error: !item.running && item.exit_code !== 0 ? item.lines.at(-1) || item.log || undefined : undefined,
    createdAt: item.started_at * 1000,
    updatedAt: (item.finished_at || item.started_at) * 1000,
    finishedAt: item.finished_at ? item.finished_at * 1000 : undefined,
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

export function dedupeAndSortActions(actions: BackgroundAction[]) {
  const specializedJobIds = new Set(
    actions
      .filter((action) => ["ansible", "hosts"].includes(action.source))
      .map((action) => action.relatedJobId)
      .filter((id): id is string => Boolean(id)),
  );
  const unique = new Map<string, BackgroundAction>();
  for (const action of actions) {
    if (action.target.detailType === "package-job" && specializedJobIds.has(action.id)) continue;
    const previous = unique.get(action.key);
    if (!previous || (action.updatedAt || action.createdAt) >= (previous.updatedAt || previous.createdAt)) {
      unique.set(action.key, action);
    }
  }
  return [...unique.values()].sort(
    (left, right) =>
      STATUS_PRIORITY[left.status] - STATUS_PRIORITY[right.status] ||
      (right.updatedAt || right.createdAt) - (left.updatedAt || left.createdAt),
  );
}
