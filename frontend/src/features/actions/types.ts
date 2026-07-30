import type { AppId } from "../../app/types";

export type BackgroundActionStatus =
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type BackgroundActionSource =
  | "transfer"
  | "upload"
  | "package"
  | "module"
  | "mount"
  | "docker"
  | "ansible"
  | "hosts"
  | "network"
  | "system"
  | string;

export type BackgroundActionTarget = {
  app: AppId;
  moduleId?: string;
  initialPath?: string;
  entityId?: string;
  jobId?: string;
  section?: string;
  detailType:
    | "transfer"
    | "package-job"
    | "mount-job"
    | "ansible-job"
    | "ansible-scan"
    | "hosts-operation"
    | "network-transaction"
    | "system-update";
};

export type BackgroundAction = {
  key: string;
  id: string;
  relatedJobId?: string;
  source: BackgroundActionSource;
  title: string;
  subtitle?: string;
  status: BackgroundActionStatus;
  progress?: number;
  currentStep?: string;
  error?: string;
  createdAt: number;
  updatedAt?: number;
  finishedAt?: number;
  cancellable?: boolean;
  retryable?: boolean;
  target: BackgroundActionTarget;
};

export const ACTIVE_ACTION_STATUSES = new Set<BackgroundActionStatus>([
  "queued",
  "running",
  "paused",
]);

export function isActiveAction(action: BackgroundAction) {
  return ACTIVE_ACTION_STATUSES.has(action.status);
}
