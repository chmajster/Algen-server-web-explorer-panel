import type { Translate } from "../../app/types";
import type { PackageHistoryItem } from "./types";

export function PackageHistory({ history, t }: { history: PackageHistoryItem[]; t: Translate }) {
  return <div className="package-history">{history.length ? history.map((item) => <article key={item.id}><strong>{item.module_id}</strong><span>{t(`store.${item.action}`)}</span><span className={`package-status ${item.status}`}>{t(`task.${item.status}`)}</span><time>{new Date(item.created_at * 1000).toLocaleString()}</time><small>{item.message}</small></article>) : <div className="empty-state"><strong>{t("package.noHistory")}</strong></div>}</div>;
}
