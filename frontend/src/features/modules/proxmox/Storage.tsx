import { useEffect, useState } from "react";
import { api, type ProxmoxStorage } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { bytes, percent } from "./utils";

export function ProxmoxStorageView({ refreshKey, t, toast }: { refreshKey: number; t: Translate; toast: ToastFn }) {
  const [items, setItems] = useState<ProxmoxStorage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    void api.proxmoxStorage().then((result) => setItems(result.storage)).catch((error) => {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }).finally(() => setLoading(false));
  }, [refreshKey, t, toast]);

  return <section className="module-info">
    <header className="module-section-toolbar"><div><h3>Storage</h3><p>Read-only Proxmox storage capacity and content visibility.</p></div></header>
    {loading && !items.length ? <div className="loading-state">{t("common.loading")}</div> : <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Storage</th><th>Node</th><th>Type</th><th>Status</th><th>Used</th><th>Free</th><th>Utilization</th><th>Scope</th><th>Content</th></tr></thead><tbody>{items.map((item) => <tr key={`${item.connection_id}:${item.node}:${item.storage}`}>
      <td><strong>{item.storage}</strong><br /><small>{item.connection_name}</small></td>
      <td>{item.node}</td>
      <td>{item.type || "—"}</td>
      <td><span className={`status-badge ${item.status === "available" ? "ok" : "neutral"}`}>{item.status}</span></td>
      <td>{bytes(item.used)} / {bytes(item.total)}</td>
      <td>{bytes(item.free)}</td>
      <td>{percent(item.utilization)}</td>
      <td>{item.shared ? "shared" : "local"}</td>
      <td>{item.content || "—"}</td>
    </tr>)}</tbody></table>{!items.length && <div className="empty-state"><strong>No storage found.</strong></div>}</div>}
  </section>;
}
