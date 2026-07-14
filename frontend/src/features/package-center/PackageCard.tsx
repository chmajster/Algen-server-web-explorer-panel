import { Box, PackageCheck, ShieldAlert } from "lucide-react";
import type { Translate } from "../../app/types";
import type { PackageAction, PackageModule } from "./types";

function mainAction(item: PackageModule): PackageAction | null {
  if (!item.compatible || item.blocked_by_proxmox || ["queued", "running"].includes(item.jobs[0]?.status)) return null;
  if (!item.state.installed) return "install";
  if (item.state.update_available) return "update";
  return Object.values(item.services).some((status) => status === "active") ? "stop" : "start";
}

export function PackageCard({ item, t, onDetails, onAction }: { item: PackageModule; t: Translate; onDetails: () => void; onAction: (action: PackageAction) => void }) {
  const action = mainAction(item);
  return <article className={`package-card status-${item.status}`}><button className="package-card-main" type="button" onClick={onDetails}><span className="package-icon">{item.blocked_by_proxmox ? <ShieldAlert /> : item.state.installed ? <PackageCheck /> : <Box />}</span><span className="package-card-copy"><strong>{item.manifest.name}</strong><small>{t(`package.category.${item.manifest.category}`)}</small><p>{item.manifest.description}</p></span><span className={`package-status ${item.status}`}>{t(`package.status.${item.status}`)}</span></button><dl><div><dt>{t("package.version")}</dt><dd>{item.state.installed_version || "—"} → {item.state.available_version}</dd></div><div><dt>{t("package.services")}</dt><dd>{Object.entries(item.services).map(([name, status]) => `${name}: ${status}`).join(", ") || "—"}</dd></div><div><dt>{t("package.compatibility")}</dt><dd>{item.compatible ? t("common.yes") : t("common.no")}</dd></div></dl><footer><button type="button" onClick={onDetails}>{t("package.details")}</button>{action && <button type="button" className="button-primary" onClick={() => onAction(action)}>{t(`store.${action}`)}</button>}</footer></article>;
}
