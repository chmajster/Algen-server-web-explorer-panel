import { useCallback, useEffect, useState } from "react";
import { api, type ProxmoxSnapshot, type ProxmoxTask, type ProxmoxVm, type ProxmoxVmDetails } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { bytes, duration, percent } from "./utils";
import { CloneDialog, ConfirmVmDialog, HardwareDialog, MigrationDialog, SnapshotDialog } from "./dialogs/OperationDialogs";

type DetailTab = "overview" | "hardware" | "network" | "snapshots" | "tasks" | "host-registry";
type DialogState = "snapshot" | "clone" | "migration" | "hardware" | { action: "delete-snapshot" | "rollback-snapshot"; snapshot: string } | null;

export function VmDetails({ vm, canManage, t, toast, onClose, onChanged }: { vm: ProxmoxVm; canManage: boolean; t: Translate; toast: ToastFn; onClose: () => void; onChanged: () => Promise<void> }) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [details, setDetails] = useState<ProxmoxVmDetails | null>(null);
  const [snapshots, setSnapshots] = useState<ProxmoxSnapshot[]>([]);
  const [tasks, setTasks] = useState<ProxmoxTask[]>([]);
  const [backups, setBackups] = useState<Array<Record<string, unknown>>>([]);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [detail, snapshotResult, taskResult, backupResult] = await Promise.all([
      api.proxmoxVmDetails(vm.connection_id, vm.vmid),
      api.proxmoxVmSnapshots(vm.connection_id, vm.vmid).catch(() => ({ snapshots: [] })),
      api.proxmoxTasks(vm.connection_id, false, 100).catch(() => ({ tasks: [], total: 0 })),
      api.proxmoxVmBackups(vm.connection_id, vm.vmid).catch(() => ({ backups: [], errors: [], total: 0 })),
    ]);
    setDetails(detail);
    setSnapshots(snapshotResult.snapshots);
    setTasks(taskResult.tasks.filter((item) => item.vmid === vm.vmid));
    setBackups(backupResult.backups);
  }, [vm.connection_id, vm.vmid]);

  useEffect(() => {
    void refresh().catch((error) => toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager"));
  }, [refresh, t, toast]);

  useEffect(() => {
    if (!tasks.some((item) => item.status === "Queued" || item.status === "Running")) return undefined;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [refresh, tasks]);

  async function changed() {
    await refresh();
    await onChanged();
  }

  async function destructiveSnapshot(action: "delete-snapshot" | "rollback-snapshot", snapshot: string) {
    setBusy(true);
    try {
      if (action === "delete-snapshot") await api.deleteProxmoxSnapshot(vm.connection_id, vm.vmid, snapshot, vm.name);
      else await api.rollbackProxmoxSnapshot(vm.connection_id, vm.vmid, snapshot, vm.name);
      setDialog(null);
      await changed();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  const tabs: Array<{ id: DetailTab; label: string }> = [
    { id: "overview", label: "Overview" }, { id: "hardware", label: "Hardware" }, { id: "network", label: "Network" },
    { id: "snapshots", label: "Snapshots" }, { id: "tasks", label: "Tasks" }, { id: "host-registry", label: "Host Registry" },
  ];

  return <>
    <Modal title={`${vm.name} · VMID ${vm.vmid}`} onClose={onClose} wide footer={<button type="button" onClick={onClose}>{t("action.close")}</button>}>
      {!details ? <div className="loading-state">{t("common.loading")}</div> : <>
        <div className="module-section-toolbar">
          <div className="module-row-actions">{tabs.map((item) => <button type="button" className={tab === item.id ? "button-primary" : ""} key={item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</div>
          {canManage && <div className="module-row-actions"><button type="button" onClick={() => setDialog("snapshot")}>Snapshot</button><button type="button" onClick={() => setDialog("clone")}>Clone</button><button type="button" onClick={() => setDialog("migration")}>Migrate</button><button type="button" onClick={() => setDialog("hardware")}>Edit hardware</button></div>}
        </div>
        {tab === "overview" && <section className="module-info"><dl>
          <dt>Status</dt><dd><span className={`status-badge ${details.status === "running" ? "ok" : "neutral"}`}>{details.status}</span></dd>
          <dt>Connection</dt><dd>{details.connection_name}</dd><dt>Node</dt><dd>{details.node}</dd><dt>VMID</dt><dd>{details.vmid}</dd>
          <dt>Type</dt><dd>{details.type === "qemu" ? "QEMU VM" : "LXC"}</dd><dt>Uptime</dt><dd>{duration(details.uptime)}</dd>
          <dt>OS</dt><dd>{typeof details.os === "string" ? details.os : JSON.stringify(details.os)}</dd><dt>IP</dt><dd>{details.host_address || "—"}</dd>
          <dt>CPU</dt><dd>{percent(details.cpu)} · {details.maxcpu} CPU</dd><dt>RAM</dt><dd>{bytes(details.mem)} / {bytes(details.maxmem)}</dd>
          <dt>Disk</dt><dd>{bytes(details.disk)} / {bytes(details.maxdisk)}</dd><dt>QEMU Guest Agent</dt><dd>{details.type === "qemu" ? details.qemu_guest_agent ? "available" : "unavailable" : "not applicable"}</dd>
          <dt>Tags</dt><dd>{details.tags.join(" · ") || "—"}</dd><dt>Template</dt><dd>{details.template ? "yes" : "no"}</dd>
          <dt>Host Registry host_id</dt><dd>{details.host_id || "—"}</dd>
        </dl><h4>Backup visibility</h4>{backups.length ? backups.map((item) => <p key={String(item.volid)}>{String(item.backup)} · {bytes(Number(item.size || 0))} · {new Date(Number(item.date || 0) * 1000).toLocaleString()} · {String(item.storage)}</p>) : <p>No matching backups found.</p>}</section>}
        {tab === "hardware" && <section className="module-info"><dl>
          <dt>Cores</dt><dd>{details.hardware.cores}</dd><dt>Sockets</dt><dd>{details.hardware.sockets}</dd><dt>CPU type</dt><dd>{details.hardware.cpu_type || "—"}</dd>
          <dt>RAM</dt><dd>{details.hardware.memory_mb} MiB</dd><dt>Balloon</dt><dd>{details.hardware.balloon_mb} MiB</dd><dt>Machine</dt><dd>{details.hardware.machine || "—"}</dd><dt>BIOS</dt><dd>{details.hardware.bios || "—"}</dd>
        </dl><h4>Disks</h4><div className="module-table-wrap"><table className="module-table"><thead><tr><th>Device</th><th>Storage</th><th>Size</th><th>Cache</th><th>Discard</th><th>IO thread</th></tr></thead><tbody>{details.hardware.disks.map((disk) => <tr key={disk.device}><td>{disk.device}</td><td>{disk.storage || "—"}</td><td>{disk.size || "—"}</td><td>{disk.cache || "—"}</td><td>{disk.discard || "—"}</td><td>{disk.iothread || "—"}</td></tr>)}</tbody></table></div></section>}
        {tab === "network" && <section className="module-info"><h4>Configured adapters</h4><div className="module-table-wrap"><table className="module-table"><thead><tr><th>Device</th><th>Model</th><th>MAC</th><th>Bridge</th><th>VLAN</th></tr></thead><tbody>{details.hardware.network_adapters.map((nic) => <tr key={nic.device}><td>{nic.device}</td><td>{nic.model || "—"}</td><td>{nic.mac || "—"}</td><td>{nic.bridge || "—"}</td><td>{nic.vlan || "—"}</td></tr>)}</tbody></table></div><h4>Guest network</h4><pre>{JSON.stringify(details.guest_network, null, 2)}</pre></section>}
        {tab === "snapshots" && <section className="module-info"><header className="module-section-toolbar"><h4>Snapshots</h4>{canManage && <button type="button" onClick={() => setDialog("snapshot")}>Create snapshot</button>}</header><div className="module-table-wrap"><table className="module-table"><thead><tr><th>Name</th><th>Created</th><th>Description</th><th>RAM</th><th>Actions</th></tr></thead><tbody>{snapshots.filter((item) => !item.current).map((item) => <tr key={item.name}><td><strong>{item.name}</strong></td><td>{item.date ? new Date(item.date * 1000).toLocaleString() : "—"}</td><td>{item.description || "—"}</td><td>{item.vmstate ? "yes" : "no"}</td><td><div className="module-row-actions">{canManage && <><button type="button" onClick={() => setDialog({ action: "rollback-snapshot", snapshot: item.name })}>Rollback</button><button className="danger" type="button" onClick={() => setDialog({ action: "delete-snapshot", snapshot: item.name })}>Delete</button></>}</div></td></tr>)}</tbody></table>{!snapshots.filter((item) => !item.current).length && <div className="empty-state"><strong>No snapshots.</strong></div>}</div></section>}
        {tab === "tasks" && <section className="module-info"><div className="module-table-wrap"><table className="module-table"><thead><tr><th>Action</th><th>Status</th><th>Progress</th><th>Exit status</th><th>UPID</th></tr></thead><tbody>{tasks.map((item) => <tr key={item.upid}><td>{item.action}</td><td>{item.status}</td><td>{item.progress}%</td><td>{item.exitstatus || "—"}</td><td><code>{item.upid}</code></td></tr>)}</tbody></table>{!tasks.length && <div className="empty-state"><strong>No tasks for this VM.</strong></div>}</div></section>}
        {tab === "host-registry" && <section className="module-info"><dl><dt>host_id</dt><dd>{details.host_id || "not synchronized"}</dd><dt>Address</dt><dd>{details.host_address || "—"}</dd><dt>Active</dt><dd>{details.host_active ? "yes" : "no"}</dd><dt>Approved</dt><dd>{details.host_approved ? "yes" : "no"}</dd><dt>User tags</dt><dd>{details.host_tags.join(" · ") || "—"}</dd></dl><p>Identity is VMID + Proxmox connection. Node changes caused by migration do not create a new Host Registry object.</p></section>}
      </>}
    </Modal>
    {dialog === "snapshot" && <SnapshotDialog vm={vm} t={t} toast={toast} onClose={() => setDialog(null)} onDone={changed} />}
    {dialog === "clone" && <CloneDialog vm={vm} t={t} toast={toast} onClose={() => setDialog(null)} onDone={changed} />}
    {dialog === "migration" && <MigrationDialog vm={vm} t={t} toast={toast} onClose={() => setDialog(null)} onDone={changed} />}
    {dialog === "hardware" && details && <HardwareDialog vm={vm} details={details} t={t} toast={toast} onClose={() => setDialog(null)} onDone={changed} />}
    {typeof dialog === "object" && dialog && <ConfirmVmDialog title={dialog.action === "delete-snapshot" ? "Delete snapshot" : "Rollback snapshot"} vm={vm} busy={busy} t={t} onClose={() => setDialog(null)} onConfirm={() => void destructiveSnapshot(dialog.action, dialog.snapshot)} />}
  </>;
}
