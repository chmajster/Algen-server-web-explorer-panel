import { useEffect, useMemo, useState } from "react";
import { Boxes } from "lucide-react";
import { api, type AppJob, type ModuleSummary } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { PackageActionDialog } from "./PackageActionDialog";
import { PackageDetails } from "./PackageDetails";
import { PackageGrid } from "./PackageGrid";
import { PackageHistory } from "./PackageHistory";
import { PackageJobDialog } from "./PackageJobDialog";
import { PackageJobs } from "./PackageJobs";
import { PackageSources } from "./PackageSources";
import { PackageTabs } from "./PackageTabs";
import { PackageToolbar } from "./PackageToolbar";
import { usePackageCenter } from "./hooks/usePackageCenter";
import { getPackageDisplayName, isPackageUpdateAvailable } from "./packageState";
import type { PackageAction, PackageView } from "./types";
import "./package-center.css";

type CredentialAction = { job: AppJob; operation: "cancel" | "retry" } | null;
const packageViewStorageKey = "webnas_package_center_view";

export function PackageCenterApp({ selectedJobId, t, toast, onOpenModule, onSelectedJobClose }: { selectedJobId?: string; t: Translate; toast: ToastFn; onOpenModule?: (moduleId: string) => void; onSelectedJobClose?: () => void }) {
  const state = usePackageCenter(t);
  const [view, setView] = useState<PackageView>(() => window.localStorage.getItem(packageViewStorageKey) === "list" ? "list" : "grid");
  const [selected, setSelected] = useState<ModuleSummary | null>(null);
  const [action, setAction] = useState<{ item: ModuleSummary; action: PackageAction } | null>(null);
  const [liveJob, setLiveJob] = useState<{ job: AppJob; name: string } | null>(null);
  const [credential, setCredential] = useState<CredentialAction>(null);
  useEffect(() => {
    if (!selectedJobId) return;
    let active = true;
    void api.appJob(selectedJobId).then((job) => {
      if (!active) return;
      const module = state.modules.find((item) => item.id === job.module_id);
      setLiveJob({ job, name: module ? getPackageDisplayName(module, t) : job.module_id });
    }).catch((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error"));
    return () => { active = false; };
  }, [selectedJobId, state.modules, t, toast]);
  const counts = useMemo(() => ({
    all: state.modules.length,
    installed: state.modules.filter((item) => item.state.installed).length,
    updates: state.modules.filter(isPackageUpdateAvailable).length,
    jobs: state.jobs.filter((job) => ["queued", "running"].includes(job.status)).length,
    history: state.history.length,
    sources: state.sources.length,
  }), [state.history.length, state.jobs, state.modules, state.sources.length]);

  function begin(item: ModuleSummary, nextAction: PackageAction) {
    if (item.id === "docker" && item.state.installed && onOpenModule) {
      setSelected(null);
      window.setTimeout(() => onOpenModule("docker"), 0);
      return;
    }
    setSelected(null);
    setAction({ item, action: nextAction });
  }

  function openSelectedModule(item: ModuleSummary) {
    setSelected(null);
    window.setTimeout(() => onOpenModule?.(item.id), 0);
  }

  async function jobOperation() {
    if (!credential) return;
    if (credential.operation === "cancel") await api.cancelAppJob(credential.job.id);
    else await api.retryAppJob(credential.job.id);
    toast(t("admin.actionCompleted"), "ok", "admin");
    setCredential(null);
    await state.refresh(true);
  }

  function selectView(nextView: PackageView) {
    setView(nextView);
    window.localStorage.setItem(packageViewStorageKey, nextView);
  }

  const catalogTab = ["all", "installed", "updates"].includes(state.tab);
  return <section className="package-center">
    <header className="package-center-title">
      <span className="package-center-title-icon" aria-hidden="true"><Boxes /></span>
      <div><h2>{t("app.store")}</h2><p>{t("store.subtitle")}</p></div>
    </header>
    <PackageToolbar search={state.search} category={state.category} status={state.status} categories={state.categories} updates={counts.updates} updatesActive={state.tab === "updates"} loading={state.loading} view={view} showView={catalogTab} t={t} onSearch={state.setSearch} onCategory={state.setCategory} onStatus={state.setStatus} onUpdates={() => state.setTab("updates")} onRefresh={() => void state.refresh()} onView={selectView} />
    <div className="package-center-layout">
      <PackageTabs active={state.tab} counts={counts} t={t} onChange={state.setTab} />
      <main className="package-center-content" aria-busy={state.loading}>
        {state.error
          ? <div className="error-state package-center-error" role="alert"><strong>{t("status.error")}</strong><span>{state.error}</span><button type="button" onClick={() => void state.refresh()}>{t("action.retry")}</button></div>
          : <>
            {catalogTab && <PackageGrid modules={state.visibleModules} loading={state.loading} view={view} t={t} onDetails={setSelected} onOpen={onOpenModule ? (item) => onOpenModule(item.id) : undefined} onAction={begin} onShowJob={(item, job) => setLiveJob({ job, name: getPackageDisplayName(item, t) })} />}
            {state.tab === "jobs" && <PackageJobs jobs={state.jobs} t={t} onCancel={(job) => setCredential({ job, operation: "cancel" })} onRetry={(job) => setCredential({ job, operation: "retry" })} />}
            {state.tab === "history" && <PackageHistory history={state.history} t={t} />}
            {state.tab === "sources" && <PackageSources sources={state.sources} t={t} toast={toast} onChanged={() => void state.refresh(true)} />}
          </>}
      </main>
    </div>
    {selected && <PackageDetails item={selected} t={t} onClose={() => setSelected(null)} onAction={(nextAction) => begin(selected, nextAction)} onConfigure={onOpenModule ? () => openSelectedModule(selected) : undefined} />}
    {action && <PackageActionDialog item={action.item} action={action.action} t={t} toast={toast} onClose={() => setAction(null)} onStarted={(job) => { setLiveJob({ job, name: getPackageDisplayName(action.item, t) }); void state.refreshModule(action.item.id); void state.refresh(true); }} />}
    {liveJob && <PackageJobDialog initialJob={liveJob.job} moduleName={liveJob.name} t={t} onClose={() => { setLiveJob(null); if (selectedJobId === liveJob.job.id) onSelectedJobClose?.(); }} />}
    {credential && <AdminActionDialog title={t(credential.operation === "cancel" ? "package.cancelJob" : "action.retry")} fields={[]} danger={credential.operation === "cancel"} t={t} onClose={() => setCredential(null)} onSubmit={jobOperation} />}
  </section>;
}
