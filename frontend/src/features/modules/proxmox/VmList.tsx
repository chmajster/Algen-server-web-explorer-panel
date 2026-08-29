import { Play, Power, RotateCcw, Square } from "lucide-react";
import { useMemo, useState } from "react";
import { api, type ProxmoxConnection, type ProxmoxVm } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { CreateVmDialog } from "./dialogs/CreateVmDialog";
import { VmDetails } from "./VmDetails";
import { bytes, duration, percent } from "./utils";

type PowerAction = "start" | "stop" | "shutdown" | "reboot";

function PowerDialog({ vm, action, busy, t, onClose, onConfirm }: { vm: ProxmoxVm; action: PowerAction; busy: boolean; t: Translate; onClose: () => void; onConfirm: (confirmation: string) => void }) {
  const dangerous = action !== "start";
  const [confirmation, setConfirmation] = useState("");
  return <Modal title={`${action}: ${vm.name}`} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className={dangerous ? "button-danger" : "button-primary"} type="button" disabled={busy || (dangerous && confirmation !== vm.name)} onClick={() => onConfirm(dangerous ? confirmation : "")}>{action}</button></>}>
    <p>{vm.name} · VMID {vm.vmid} · {vm.node}</p>
    {dangerous && <label className="field-label">Confirm exact VM name<input autoFocus value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={vm.name} /></label>}
  </Modal>;
}

