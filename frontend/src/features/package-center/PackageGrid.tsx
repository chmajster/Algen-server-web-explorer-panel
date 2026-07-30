import { PackageOpen } from "lucide-react";
import type { AppJob, ModuleSummary } from "../../api";
import type { Translate } from "../../app/types";
import { PackageCard } from "./PackageCard";
import type { PackageAction, PackageView } from "./types";

export function PackageGrid({ modules, loading, view, t, onDetails, onOpen, onAction, onShowJob }: { modules: ModuleSummary[]; loading: boolean; view: PackageView; t: Translate; onDetails: (item: ModuleSummary) => void; onOpen?: (item: ModuleSummary) => void; onAction: (item: ModuleSummary, action: PackageAction) => void; onShowJob: (item: ModuleSummary, job: AppJob) => void }) {
  const className = `package-grid package-view-${view}`;
  if (loading) return <div className={className}>{Array.from({ length: 4 }, (_, index) => <div className="package-skeleton" key={index} />)}</div>;
  if (!modules.length) return <div className="empty-state"><PackageOpen /><strong>{t("package.empty")}</strong><span>{t("package.emptyHint")}</span></div>;
  return <div className={className}>{modules.map((item) => <PackageCard item={item} t={t} onDetails={() => onDetails(item)} onOpen={onOpen ? () => onOpen(item) : undefined} onAction={(action) => onAction(item, action)} onShowJob={(job) => onShowJob(item, job)} key={item.id} />)}</div>;
}
