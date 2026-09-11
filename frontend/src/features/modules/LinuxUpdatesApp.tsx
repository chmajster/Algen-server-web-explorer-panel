import { CircleAlert, Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleJob, type ModuleStatus } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { PackageJobDialog } from "../package-center/PackageJobDialog";
import { ManagedModuleApp } from "./ManagedModuleApp";

const ACTIVE_JOB_STATES = new Set(["queued", "running", "waiting_for_confirmation"]);

export function LinuxUpdatesApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [status, setStatus] = useState<ModuleStatus | null>(null);
  const [activeJob, setActiveJob] = useState<ModuleJob | null>(null);
  const [confirmRepair, setConfirmRepair] = useState(false);
  const [liveJob, setLiveJob] = useState<ModuleJob | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.module("linux-updates");
      setStatus(data.module_status);
      setActiveJob(data.active_job || null);
    } catch {
      // ManagedModuleApp reports module loading errors. This lightweight wrapper
      // only controls visibility and state of the dpkg recovery action.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const aptSystem = status?.metrics.package_manager === "apt-get";
  const canRepair = aptSystem && permissions.includes("updates.apply");
  const repairNeeded = String(status?.metrics.package_query_error || "").toLowerCase().includes("dpkg was interrupted");
  const busy = Boolean(activeJob && ACTIVE_JOB_STATES.has(activeJob.status));

  async function repairDpkg() {
    const started = (await api.moduleAction("linux-updates", "repair_dpkg", {})).job;
    setLiveJob(started);
    setActiveJob(started);
    setConfirmRepair(false);
    toast(t("admin.actionCompleted"), "ok", "admin");
    await refresh();
  }

  return <>
    {canRepair && <section className="module-info">
      <div className={repairNeeded ? "module-health-message error" : "module-health-message"}>
        <CircleAlert />
        <span>{repairNeeded
          ? "E: dpkg was interrupted, you must manually run 'dpkg --configure -a' to correct the problem."
          : "APT/DPKG recovery action for interrupted package configuration."}</span>
      </div>
      <div className="managed-actions update-actions">
        <button className="managed-action-button" disabled={busy} onClick={() => setConfirmRepair(true)}>
          <span className="managed-action-icon"><Wrench /></span>
          <span className="managed-action-copy"><strong>dpkg --configure -a</strong><small>Configure pending packages and repair an interrupted dpkg transaction.</small></span>
        </button>
      </div>
    </section>}

    <ManagedModuleApp moduleId="linux-updates" permissions={permissions} t={t} toast={toast} />

    {confirmRepair && <AdminActionDialog
      title="dpkg --configure -a"
      fields={[]}
      description={<section className="linux-update-confirmation">
        <div className="linux-update-confirmation-intro install">
          <Wrench />
          <div>
            <strong>Repair interrupted DPKG configuration</strong>
            <p>This runs the package manager recovery command shown by APT when dpkg was interrupted.</p>
          </div>
        </div>
        <dl>
          <div><dt>Command</dt><dd><code>dpkg --configure -a</code></dd></div>
          <div><dt>Package manager</dt><dd>{String(status?.metrics.package_manager || "apt-get")}</dd></div>
        </dl>
        <p className="linux-update-confirmation-note"><CircleAlert />Pending package maintainer scripts may be executed. Review the job output after the command completes.</p>
      </section>}
      submitLabel="dpkg --configure -a"
      danger
      t={t}
      onClose={() => setConfirmRepair(false)}
      onSubmit={repairDpkg}
    />}

    {liveJob && <PackageJobDialog initialJob={liveJob} moduleName={t("managed.linuxUpdatesName")} t={t} onClose={() => { setLiveJob(null); void refresh(); }} />}
  </>;
}
