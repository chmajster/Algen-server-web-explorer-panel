import { useState } from "react";
import { api, type ProxmoxVm, type ProxmoxVmDetails } from "../../../../api";
import type { ToastFn, Translate } from "../../../../app/types";
import { Modal } from "../../../../components/Modal";

function failure(error: unknown, t: Translate): string {
  return error instanceof Error ? error.message : t("error.generic");
}

export function SnapshotDialog({ vm, t, toast, onClose, onDone }: { vm: ProxmoxVm; t: Translate; toast: ToastFn; onClose: () => void; onDone: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [includeRam, setIncludeRam] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await api.createProxmoxSnapshot(vm.connection_id, vm.vmid, { name, description, include_ram: includeRam });
      await onDone();
      onClose();
    } catch (error) {
      toast(failure(error, t), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Create snapshot: ${vm.name}`} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="button" disabled={busy || !name.trim()} onClick={() => void submit()}>Create snapshot</button></>}>
    <label className="field-label">Snapshot name<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="before-upgrade" /></label>
    <label className="field-label">Description<textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    {vm.type === "qemu" && <label><input type="checkbox" checked={includeRam} onChange={(event) => setIncludeRam(event.target.checked)} /> Include VM state/RAM</label>}
  </Modal>;
}

export function ConfirmVmDialog({ title, vm, busy, t, onClose, onConfirm }: { title: string; vm: ProxmoxVm; busy: boolean; t: Translate; onClose: () => void; onConfirm: () => void }) {
  const [confirmation, setConfirmation] = useState("");
  return <Modal title={`${title}: ${vm.name}`} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-danger" type="button" disabled={busy || confirmation !== vm.name} onClick={onConfirm}>{title}</button></>}>
    <p>This operation can change or destroy VM state. Type the exact VM name to continue.</p>
    <label className="field-label">VM name<input autoFocus value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={vm.name} /></label>
  </Modal>;
}

export function CloneDialog({ vm, t, toast, onClose, onDone }: { vm: ProxmoxVm; t: Translate; toast: ToastFn; onClose: () => void; onDone: () => Promise<void> }) {
  const [newVmid, setNewVmid] = useState(String(vm.vmid + 1));
  const [name, setName] = useState(`${vm.name}-clone`);
  const [targetNode, setTargetNode] = useState(vm.node);
  const [storage, setStorage] = useState("");
  const [pool, setPool] = useState("");
  const [full, setFull] = useState(true);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await api.cloneProxmoxVm(vm.connection_id, vm.vmid, {
        new_vmid: Number(newVmid), name, full, target_node: targetNode,
        target_storage: storage, pool, sync_to_host_registry: true,
      });
      await onDone();
      onClose();
    } catch (error) {
      toast(failure(error, t), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Clone VM: ${vm.name}`} onClose={onClose} wide footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="button" disabled={busy || !name.trim() || !Number(newVmid)} onClick={() => void submit()}>Clone</button></>}>
    <label className="field-label">New VMID<input type="number" min={100} value={newVmid} onChange={(event) => setNewVmid(event.target.value)} /></label>
    <label className="field-label">Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
    <label className="field-label">Target node<input value={targetNode} onChange={(event) => setTargetNode(event.target.value)} /></label>
    <label className="field-label">Target storage<input value={storage} onChange={(event) => setStorage(event.target.value)} placeholder="optional" /></label>
    <label className="field-label">Pool<input value={pool} onChange={(event) => setPool(event.target.value)} placeholder="optional" /></label>
    <label><input type="checkbox" checked={full} onChange={(event) => setFull(event.target.checked)} /> Full clone</label>
  </Modal>;
}

