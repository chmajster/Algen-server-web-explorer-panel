import { RefreshCw, Search } from "lucide-react";
import type { Translate } from "../../app/types";

export function PackageToolbar({ search, category, status, categories, updates, loading, t, onSearch, onCategory, onStatus, onRefresh }: {
  search: string; category: string; status: string; categories: string[]; updates: number; loading: boolean; t: Translate;
  onSearch: (value: string) => void; onCategory: (value: string) => void; onStatus: (value: string) => void; onRefresh: () => void;
}) {
  const statuses = ["available", "installing", "installed", "running", "stopped", "update_available", "error", "incompatible", "blocked", "reboot_required"];
  return <header className="package-toolbar"><label className="package-search"><Search /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("package.search")} aria-label={t("package.search")} /></label><select aria-label={t("package.category")} value={category} onChange={(event) => onCategory(event.target.value)}><option value="">{t("package.allCategories")}</option>{categories.map((item) => <option value={item} key={item}>{t(`package.category.${item}`)}</option>)}</select><select aria-label={t("package.status")} value={status} onChange={(event) => onStatus(event.target.value)}><option value="">{t("package.allStatuses")}</option>{statuses.map((item) => <option value={item} key={item}>{t(`package.status.${item}`)}</option>)}</select><span className="package-updates">{t("package.updatesCount").replace("{count}", String(updates))}</span><button type="button" onClick={onRefresh}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></header>;
}
