import { Boxes, CircleArrowUp, Database, History, ListTodo, PackageCheck, type LucideIcon } from "lucide-react";
import type { Translate } from "../../app/types";
import type { PackageTab } from "./types";

const tabs: Array<{ id: PackageTab; icon: LucideIcon }> = [
  { id: "all", icon: Boxes },
  { id: "installed", icon: PackageCheck },
  { id: "updates", icon: CircleArrowUp },
  { id: "jobs", icon: ListTodo },
  { id: "history", icon: History },
  { id: "sources", icon: Database },
];

type PackageTabsProps = {
  active: PackageTab;
  counts: Partial<Record<PackageTab, number>>;
  showSources?: boolean;
  t: Translate;
  onChange: (tab: PackageTab) => void;
};

export function PackageTabs({ active, counts, showSources = true, t, onChange }: PackageTabsProps) {
  return <nav className="package-tabs" aria-label={t("package.tabs")}>
    {tabs.filter(({ id }) => showSources || id !== "sources").map(({ id, icon: Icon }) => <button type="button" className={active === id ? "active" : ""} aria-current={active === id ? "page" : undefined} onClick={() => onChange(id)} key={id}>
      <Icon aria-hidden="true" />
      <span>{t(`package.tab.${id}`)}</span>
      {counts[id] !== undefined && <small aria-label={`${t(`package.tab.${id}`)}: ${counts[id]}`}>{counts[id]}</small>}
    </button>)}
  </nav>;
}