export function MigrationDialog({ vm, t, toast, onClose, onDone }: { vm: ProxmoxVm; t: Translate; toast: ToastFn; onClose: () => void; onDone: () => Promise<void> }) {
  const [targetNode, setTargetNode] = useState("");
  const [storage, setStorage] = useState("");
  const [network, setNetwork] = useState("");
  const [online, setOnline] = useState(vm.type === "qemu" && vm.status === "running");
  const [localDisks, setLocalDisks] = useState(true);
  const [confirmation, setConfirmation] = useState("");
  const [validation, setValidation] = useState<{ valid: boolean; issues: string[]; warnings: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const payload = {
    target_node: targetNode, target_storage: storage, online,
    with_local_disks: localDisks, migration_network: network,
    confirm: false, confirmation_text: "",
  };

  async function validate() {
    setBusy(true);
    try {
      setValidation(await api.validateProxmoxMigration(vm.connection_id, vm.vmid, payload));
    } catch (error) {
      toast(failure(error, t), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    setBusy(true);
    try {
      await api.migrateProxmoxVm(vm.connection_id, vm.vmid, { ...payload, confirm: true, confirmation_text: confirmation });
      await onDone();
      onClose();
    } catch (error) {
      toast(failure(error, t), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Migrate: ${vm.name}`} onClose={onClose} wide footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button type="button" disabled={busy || !targetNode} onClick={() => void validate()}>Validate</button><button className="button-danger" type="button" disabled={busy || !validation?.valid || confirmation !== vm.name} onClick={() => void execute()}>Execute</button></>}>
    <label className="field-label">Destination node<input autoFocus value={targetNode} onChange={(event) => { setTargetNode(event.target.value); setValidation(null); }} /></label>
    <label className="field-label">Target storage<input value={storage} onChange={(event) => { setStorage(event.target.value); setValidation(null); }} placeholder="optional" /></label>
    {vm.type === "qemu" && <><label><input type="checkbox" checked={online} onChange={(event) => { setOnline(event.target.checked); setValidation(null); }} /> Online migration</label><br /><label><input type="checkbox" checked={localDisks} onChange={(event) => { setLocalDisks(event.target.checked); setValidation(null); }} /> Migrate local disks</label><label className="field-label">Migration network<input value={network} onChange={(event) => { setNetwork(event.target.value); setValidation(null); }} placeholder="optional CIDR/network" /></label></>}
    {validation && <section className="module-info"><strong>{validation.valid ? "Validation passed" : "Validation failed"}</strong>{validation.issues.map((item) => <p key={item}>{item}</p>)}{validation.warnings.map((item) => <p key={item}>{item}</p>)}</section>}
    <label className="field-label">Confirm exact VM name<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={vm.name} /></label>
  </Modal>;
}

export function HardwareDialog({ vm, details, t, toast, onClose, onDone }: { vm: ProxmoxVm; details: ProxmoxVmDetails; t: Translate; toast: ToastFn; onClose: () => void; onDone: () => Promise<void> }) {
  const [cores, setCores] = useState(String(details.hardware.cores || vm.maxcpu || 1));
  const [sockets, setSockets] = useState(String(details.hardware.sockets || 1));
  const [memory, setMemory] = useState(String(details.hardware.memory_mb || Math.round(vm.maxmem / 1024 / 1024)));
  const [balloon, setBalloon] = useState(String(details.hardware.balloon_mb || 0));
  const [confirmation, setConfirmation] = useState("");
  const [plan, setPlan] = useState<Array<{ field: string; current: number; new: number }> | null>(null);
  const [busy, setBusy] = useState(false);

  const payload = { cores: Number(cores), sockets: Number(sockets), memory_mb: Number(memory), balloon_mb: Number(balloon), confirm: false, confirmation_text: "" };

  async function preview() {
    setBusy(true);
    try {
      const result = await api.planProxmoxHardware(vm.connection_id, vm.vmid, payload);
      setPlan(result.changes);
    } catch (error) {
      toast(failure(error, t), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setBusy(true);
    try {
      await api.updateProxmoxHardware(vm.connection_id, vm.vmid, { ...payload, confirm: true, confirmation_text: confirmation });
      await onDone();
      onClose();
    } catch (error) {
      toast(failure(error, t), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  return <Modal title={`Hardware: ${vm.name}`} onClose={onClose} wide footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button type="button" disabled={busy} onClick={() => void preview()}>Preview changes</button><button className="button-primary" type="button" disabled={busy || !plan?.length || confirmation !== vm.name} onClick={() => void apply()}>Apply</button></>}>
    <label className="field-label">Cores<input type="number" min={1} value={cores} onChange={(event) => { setCores(event.target.value); setPlan(null); }} /></label>
    <label className="field-label">Sockets<input type="number" min={1} value={sockets} onChange={(event) => { setSockets(event.target.value); setPlan(null); }} /></label>
    <label className="field-label">RAM (MiB)<input type="number" min={128} value={memory} onChange={(event) => { setMemory(event.target.value); setPlan(null); }} /></label>
    <label className="field-label">Balloon (MiB)<input type="number" min={0} value={balloon} onChange={(event) => { setBalloon(event.target.value); setPlan(null); }} /></label>
    {plan && <section className="module-info"><h4>Current → New</h4>{plan.length ? plan.map((item) => <p key={item.field}><strong>{item.field}</strong>: {item.current} → {item.new}</p>) : <p>No changes.</p>}</section>}
    <label className="field-label">Confirm exact VM name<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={vm.name} /></label>
  </Modal>;
}