export function ProxmoxVmList({ vms, connections, permissions, t, toast, onChanged }: { vms: ProxmoxVm[]; connections: ProxmoxConnection[]; permissions: string[]; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [search, setSearch] = useState("");
  const [node, setNode] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [tag, setTag] = useState("");
  const [sort, setSort] = useState<"name" | "vmid" | "node" | "status">("name");
  const [selected, setSelected] = useState<ProxmoxVm | null>(null);
  const [powerDialog, setPowerDialog] = useState<{ vm: ProxmoxVm; action: PowerAction } | null>(null);
  const [busyVm, setBusyVm] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const canManage = permissions.includes("hosts-manager.hosts.manage");
  const canStart = permissions.includes("hosts-manager.power.on");
  const canShutdown = permissions.includes("hosts-manager.power.shutdown");
  const canReboot = permissions.includes("hosts-manager.power.reboot");
  const nodes = useMemo(() => [...new Set(vms.map((item) => item.node).filter(Boolean))].sort(), [vms]);
  const tags = useMemo(() => [...new Set(vms.flatMap((item) => item.tags))].sort(), [vms]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return vms.filter((item) => {
      if (needle && !`${item.name} ${item.vmid} ${item.connection_name} ${item.host_address || ""}`.toLocaleLowerCase().includes(needle)) return false;
      if (node && item.node !== node) return false;
      if (type && item.type !== type) return false;
      if (status && item.status !== status) return false;
      if (tag && !item.tags.includes(tag)) return false;
      return true;
    }).sort((left, right) => sort === "vmid" ? left.vmid - right.vmid : String(left[sort]).localeCompare(String(right[sort])));
  }, [node, search, sort, status, tag, type, vms]);

  async function power(vm: ProxmoxVm, action: PowerAction, confirmationText: string) {
    setBusyVm(`${vm.connection_id}:${vm.vmid}`);
    try {
      await api.proxmoxVmPower(vm.connection_id, vm.vmid, action, confirmationText);
      setPowerDialog(null);
      await onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setBusyVm("");
    }
  }

  return <>
    <section className="module-info">
      <header className="module-section-toolbar"><div><h3>Virtual Machines</h3><p>Live VM/LXC inventory linked to Host Registry.</p></div>{canManage && <button className="button-primary" type="button" onClick={() => setCreateOpen(true)}>Create VM</button>}</header>
      <div className="module-section-toolbar">
        <input aria-label="Search VM" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, VMID, connection or IP" />
        <select aria-label="Filter node" value={node} onChange={(event) => setNode(event.target.value)}><option value="">All nodes</option>{nodes.map((item) => <option key={item} value={item}>{item}</option>)}</select>
        <select aria-label="Filter type" value={type} onChange={(event) => setType(event.target.value)}><option value="">VM + LXC</option><option value="qemu">VM</option><option value="lxc">LXC</option></select>
        <select aria-label="Filter status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="running">running</option><option value="stopped">stopped</option></select>
        <select aria-label="Filter tag" value={tag} onChange={(event) => setTag(event.target.value)}><option value="">All tags</option>{tags.map((item) => <option key={item} value={item}>{item}</option>)}</select>
        <select aria-label="Sort" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="name">Sort: name</option><option value="vmid">Sort: VMID</option><option value="node">Sort: node</option><option value="status">Sort: status</option></select>
      </div>
      <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Name</th><th>VMID</th><th>Type</th><th>Status</th><th>Node</th><th>IP</th><th>Uptime</th><th>CPU</th><th>RAM</th><th>Disk</th><th>Tags</th><th>Host Registry</th><th>Actions</th></tr></thead><tbody>{filtered.map((vm) => {
        const busy = busyVm === `${vm.connection_id}:${vm.vmid}`;
        return <tr key={`${vm.connection_id}:${vm.vmid}`} onClick={() => setSelected(vm)}>
          <td><strong>{vm.name}</strong><br /><small>{vm.connection_name}</small></td><td><code>{vm.vmid}</code></td><td>{vm.type === "qemu" ? "VM" : "LXC"}</td>
          <td><span className={`status-badge ${vm.status === "running" ? "ok" : "neutral"}`}>{vm.status}</span></td><td>{vm.node}</td><td>{vm.host_address || "—"}</td><td>{duration(vm.uptime)}</td>
          <td>{percent(vm.cpu)}<br /><small>{vm.maxcpu || "—"} CPU</small></td><td>{bytes(vm.mem)} / {bytes(vm.maxmem)}</td><td>{bytes(vm.disk)} / {bytes(vm.maxdisk)}</td><td>{vm.tags.join(" · ") || "—"}</td>
          <td>{vm.host_id ? <><code>{vm.host_id}</code><br /><small>{vm.host_active ? "active" : "inactive"}</small></> : "not synchronized"}</td>
          <td onClick={(event) => event.stopPropagation()}><div className="module-row-actions">
            {canStart && vm.status !== "running" && <button type="button" title="Start" disabled={busy} onClick={() => setPowerDialog({ vm, action: "start" })}><Play /></button>}
            {canShutdown && vm.status === "running" && <button type="button" title="Shutdown" disabled={busy} onClick={() => setPowerDialog({ vm, action: "shutdown" })}><Power /></button>}
            {canReboot && vm.status === "running" && <button type="button" title="Reboot" disabled={busy} onClick={() => setPowerDialog({ vm, action: "reboot" })}><RotateCcw /></button>}
            {canShutdown && vm.status === "running" && <button className="danger" type="button" title="Stop" disabled={busy} onClick={() => setPowerDialog({ vm, action: "stop" })}><Square /></button>}
          </div></td>
        </tr>;
      })}</tbody></table>{!filtered.length && <div className="empty-state"><strong>No virtual machines match the current filters.</strong></div>}</div>
    </section>
    {selected && <VmDetails vm={selected} canManage={canManage} t={t} toast={toast} onClose={() => setSelected(null)} onChanged={onChanged} />}
    {powerDialog && <PowerDialog vm={powerDialog.vm} action={powerDialog.action} busy={busyVm === `${powerDialog.vm.connection_id}:${powerDialog.vm.vmid}`} t={t} onClose={() => setPowerDialog(null)} onConfirm={(text) => void power(powerDialog.vm, powerDialog.action, text)} />}
    {createOpen && <CreateVmDialog connections={connections} t={t} toast={toast} onClose={() => setCreateOpen(false)} onDone={onChanged} />}
  </>;
}
