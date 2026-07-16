import type { Translate } from "../../app/types";
import type { PackageTab } from "./types";

const tabs: PackageTab[] = ["all", "installed", "updates", "jobs", "history", "sources"];

export function PackageTabs({ active, counts, t, onChange }: { active: PackageTab; counts: Partial<Record<PackageTab, number>>; t: Translate; onChange: (tab: PackageTab) => void }) {
  return <nav className="package-tabs" aria-label={t("package.tabs")}>{tabs.map((tab) => <button type="button" className={active === tab ? "active" : ""} aria-current={active === tab ? "page" : undefined} onClick={() => onChange(tab)} key={tab}><span>{t(`package.tab.${tab}`)}</span>{counts[tab] !== undefined && <small aria-label={`${t(`package.tab.${tab}`)}: ${counts[tab]}`}>{counts[tab]}</small>}</button>)}</nav>;
}
