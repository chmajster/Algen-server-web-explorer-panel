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
const MISSING_ACTIVE_RETENTION = 15 * 1000;
const MAX_DISMISSED_ACTIONS = 500;

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

function isAllowedAction(action: BackgroundAction, permissions: ReadonlySet<string>) {
  if (action.target.detailType === "transfer") {
    return permissions.has("transfers.view_own") || permissions.has("transfers.view_all");
  }
  if (action.target.detailType === "package-job") return permissions.has("modules.view");
  if (action.target.detailType === "mount-job") return permissions.has("network_resources.view");
  if (action.target.detailType === "ansible-job") return permissions.has("ansible-controller.view");
  if (action.target.detailType === "ansible-scan") return permissions.has("ansible-controller.discovery");
  if (action.target.detailType === "hosts-operation") return permissions.has("hosts-manager.audit.view");
  if (action.target.detailType === "network-transaction") return permissions.has("network.view");
  if (action.target.detailType === "system-update") return permissions.has("updates.view");
  return false;
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
  const [rememberedActions, setRememberedActions] = useState<BackgroundAction[]>([]);
  const mounted = useRef(true);
  const lastSeen = useRef(new Map<string, number>());
  const refreshSequence = useRef(0);
  const latestAppliedRefresh = useRef(0);
  const refreshInFlight = useRef<Promise<void> | null>(null);
  const streamRevisions = useRef<Record<keyof Sources, number>>({
    appJobs: 0,
    mounts: 0,
    ansibleJobs: 0,
    ansibleScans: 0,
    hostsOperations: 0,
    networkTransaction: 0,
    systemUpdate: 0,
  });
  const permissions = profile.permissions;
  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);

  const refresh = useCallback(() => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const operation = (async () => {
      const sequence = ++refreshSequence.current;
      const revisionsAtStart = { ...streamRevisions.current };
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
      if (!mounted.current || sequence < latestAppliedRefresh.current) return;
      latestAppliedRefresh.current = sequence;
      setSources((current) => {
        const next = { ...current };
        for (const key of Object.keys(updates) as Array<keyof Sources>) {
          if (streamRevisions.current[key] !== revisionsAtStart[key]) continue;
          Object.assign(next, { [key]: updates[key] });
        }
        return next;
      });
    })();
    const tracked = operation.finally(() => {
      if (refreshInFlight.current === tracked) refreshInFlight.current = null;
    });
    refreshInFlight.current = tracked;
    return tracked;
  }, [can]);

  useEffect(() => {
    mounted.current = true;
    const pollWhenVisible = () => {
      if (!document.hidden) void refresh();
    };
    pollWhenVisible();
    const timer = window.setInterval(pollWhenVisible, pollInterval);
    document.addEventListener("visibilitychange", pollWhenVisible);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", pollWhenVisible);
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
          streamRevisions.current.appJobs += 1;
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
          if (value.execution) {
            streamRevisions.current.ansibleJobs += 1;
            setSources((current) => ({ ...current, ansibleJobs: replaceById(current.ansibleJobs, value.execution!) }));
          }
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
          streamRevisions.current.hostsOperations += 1;
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

  const currentActions = useMemo(
    () => dedupeAndSortActions([
      ...tasks.map((task) => normalizeTransfer(task, t)),
      ...sources.appJobs.map((job) => normalizeAppJob(job, moduleNames, t)),
      ...sources.mounts.flatMap((mount) => mount.jobs.map((job) => normalizeMountJob(mount, job, t))),
      ...sources.ansibleJobs.map((job) => normalizeAnsibleExecution(job, t)),
      ...sources.ansibleScans.map((scan) => normalizeAnsibleScan(scan, t)),
      ...sources.hostsOperations.map((operation) => normalizeHostsOperation(operation, t)),
      ...(sources.networkTransaction ? [normalizeNetworkTransaction(sources.networkTransaction, t)] : []),
      ...(sources.systemUpdate ? [normalizeSystemUpdate(sources.systemUpdate, t)].filter((action): action is BackgroundAction => Boolean(action)) : []),
    ]),
    [moduleNames, sources, t, tasks],
  );

  useEffect(() => {
    const now = Date.now();
    const currentKeys = new Set(currentActions.map((action) => action.key));
    currentActions.forEach((action) => lastSeen.current.set(action.key, now));
    setRememberedActions((previous) => {
      const remembered = new Map(previous.map((action) => [action.key, action]));
      currentActions.forEach((action) => remembered.set(action.key, action));
      for (const [key, action] of remembered) {
        if (isActiveAction(action) && !currentKeys.has(key) && now - (lastSeen.current.get(key) || action.createdAt) > MISSING_ACTIVE_RETENTION) {
          remembered.delete(key);
          lastSeen.current.delete(key);
          continue;
        }
        const terminalAt = action.finishedAt || action.updatedAt || action.createdAt;
        const retention = action.status === "failed" ? FAILED_RETENTION : COMPLETED_RETENTION;
        if (!isActiveAction(action) && now - terminalAt > retention) {
          remembered.delete(key);
          lastSeen.current.delete(key);
        }
      }
      const next = dedupeAndSortActions([...remembered.values()]);
      return JSON.stringify(next) === JSON.stringify(previous) ? previous : next;
    });
  }, [currentActions]);

  const permissionSet = useMemo(() => new Set(permissions), [permissions]);
  const actions = useMemo(
    () => rememberedActions.filter((action) => !dismissed.has(action.key) && isAllowedAction(action, permissionSet)),
    [dismissed, permissionSet, rememberedActions],
  );

  const dismiss = useCallback((key: string) => {
    setDismissed((current) => {
      const next = new Set(current);
      next.delete(key);
      next.add(key);
      while (next.size > MAX_DISMISSED_ACTIONS) {
        const oldest = next.values().next().value as string | undefined;
        if (!oldest) break;
        next.delete(oldest);
      }
      return next;
    });
  }, []);

  const markOpened = useCallback((action: BackgroundAction) => {
    if (!isActiveAction(action)) dismiss(action.key);
  }, [dismiss]);

  return { actions, refresh, dismiss, markOpened };
}
