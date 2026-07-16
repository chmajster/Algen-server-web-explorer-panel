import { Box, PackageCheck, ShieldAlert } from "lucide-react";
import type { ModuleSummary } from "../../api";
import type { Translate } from "../../app/types";
import type { PackageAction } from "./types";

function mainAction(item: ModuleSummary): PackageAction | null {
  if (!item.compatible || item.blocked_by_proxmox || item.active_job) return null;
  if (!item.state.installed) return item.capabilities.install ? "install" : null;
  if (item.state.update_available) return item.capabilities.update ? "update" : null;
  if (!item.capabilities.service_control) return null;
  return Object.values(item.services).some((status) => status === "active") ? "stop" : "start";
}

export function PackageCard({ item, t, onDetails, onOpen, onAction }: { item: ModuleSummary; t: Translate; onDetails: () => void; onOpen: () => void; onAction: (action: PackageAction) => void }) {
  const action = mainAction(item);
  const manageable = item.state.installed || item.capabilities.configure || item.capabilities.resources.length > 0 || item.capabilities.actions.length > 0;
  return <article className={`package-card status-${item.status}`}>
    <button className="package-card-main" type="button" onClick={onDetails}><span className="package-icon">{item.blocked_by_proxmox ? <ShieldAlert /> : item.state.installed ? <PackageCheck /> : <Box />}</span><span className="package-card-copy"><strong>{item.manifest.name}</strong><small>{t(`package.category.${item.manifest.category}`)}</small><p>{item.manifest.description}</p></span><span className={`package-status ${item.status}`}>{t(`package.status.${item.status}`)}</span></button>
    <dl><div><dt>{t("package.version")}</dt><dd>{item.module_status.package_version || "—"} → {item.module_status.available_version || item.state.available_version}</dd></div><div><dt>{t("module.serviceState")}</dt><dd>{item.module_status.service_state}</dd></div><div><dt>{t("module.health")}</dt><dd><span className={`module-health-inline ${item.module_status.health}`}>{t(`module.health.${item.module_status.health}`)}</span></dd></div><div><dt>{t("package.updateAvailable")}</dt><dd>{item.module_status.update_available ? t("common.yes") : t("common.no")}</dd></div>{item.active_job && <div><dt>{t("module.activeJob")}</dt><dd>{t(`module.operation.${item.active_job.operation || item.active_job.action}`)} · {item.active_job.progress}%</dd></div>}{item.module_status.last_error && <div className="package-last-error"><dt>{t("module.lastError")}</dt><dd>{item.module_status.last_error}</dd></div>}</dl>
    <footer><button type="button" onClick={onDetails}>{t("package.details")}</button>{manageable && <button type="button" className="button-primary" onClick={onOpen}>{t("action.open")}</button>}{action && <button type="button" className={item.state.installed ? "" : "button-primary"} onClick={() => onAction(action)}>{t(`store.${action}`)}</button>}</footer>
  </article>;
}
