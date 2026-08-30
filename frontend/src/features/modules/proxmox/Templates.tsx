import { useCallback, useEffect, useState } from "react";
import { api, type ProxmoxVm } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { CloneDialog } from "./dialogs/OperationDialogs";
import { VmDetails } from "./VmDetails";
import { bytes } from "./utils";

function normalizeTemplate(item: ProxmoxVm): ProxmoxVm {
  return {
    connection_id: item.connection_id,
    connection_name: item.connection_name,
    vmid: item.vmid,
    name: item.name,
    node: item.node,
    type: item.type,
    status: item.status || "stopped",
    template: true,
    uptime: item.uptime || 0,
    cpu: item.cpu || 0,
    maxcpu: item.maxcpu || 0,
    mem: item.mem || 0,
    maxmem: item.maxmem || 0,
    disk: item.disk || 0,
    maxdisk: item.maxdisk || 0,
    tags: item.tags || [],
    sync_state: "not_synced",
  };
}

export function ProxmoxTemplates({ canManage, refreshKey, t, toast, onChanged }: { canManage: boolean; refreshKey: number; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [items, setItems] = useState<ProxmoxVm[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<ProxmoxVm | null>(null);
  const [clone, setClone] = useState<ProxmoxVm | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.proxmoxTemplates();
      setItems(result.templates.map(normalizeTemplate));
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useEffect(() => { void refresh(); }, [refresh, refreshKey]);

  return <>
    <section className="module-info">
      <header className="module-section-toolbar"><div><h3>Templates</h3><p>Live QEMU/LXC templates from Proxmox. Template metadata is not persisted locally.</p></div></header>
      {loading && !items.length ? <div className="loading-state">{t("common.loading")}</div> : <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Name</th><th>VMID</th><th>Type</th><th>Node</th><th>Connection</th><th>CPU</th><th>RAM</th><th>Disk</th><th>Tags</th><th>Actions</th></tr></thead><tbody>{items.map((item) => <tr key={`${item.connection_id}:${item.vmid}`}>
        <td><strong>{item.name}</strong></td><td><code>{item.vmid}</code></td><td>{item.type === "qemu" ? "QEMU" : "LXC"}</td><td>{item.node || "—"}</td><td>{item.connection_name}</td><td>{item.maxcpu || "—"}</td><td>{bytes(item.maxmem || 0)}</td><td>{bytes(item.maxdisk || 0)}</td><td>{item.tags.join(" · ") || "—"}</td>
        <td><div className="module-row-actions"><button type="button" onClick={() => setSelected(item)}>View configuration</button>{canManage && <button type="button" onClick={() => setClone(item)}>Clone</button>}</div></td>
      </tr>)}</tbody></table>{!items.length && <div className="empty-state"><strong>No QEMU/LXC templates found.</strong></div>}</div>}
    </section>
    {selected && <VmDetails vm={selected} canManage={canManage} t={t} toast={toast} onClose={() => setSelected(null)} onChanged={async () => { await refresh(); await onChanged(); }} />}
    {clone && <CloneDialog vm={clone} t={t} toast={toast} onClose={() => setClone(null)} onDone={async () => { await refresh(); await onChanged(); }} />}
  </>;
}
