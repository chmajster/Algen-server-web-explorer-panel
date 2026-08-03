import { Box, Network, PackageCheck, RefreshCw, Server, Share2, ShieldAlert } from "lucide-react";
import type { AppJob, ModuleSummary } from "../../api";
import type { Translate } from "../../app/types";
import { getPackageActions, getPackageInstalledVersion, getPackageServiceStatus, getPackageUiStatus, isPackageUpdateAvailable, packageActionLabelKey, type PackageDisplayAction } from "./packageState";
import type { PackageAction } from "./types";

const KNOWN_OPERATIONS = new Set(["install", "reinstall", "update", "uninstall", "start", "stop", "restart"]);

function catalogIcon(icon: string) {
  if (icon === "share-2") return <Share2 />;
  if (icon === "server") return <Server />;
  if (icon === "network") return <Network />;
  return <Box />;
}

function operationLabel(item: ModuleSummary, t: Translate): string {
  const operation = item.active_job?.operation || item.active_job?.action || "working";
  return t(`package.operation.${KNOWN_OPERATIONS.has(operation) ? operation : "working"}`);
}

type PackageCardProps = {
  item: ModuleSummary;
  t: Translate;
  onDetails: () => void;
  onOpen?: () => void;
  onAction: (action: PackageAction) => void;
  onShowJob: (job: AppJob) => void;
};

export function PackageCard({ item, t, onDetails, onOpen, onAction, onShowJob }: PackageCardProps) {
  const status = getPackageUiStatus(item);
  const serviceStatus = getPackageServiceStatus(item);
  const updateAvailable = isPackageUpdateAvailable(item);
  const isLinuxUpdates = item.id === "linux-updates";
  const runtimePackageManager = String(item.module_status.metrics.package_manager || item.distribution.package_manager || t("module.notAvailable"));
  const activeJob = item.active_job && ["queued", "running", "waiting_for_confirmation"].includes(item.active_job.status) ? item.active_job : null;
  const busy = Boolean(activeJob);
  const actions = getPackageActions(item).filter((action) => !["open", "configure"].includes(action) || onOpen);
  const titleId = `package-card-${item.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  function run(action: PackageDisplayAction) {
    if (action === "open" || action === "configure") onOpen?.();
    else onAction(action);
  }

  return <article className={`package-card ui-status-${status}`} aria-labelledby={titleId} aria-busy={busy}>
    <button className="package-card-main" type="button" onClick={onDetails} aria-label={`${t("package.details")}: ${item.manifest.name}`}>
      <span className="package-icon" aria-hidden="true">
        {item.blocked_by_proxmox ? <ShieldAlert /> : item.state.installed ? <PackageCheck /> : catalogIcon(item.manifest.icon)}
      </span>
      <span className="package-card-copy">
        <span className="package-card-heading">
          <strong id={titleId}>{item.manifest.name}</strong>
          <span className={`package-status ui-status-${status}`} role="status">{t(`package.status.${status}`)}</span>
        </span>
        <small>{t(`package.category.${item.manifest.category}`)}</small>
        <p>{item.manifest.description}</p>
      </span>
    </button>
    <dl className="package-card-facts">
      <div><dt>{t("package.version")}</dt><dd>{getPackageInstalledVersion(item)}</dd></div>
      <div><dt>{t(isLinuxUpdates ? "managed.field.package_manager" : "module.serviceState")}</dt><dd>{isLinuxUpdates ? runtimePackageManager : t(`package.service.${serviceStatus}`)}</dd></div>
      <div><dt>{t("module.health")}</dt><dd><span className={`module-health-inline ${item.module_status.health}`}>{t(`module.health.${item.module_status.health}`)}</span></dd></div>
      <div className={updateAvailable ? "package-update-available" : ""}><dt>{t("package.updateAvailable")}</dt><dd>{updateAvailable ? t("common.yes") : t("common.no")}</dd></div>
      {item.module_status.last_error && <div className="package-last-error"><dt>{t("module.lastError")}</dt><dd>{item.module_status.last_error}</dd></div>}
    </dl>
    {activeJob && <button className="package-operation-state" type="button" onClick={() => onShowJob(activeJob)} aria-live="polite" aria-label={`${t("package.showLiveJob")}: ${operationLabel(item, t)}, ${activeJob.progress}%`}>
      <span className="package-operation-label"><RefreshCw className="spin" aria-hidden="true" /><span>{operationLabel(item, t)}</span><small>{activeJob.progress}%</small></span>
      <span className="package-operation-progress" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, activeJob.progress))}%` }} /></span>
    </button>}
    <footer>
      <button type="button" onClick={onDetails}>{t("package.details")}</button>
      {actions.map((action, index) => <button
        type="button"
        disabled={busy}
        className={index === 0 && !["stop", "uninstall"].includes(action) ? "button-primary" : action === "uninstall" ? "button-danger" : ""}
        onClick={() => run(action)}
        key={action}
      >{t(!item.state.installed && action === "open" ? "store.install" : packageActionLabelKey(action))}</button>)}
    </footer>
  </article>;
}
