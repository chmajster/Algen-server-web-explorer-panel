import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type AnsibleExecution,
  type AnsibleScan,
  type AppJob,
  type HostsManagerOperation,
  type NetworkMount,
  type NetworkTransaction,
  type SettingsMe,
  type Task,
  type UpdateProgress,
} from "../../api";
import type { Translate } from "../../app/types";
import {
  dedupeAndSortActions,
  normalizeAnsibleExecution,
  normalizeAnsibleScan,
  normalizeAppJob,
  normalizeHostsOperation,
  normalizeMountJob,
  normalizeNetworkTransaction,
  normalizeSystemUpdate,
  normalizeTransfer,
} from "./normalizers";
import { isActiveAction, type BackgroundAction } from "./types";

const POLL_INTERVAL = 4000;
const COMPLETED_RETENTION = 8000;
const FAILED_RETENTION = 15 * 60 * 1000;

type Sources = {
  appJobs: AppJob[];
  mounts: NetworkMount[];
  ansibleJobs: AnsibleExecution[];
  ansibleScans: AnsibleScan[];
  hostsOperations: HostsManagerOperation[];
  networkTransaction: NetworkTransaction | null;
  systemUpdate: UpdateProgress | null;
};

const emptySources: Sources = {
  appJobs: [],
  mounts: [],
  ansibleJobs: [],
  ansibleScans: [],
  hostsOperations: [],
  networkTransaction: null,
  systemUpdate: null,
};

function replaceById<T extends { id: string }>(items: T[], next: T) {
  return [next, ...items.filter((item) => item.id !== next.id)];
}

