import { useEffect, useState } from "react";
import { api, type ProxmoxCluster } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";

export function ProxmoxClusterView({ refreshKey, t, toast }: { refreshKey: number; t: Translate; toast: ToastFn }) {
  const [items, setItems] = useState<ProxmoxCluster[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    void api.proxmoxCluster().then((result) => setItems(result.clusters)).catch((error) => {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }).finally(() => setLoading(false));
  }, [refreshKey, t, toast]);

  return <section className="module-info">
    <header className="module-section-toolbar"><div><h3>Cluster</h3><p>Monitoring-only cluster, quorum and HA visibility.</p></div></header>
    {loading && !items.length ? <div className="loading-state">{t("common.loading")}</div> : items.map((item) => <article className="module-info" key={item.connection_id}>
      <h4>{item.name} <span className={`status-badge ${item.quorate ? "ok" : "neutral"}`}>{item.quorate ? "quorate" : "no quorum"}</span></h4>
      <dl>
        <dt>Connection</dt><dd>{item.connection_name}</dd>
        <dt>Nodes</dt><dd>{item.online_nodes} online / {item.nodes.length} total</dd>
        <dt>Votes</dt><dd>{item.votes}</dd>
        <dt>HA resources</dt><dd>{item.ha_resources.length}</dd>
        <dt>HA groups</dt><dd>{item.ha_groups.length}</dd>
      </dl>
      <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Node</th><th>Status</th><th>Votes</th><th>Node ID</th></tr></thead><tbody>{item.nodes.map((node, index) => <tr key={`${item.connection_id}:${String(node.name || node.node || index)}`}><td>{String(node.name || node.node || "—")}</td><td>{String(node.status || (node.online ? "online" : "offline"))}</td><td>{String(node.votes ?? "—")}</td><td>{String(node.nodeid ?? node.id ?? "—")}</td></tr>)}</tbody></table></div>
      {Object.keys(item.errors).length > 0 && <p>{Object.entries(item.errors).map(([key, value]) => `${key}: ${value}`).join(" · ")}</p>}
    </article>)}
    {!loading && !items.length && <div className="empty-state"><strong>No cluster information available.</strong></div>}
  </section>;
}
