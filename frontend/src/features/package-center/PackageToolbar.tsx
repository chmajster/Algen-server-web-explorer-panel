import { RefreshCw, Search } from "lucide-react";
import type { Translate } from "../../app/types";

export function PackageToolbar({ search, category, status, categories, updates, updatesActive, loading, t, onSearch, onCategory, onStatus, onUpdates, onRefresh }: {
  search: string; category: string; status: string; categories: string[]; updates: number; updatesActive: boolean; loading: boolean; t: Translate;
  onSearch: (value: string) => void; onCategory: (value: string) => void; onStatus: (value: string) => void; onUpdates: () => void; onRefresh: () => void;
}) {
  const statuses = ["not_installed", "installed", "running", "stopped", "needs_config", "update_available", "error"];
  return <header className="package-toolbar"><label className="package-search"><Search aria-hidden="true" /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("package.search")} aria-label={t("package.search")} /></label><select aria-label={t("package.category")} value={category} onChange={(event) => onCategory(event.target.value)}><option value="">{t("package.allCategories")}</option>{categories.map((item) => <option value={item} key={item}>{t(`package.category.${item}`)}</option>)}</select><select aria-label={t("package.status")} value={status} onChange={(event) => onStatus(event.target.value)}><option value="">{t("package.allStatuses")}</option>{statuses.map((item) => <option value={item} key={item}>{t(`package.status.${item}`)}</option>)}</select><button type="button" className={`package-updates ${updatesActive ? "active" : ""}`} aria-pressed={updatesActive} onClick={onUpdates}>{t("package.updatesCount").replace("{count}", String(updates))}</button><button type="button" onClick={onRefresh}><RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />{t("action.refresh")}</button></header>;
}
