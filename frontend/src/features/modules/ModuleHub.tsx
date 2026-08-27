import { Boxes, Download, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ModuleSummary, type PackageModule } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { useRefreshOnConnectionRestored } from "../connection/ConnectionStatusMonitor";
import { PackageActionDialog } from "../package-center/PackageActionDialog";
import { mergePackageCatalog } from "../package-center/packageState";
import { ModuleStatusBadge } from "./common/ModuleAppShell";

export function ModuleHub({ t, toast, onOpen, permissions = [] }: { t: Translate; toast: ToastFn; onOpen: (moduleId: string) => void; permissions?: string[] }) {
  const [modules, setModules] = useState<ModuleSummary[]>([]); const [loading, setLoading] = useState(false); const [search, setSearch] = useState(""); const [installTarget, setInstallTarget] = useState<ModuleSummary | null>(null);
  const refreshRequest = useRef(0);
  const refresh = useCallback(async () => {
    const requestId = ++refreshRequest.current;
    setLoading(true);
    let catalog: PackageModule[] | null = null;
    let runtime: ModuleSummary[] | null = null;
    const publish = () => {
      if (refreshRequest.current !== requestId) return;
      setModules(mergePackageCatalog(catalog || [], runtime || []));
    };
    const [catalogResult, runtimeResult] = await Promise.allSettled([
      api.apps().then((value) => { catalog = value; publish(); }),
      api.modules().then((value) => { runtime = value; publish(); }),
    ]);
    if (refreshRequest.current !== requestId) return;
    if (catalogResult.status === "rejected" && runtimeResult.status === "rejected") {
      const error = runtimeResult.reason;
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin");
    }
    setLoading(false);
  }, [t, toast]);
  useEffect(() => { void refresh(); }, [refresh]);
  useRefreshOnConnectionRestored(() => { void refresh(); });
  const visible = modules.filter((module) => `${module.manifest.name} ${module.manifest.description}`.toLowerCase().includes(search.toLowerCase()));
  const canInstallModules = permissions.includes("modules.install");
  return <><section className="system-app module-hub"><header className="feature-header"><div><h2>{t("app.modules")}</h2><p>{t("managed.hubSubtitle")}</p></div><div className="header-actions"><input aria-label={t("action.search")} placeholder={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} /><button onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></div></header><div className="card-grid">{visible.map((module) => {
    const installable = canInstallModules && !module.state.installed && module.capabilities.install && module.compatible && !module.blocked_by_proxmox;
    return <article className="data-card" key={module.id}><header><Boxes /><strong>{module.manifest.name}</strong><ModuleStatusBadge status={module.module_status} t={t} /></header><p>{module.manifest.description}</p><dl><dt>{t("module.serviceState")}</dt><dd>{module.module_status.service_state}</dd><dt>{t("module.version")}</dt><dd>{module.module_status.package_version || "—"}</dd></dl><div className="data-actions">{installable && <button className="button-primary" onClick={() => setInstallTarget(module)}><Download />{t("store.install")}</button>}<button className={installable ? "" : "button-primary"} onClick={() => onOpen(module.id)}>{t("managed.openModule")}</button></div></article>;
  })}</div>{!visible.length && (loading ? <div className="loading-state" role="status">{t("status.loading")}</div> : <div className="empty-state">{t("managed.noModules")}</div>)}</section>{installTarget && <PackageActionDialog item={installTarget} action="install" t={t} toast={toast} onClose={() => setInstallTarget(null)} onStarted={() => { setInstallTarget(null); void refresh(); }} />}</>;
}
