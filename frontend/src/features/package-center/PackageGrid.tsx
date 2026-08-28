import { PackageOpen } from "lucide-react";
import type { AppJob, ModuleSummary } from "../../api";
import type { Translate } from "../../app/types";
import { PackageCard } from "./PackageCard";
import type { PackageAction, PackageView } from "./types";

type PackageGridProps = {
  modules: ModuleSummary[];
  loading: boolean;
  view: PackageView;
  permissions?: readonly string[];
  t: Translate;
  onDetails: (item: ModuleSummary) => void;
  onOpen?: (item: ModuleSummary) => void;
  onAction: (item: ModuleSummary, action: PackageAction) => void;
  onShowJob: (item: ModuleSummary, job: AppJob) => void;
};

export function PackageGrid({ modules, loading, view, permissions, t, onDetails, onOpen, onAction, onShowJob }: PackageGridProps) {
  const className = `package-grid package-view-${view}`;
  if (loading) return <div className={className} role="status" aria-label={t("status.loading")} aria-busy="true">{Array.from({ length: 8 }, (_, index) => <div className="package-skeleton" aria-hidden="true" key={index} />)}</div>;
  if (!modules.length) return <div className="empty-state package-empty"><PackageOpen aria-hidden="true" /><strong>{t("package.empty")}</strong><span>{t("package.emptyHint")}</span></div>;
  return <div className={className}>
    {modules.map((item) => <PackageCard item={item} permissions={permissions} t={t} onDetails={() => onDetails(item)} onOpen={onOpen ? () => onOpen(item) : undefined} onAction={(action) => onAction(item, action)} onShowJob={(job) => onShowJob(item, job)} key={item.id} />)}
  </div>;
}
