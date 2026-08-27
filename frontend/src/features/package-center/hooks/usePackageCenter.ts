import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type AppJob, type ModuleSummary, type PackageHistoryItem, type PackageSource } from "../../../api";
import type { Translate } from "../../../app/types";
import { useRefreshOnConnectionRestored } from "../../connection/ConnectionStatusMonitor";
import type { PackageTab } from "../types";
import { getPackageUiStatus, isPackageUpdateAvailable, matchesPackageSearch, mergePackageCatalog } from "../packageState";

export function usePackageCenter(t: Translate, { canManageSources = true }: { canManageSources?: boolean } = {}) {
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [jobs, setJobs] = useState<AppJob[]>([]);
  const [history, setHistory] = useState<PackageHistoryItem[]>([]);
  const [sources, setSources] = useState<PackageSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<PackageTab>("all");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const [catalog, nextModules, nextCategories, nextJobs, nextHistory, nextSources] = await Promise.all([
        api.apps(),
        api.modules().catch(() => []),
        api.appCategories(),
        api.appJobs(),
        api.appHistory(),
        canManageSources ? api.packageSources() : Promise.resolve([] as PackageSource[]),
      ]);
      setModules(mergePackageCatalog(catalog, nextModules));
      setCategories(nextCategories);
      setJobs(nextJobs);
      setHistory(nextHistory);
      setSources(nextSources);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Module Center request failed"); }
    finally { if (!quiet) setLoading(false); }
  }, [canManageSources]);

  const refreshModule = useCallback(async (moduleId: string) => {
    try {
      const next = await api.module(moduleId);
      setModules((current) => current.map((item) => item.id === moduleId ? next : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Package request failed");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useRefreshOnConnectionRestored(() => { void refresh(true); });
  const activeIds = jobs.filter((job) => ["queued", "running"].includes(job.status)).map((job) => job.id).join("|");
  useEffect(() => {
    if (!activeIds) return;
    const events = activeIds.split("|").map((id) => {
      const source = new EventSource(`/api/apps/jobs/${encodeURIComponent(id)}/events`);
      source.onmessage = (event) => {
        const job = JSON.parse(event.data) as AppJob;
        setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
        if (["completed", "failed", "cancelled"].includes(job.status)) {
          void refreshModule(job.module_id);
          void refresh(true);
        }
      };
      source.onerror = () => source.close();
      return source;
    });
    const fallback = window.setInterval(() => void refresh(true), 2500);
    return () => { events.forEach((source) => source.close()); window.clearInterval(fallback); };
  }, [activeIds, refresh, refreshModule]);

  const visibleModules = useMemo(() => modules.filter((item) => {
    if (!matchesPackageSearch(item, search, t)) return false;
    if (category && item.manifest.category !== category) return false;
    if (status && getPackageUiStatus(item) !== status) return false;
    if (tab === "installed" && !item.state.installed) return false;
    if (tab === "updates" && !isPackageUpdateAvailable(item)) return false;
    return true;
  }), [category, modules, search, status, t, tab]);

  return { modules, visibleModules, categories, jobs, history, sources, loading, error, tab, search, category, status, setTab, setSearch, setCategory, setStatus, refresh, refreshModule };
}
