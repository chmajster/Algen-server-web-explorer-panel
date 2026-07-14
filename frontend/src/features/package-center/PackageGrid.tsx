import { PackageOpen } from "lucide-react";
import type { Translate } from "../../app/types";
import { PackageCard } from "./PackageCard";
import type { PackageAction, PackageModule } from "./types";

export function PackageGrid({ modules, loading, t, onDetails, onAction }: { modules: PackageModule[]; loading: boolean; t: Translate; onDetails: (item: PackageModule) => void; onAction: (item: PackageModule, action: PackageAction) => void }) {
  if (loading) return <div className="package-grid">{Array.from({ length: 4 }, (_, index) => <div className="package-skeleton" key={index} />)}</div>;
  if (!modules.length) return <div className="empty-state"><PackageOpen /><strong>{t("package.empty")}</strong><span>{t("package.emptyHint")}</span></div>;
  return <div className="package-grid">{modules.map((item) => <PackageCard item={item} t={t} onDetails={() => onDetails(item)} onAction={(action) => onAction(item, action)} key={item.id} />)}</div>;
}