export function useBackgroundActions({
  tasks,
  profile,
  moduleNames,
  t,
  pollInterval = POLL_INTERVAL,
}: {
  tasks: Task[];
  profile: SettingsMe;
  moduleNames: Map<string, string>;
  t: Translate;
  pollInterval?: number;
}) {
  const [sources, setSources] = useState<Sources>(emptySources);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const mounted = useRef(true);
  const remembered = useRef(new Map<string, BackgroundAction>());
  const permissions = profile.permissions;
  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);

  const refresh = useCallback(async () => {
    const updates: Partial<Sources> = {};
    const requests: Promise<void>[] = [];
    const load = <K extends keyof Sources>(key: K, request: Promise<Sources[K]>) => {
      requests.push(request.then((value) => { updates[key] = value; }).catch(() => undefined));
    };

    if (can("modules.view")) load("appJobs", api.appJobs());
    else updates.appJobs = [];
    if (can("network_resources.view")) load("mounts", api.mounts());
    else updates.mounts = [];
    if (can("ansible-controller.view")) load("ansibleJobs", api.ansibleJobs());
    else updates.ansibleJobs = [];
    if (can("ansible-controller.discovery")) load("ansibleScans", api.ansibleScans());
    else updates.ansibleScans = [];
    if (can("hosts-manager.audit.view")) load("hostsOperations", api.hostsManagerOperations());
    else updates.hostsOperations = [];
    if (can("network.view")) load("networkTransaction", api.activeNetworkTransaction());
    else updates.networkTransaction = null;
    if (can("updates.view")) load("systemUpdate", api.updateProgress());
    else updates.systemUpdate = null;

    await Promise.all(requests);
    if (mounted.current) setSources((current) => ({ ...current, ...updates }));
  }, [can]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), pollInterval);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [pollInterval, refresh]);

  const activeAppJobIds = sources.appJobs.filter((job) => ["queued", "running", "waiting_for_confirmation"].includes(job.status)).map((job) => job.id).sort().join("|");
  useEffect(() => {
    if (!activeAppJobIds || typeof EventSource === "undefined") return;
    const eventSources = activeAppJobIds.split("|").map((id) => {
      const source = new EventSource(`/api/apps/jobs/${encodeURIComponent(id)}/events`, { withCredentials: true });
      source.onmessage = (event) => {
        try {
          const job = JSON.parse(event.data) as AppJob;
          setSources((current) => ({ ...current, appJobs: replaceById(current.appJobs, job) }));
          if (["completed", "failed", "cancelled"].includes(job.status)) source.close();
        } catch {
          source.close();
        }
      };
      source.onerror = () => source.close();
      return source;
    });
    return () => eventSources.forEach((source) => source.close());
  }, [activeAppJobIds]);

  const activeAnsibleIds = sources.ansibleJobs.filter((job) => ["queued", "running"].includes(job.status)).map((job) => job.id).sort().join("|");
  useEffect(() => {
    if (!activeAnsibleIds || typeof EventSource === "undefined") return;
    const eventSources = activeAnsibleIds.split("|").map((id) => {
      const source = new EventSource(`/api/modules/ansible-controller/jobs/${encodeURIComponent(id)}/events`, { withCredentials: true });
      const update = (event: MessageEvent) => {
        try {
          const value = JSON.parse(event.data) as { execution?: AnsibleExecution };
          if (value.execution) setSources((current) => ({ ...current, ansibleJobs: replaceById(current.ansibleJobs, value.execution!) }));
        } catch {
          source.close();
        }
      };
      source.addEventListener("progress", update as EventListener);
      source.addEventListener("done", update as EventListener);
      source.onerror = () => source.close();
      return source;
    });
    return () => eventSources.forEach((source) => source.close());
  }, [activeAnsibleIds]);

  const activeHostsIds = sources.hostsOperations.filter((operation) => ["queued", "running"].includes(operation.status)).map((operation) => operation.id).sort().join("|");
  useEffect(() => {
    if (!activeHostsIds || typeof EventSource === "undefined") return;
    const eventSources = activeHostsIds.split("|").map((id) => {
      const source = new EventSource(`/api/modules/hosts-manager/operations/${encodeURIComponent(id)}/events`, { withCredentials: true });
      source.onmessage = (event) => {
        try {
          const operation = JSON.parse(event.data) as HostsManagerOperation;
          setSources((current) => ({ ...current, hostsOperations: replaceById(current.hostsOperations, operation) }));
          if (["completed", "failed", "cancelled"].includes(operation.status)) source.close();
        } catch {
          source.close();
        }
      };
      source.onerror = () => source.close();
      return source;
    });
    return () => eventSources.forEach((source) => source.close());
  }, [activeHostsIds]);

  const actions = useMemo(() => {
    const now = Date.now();
    const current = dedupeAndSortActions([
      ...tasks.map((task) => normalizeTransfer(task, t)),
      ...sources.appJobs.map((job) => normalizeAppJob(job, moduleNames, t)),
      ...sources.mounts.flatMap((mount) => mount.jobs.map((job) => normalizeMountJob(mount, job, t))),
      ...sources.ansibleJobs.map((job) => normalizeAnsibleExecution(job, t)),
      ...sources.ansibleScans.map((scan) => normalizeAnsibleScan(scan, t)),
      ...sources.hostsOperations.map((operation) => normalizeHostsOperation(operation, t)),
      ...(sources.networkTransaction ? [normalizeNetworkTransaction(sources.networkTransaction, t)] : []),
      ...(sources.systemUpdate ? [normalizeSystemUpdate(sources.systemUpdate, t)].filter((action): action is BackgroundAction => Boolean(action)) : []),
    ]);
    current.forEach((action) => remembered.current.set(action.key, action));
    for (const [key, action] of remembered.current) {
      const terminalAt = action.finishedAt || action.updatedAt || action.createdAt;
      const retention = action.status === "failed" ? FAILED_RETENTION : COMPLETED_RETENTION;
      if (!isActiveAction(action) && now - terminalAt > retention) remembered.current.delete(key);
    }
    return dedupeAndSortActions([...remembered.current.values()]).filter((action) => {
      if (dismissed.has(action.key)) return false;
      if (isActiveAction(action)) return true;
      const terminalAt = action.finishedAt || action.updatedAt || action.createdAt;
      return now - terminalAt <= (action.status === "failed" ? FAILED_RETENTION : COMPLETED_RETENTION);
    });
  }, [dismissed, moduleNames, sources, t, tasks]);

  const dismiss = useCallback((key: string) => {
    setDismissed((current) => new Set(current).add(key));
  }, []);

  const markOpened = useCallback((action: BackgroundAction) => {
    if (!isActiveAction(action)) dismiss(action.key);
  }, [dismiss]);

  return { actions, refresh, dismiss, markOpened };
}
