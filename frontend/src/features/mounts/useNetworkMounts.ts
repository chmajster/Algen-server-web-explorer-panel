import { useEffect, useState } from "react";
import { api, type NetworkMountRoot } from "../../api";
import { useRefreshOnConnectionRestored } from "../connection/ConnectionStatusMonitor";

export const MOUNTS_CHANGED_EVENT = "webnas:mounts-changed";

type Snapshot = { roots: NetworkMountRoot[]; loading: boolean; initialized: boolean; error: string };

let snapshot: Snapshot = { roots: [], loading: false, initialized: false, error: "" };
let pending: Promise<void> | null = null;
let generation = 0;
let watchTimer: number | null = null;
let watchDeadline = 0;
const listeners = new Set<() => void>();

function publish() {
  listeners.forEach((listener) => listener());
}

export function refreshNetworkMounts(): Promise<void> {
  if (pending) return pending;
  // Some embedded/test clients may still expose the pre-roots API surface.
  // Treat that as no published resources rather than crashing File Explorer.
  if (typeof api.mountRoots !== "function") {
    snapshot = { roots: [], loading: false, initialized: true, error: "" };
    publish();
    return Promise.resolve();
  }
  const requestGeneration = ++generation;
  snapshot = { ...snapshot, loading: true, error: "" };
  publish();
  pending = api.mountRoots()
    .then((roots) => {
      if (requestGeneration === generation) snapshot = { roots, loading: false, initialized: true, error: "" };
    })
    .catch((reason: unknown) => {
      if (requestGeneration === generation) snapshot = { ...snapshot, loading: false, initialized: true, error: reason instanceof Error ? reason.message : "Unable to load network resources" };
    })
    .finally(() => {
      if (requestGeneration === generation) pending = null;
      publish();
    });
  return pending;
}

export function notifyNetworkMountsChanged() {
  window.dispatchEvent(new CustomEvent(MOUNTS_CHANGED_EVENT));
}

export function watchNetworkMountChanges(durationMs = 180_000) {
  watchDeadline = Math.max(watchDeadline, Date.now() + durationMs);
  if (watchTimer !== null) return;
  watchTimer = window.setInterval(() => {
    if (Date.now() >= watchDeadline) {
      stopWatchingNetworkMountChanges();
      return;
    }
    void refreshNetworkMounts();
  }, 1200);
}

export function stopWatchingNetworkMountChanges() {
  if (watchTimer !== null) window.clearInterval(watchTimer);
  watchTimer = null;
  watchDeadline = 0;
}

export function useNetworkMounts() {
  const [current, setCurrent] = useState(snapshot);
  useRefreshOnConnectionRestored(() => { void refreshNetworkMounts(); });

  useEffect(() => {
    const update = () => setCurrent(snapshot);
    const changed = () => { void refreshNetworkMounts(); };
    listeners.add(update);
    window.addEventListener(MOUNTS_CHANGED_EVENT, changed);
    if (!pending && snapshot.roots.length === 0) void refreshNetworkMounts();
    return () => {
      listeners.delete(update);
      window.removeEventListener(MOUNTS_CHANGED_EVENT, changed);
    };
  }, []);

  return { ...current, refresh: refreshNetworkMounts };
}
