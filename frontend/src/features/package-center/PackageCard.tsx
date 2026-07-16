import { Box, PackageCheck, RefreshCw, ShieldAlert } from "lucide-react";
import type { ModuleSummary } from "../../api";
import type { Translate } from "../../app/types";
import { getPackageActions, getPackageInstalledVersion, getPackageServiceStatus, getPackageUiStatus, packageActionLabelKey, type PackageDisplayAction } from "./packageState";
import type { PackageAction } from "./types";

const KNOWN_OPERATIONS = new Set(["install", "update", "uninstall", "start", "stop", "restart"]);

function operationLabel(item: ModuleSummary, t: Translate): string {
  const operation = item.active_job?.operation || item.active_job?.action || "working";
  return t(`package.operation.${KNOWN_OPERATIONS.has(operation) ? operation : "working"}`);
}

export function PackageCard({ item, t, onDetails, onOpen, onAction }: { item: ModuleSummary; t: Translate; onDetails: () => void; onOpen?: () => void; onAction: (action: PackageAction) => void }) {
  const status = getPackageUiStatus(item);
  const serviceStatus = getPackageServiceStatus(item);
  const busy = Boolean(item.active_job && ["queued", "running", "waiting_for_confirmation"].includes(item.active_job.status));
  const actions = getPackageActions(item).filter((action) => !["open", "configure"].includes(action) || onOpen);
  const titleId = `package-card-${item.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  function run(action: PackageDisplayAction) {
    if (action === "open" || action === "configure") onOpen?.();
    else onAction(action);
  }

  return <article className={`package-card ui-status-${status}`} aria-labelledby={titleId} aria-busy={busy}>
    <button className="package-card-main" type="button" onClick={onDetails} aria-label={`${t("package.details")}: ${item.manifest.name}`}>
      <span className="package-icon" aria-hidden="true">{item.blocked_by_proxmox ? <ShieldAlert /> : item.state.installed ? <PackageCheck /> : <Box />}</span>
      <span className="package-card-copy"><strong id={titleId}>{item.manifest.name}</strong><small>{t(`package.category.${item.manifest.category}`)}</small><p>{item.manifest.description}</p></span>
      <span className={`package-status ui-status-${status}`} role="status">{t(`package.status.${status}`)}</span>
    </button>
    <dl className="package-card-facts">
      <div><dt>{t("package.version")}</dt><dd>{getPackageInstalledVersion(item)}</dd></div>
      <div><dt>{t("module.serviceState")}</dt><dd>{t(`package.service.${serviceStatus}`)}</dd></div>
      <div><dt>{t("module.health")}</dt><dd><span className={`module-health-inline ${item.module_status.health}`}>{t(`module.health.${item.module_status.health}`)}</span></dd></div>
      <div><dt>{t("package.updateAvailable")}</dt><dd>{item.state.update_available || item.module_status.update_available ? t("common.yes") : t("common.no")}</dd></div>
      {item.module_status.last_error && <div className="package-last-error"><dt>{t("module.lastError")}</dt><dd>{item.module_status.last_error}</dd></div>}
    </dl>
    {busy && <div className="package-operation-state" role="status" aria-live="polite"><RefreshCw className="spin" aria-hidden="true" /><span>{operationLabel(item, t)}</span><small>{item.active_job?.progress ?? 0}%</small></div>}
    <footer>
      <button type="button" onClick={onDetails}>{t("package.details")}</button>
      {actions.map((action, index) => <button type="button" disabled={busy} className={index === 0 && !["stop", "uninstall"].includes(action) ? "button-primary" : action === "uninstall" ? "button-danger" : ""} onClick={() => run(action)} key={action}>{t(packageActionLabelKey(action))}</button>)}
    </footer>
  </article>;
}
