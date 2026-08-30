import { useEffect, useState } from "react";
import { api, type ProxmoxNode } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { bytes, duration, percent } from "./utils";

export function ProxmoxNodes({ refreshKey, t, toast }: { refreshKey: number; t: Translate; toast: ToastFn }) {
  const [nodes, setNodes] = useState<ProxmoxNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<ProxmoxNode | null>(null);
  const [details, setDetails] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    setLoading(true);
    void api.proxmoxNodes().then((result) => setNodes(result.nodes)).catch((error) => {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }).finally(() => setLoading(false));
  }, [refreshKey, t, toast]);

  async function open(item: ProxmoxNode) {
    setSelected(item);
    setDetails(null);
    try {
      setDetails(await api.proxmoxNodeDetails(item.connection_id, item.node));
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }
  }

  return <>
    <section className="module-info">
      <header className="module-section-toolbar"><div><h3>Nodes</h3><p>Live node health read from the Proxmox REST API.</p></div></header>
      {loading && !nodes.length ? <div className="loading-state">{t("common.loading")}</div> : <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Node</th><th>Status</th><th>Uptime</th><th>CPU</th><th>RAM</th><th>Storage</th><th>Version</th><th>Guests</th></tr></thead><tbody>{nodes.map((item) => <tr key={`${item.connection_id}:${item.node}`} onClick={() => void open(item)}>
        <td><strong>{item.node}</strong><br /><small>{item.connection_name}</small></td>
        <td><span className={`status-badge ${item.status === "online" ? "ok" : "neutral"}`}>{item.status}</span></td>
        <td>{duration(item.uptime)}</td>
        <td>{percent(item.cpu)}<br /><small>{item.maxcpu || "—"} CPU</small></td>
        <td>{bytes(item.mem)} / {bytes(item.maxmem)}</td>
        <td>{bytes(item.storage_used)} / {bytes(item.storage_total)}</td>
        <td>{item.proxmox_version || "—"}<br /><small>{item.kernel || ""}</small></td>
        <td>{item.vms} VM · {item.lxc} LXC</td>
      </tr>)}</tbody></table>{!nodes.length && <div className="empty-state"><strong>No Proxmox nodes found.</strong></div>}</div>}
    </section>
    {selected && <Modal title={`Node: ${selected.node}`} onClose={() => setSelected(null)} wide footer={<button type="button" onClick={() => setSelected(null)}>{t("action.close")}</button>}>
      {!details ? <div className="loading-state">{t("common.loading")}</div> : <>
        <dl>
          <dt>Status</dt><dd>{selected.status}</dd>
          <dt>Load average</dt><dd>{selected.load_average.join(" · ") || "—"}</dd>
          <dt>Kernel</dt><dd>{selected.kernel || "—"}</dd>
          <dt>Proxmox</dt><dd>{selected.proxmox_version || "—"}</dd>
        </dl>
        {(["network", "dns", "subscription", "repositories", "services"] as const).map((key) => <section className="module-info" key={key}><h4>{key}</h4><pre>{JSON.stringify(details[key] ?? null, null, 2)}</pre></section>)}
      </>}
    </Modal>}
  </>;
}
