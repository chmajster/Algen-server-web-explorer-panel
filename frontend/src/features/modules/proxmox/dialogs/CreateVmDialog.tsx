import { useState } from "react";
import { api, type ProxmoxConnection } from "../../../../api";
import type { ToastFn, Translate } from "../../../../app/types";
import { Modal } from "../../../../components/Modal";

const steps = ["General", "OS / template", "CPU", "Memory", "Disk", "Network", "Cloud-init", "Review"] as const;

export function CreateVmDialog({ connections, t, toast, onClose, onDone }: { connections: ProxmoxConnection[]; t: Translate; toast: ToastFn; onClose: () => void; onDone: () => Promise<void> }) {
  const active = connections.filter((item) => item.active);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [connectionId, setConnectionId] = useState(active[0]?.id || "");
  const [vmid, setVmid] = useState("100");
  const [name, setName] = useState("");
  const [node, setNode] = useState("");
  const [storage, setStorage] = useState("local-lvm");
  const [disk, setDisk] = useState("32");
  const [cores, setCores] = useState("2");
  const [sockets, setSockets] = useState("1");
  const [memory, setMemory] = useState("2048");
  const [bridge, setBridge] = useState("vmbr0");
  const [vlan, setVlan] = useState("");
  const [ipv4Mode, setIpv4Mode] = useState<"dhcp" | "static">("dhcp");
  const [address, setAddress] = useState("");
  const [gateway, setGateway] = useState("");
  const [dns, setDns] = useState("");
  const [cloudUser, setCloudUser] = useState("");
  const [sshKey, setSshKey] = useState("");

  const payload = {
    vmid: Number(vmid), name, node, storage, disk_size_gb: Number(disk), cores: Number(cores), sockets: Number(sockets),
    memory_mb: Number(memory), bridge, vlan: vlan ? Number(vlan) : null, ipv4_mode: ipv4Mode,
    ipv4_address: address, gateway, dns, cloud_init_user: cloudUser, ssh_public_key: sshKey,
    start_after_create: false, sync_to_host_registry: true,
  };

  async function create() {
    setBusy(true);
    try {
      await api.createProxmoxVm(connectionId, payload);
      await onDone();
      onClose();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setBusy(false);
    }
  }

  const validGeneral = Boolean(connectionId && Number(vmid) >= 100 && name.trim() && node.trim());
  const canNext = step !== 0 || validGeneral;

  return <Modal title={`Create VM · ${steps[step]}`} onClose={onClose} wide footer={<>
    <button type="button" onClick={onClose}>{t("action.cancel")}</button>
    {step > 0 && <button type="button" disabled={busy} onClick={() => setStep(step - 1)}>Back</button>}
    {step < steps.length - 1 && <button className="button-primary" type="button" disabled={busy || !canNext} onClick={() => setStep(step + 1)}>Next</button>}
    {step === steps.length - 1 && <button className="button-primary" type="button" disabled={busy || !validGeneral || !storage} onClick={() => void create()}>{busy ? "Creating…" : "Create"}</button>}
  </>}>
    <p>Step {step + 1} / {steps.length}: {steps[step]}</p>
    {step === 0 && <>
      <label className="field-label">Connection<select value={connectionId} onChange={(event) => setConnectionId(event.target.value)}><option value="">Select connection</option>{active.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label className="field-label">VMID<input type="number" min={100} value={vmid} onChange={(event) => setVmid(event.target.value)} /></label>
      <label className="field-label">Name<input autoFocus value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label className="field-label">Node<input value={node} onChange={(event) => setNode(event.target.value)} placeholder="pve01" /></label>
    </>}
    {step === 1 && <section className="module-info"><h4>Cloud-init capable QEMU VM</h4><p>This creator uses the Proxmox QEMU REST endpoint and adds a cloud-init drive. Existing Proxmox templates are cloned through the Clone action so the asynchronous clone task is tracked correctly.</p></section>}
    {step === 2 && <><label className="field-label">Cores<input type="number" min={1} value={cores} onChange={(event) => setCores(event.target.value)} /></label><label className="field-label">Sockets<input type="number" min={1} value={sockets} onChange={(event) => setSockets(event.target.value)} /></label></>}
    {step === 3 && <label className="field-label">RAM (MiB)<input type="number" min={128} value={memory} onChange={(event) => setMemory(event.target.value)} /></label>}
    {step === 4 && <><label className="field-label">Storage<input value={storage} onChange={(event) => setStorage(event.target.value)} /></label><label className="field-label">Disk size (GiB)<input type="number" min={1} value={disk} onChange={(event) => setDisk(event.target.value)} /></label></>}
    {step === 5 && <><label className="field-label">Bridge<input value={bridge} onChange={(event) => setBridge(event.target.value)} /></label><label className="field-label">VLAN<input type="number" min={1} max={4094} value={vlan} onChange={(event) => setVlan(event.target.value)} placeholder="optional" /></label><label className="field-label">IPv4<select value={ipv4Mode} onChange={(event) => setIpv4Mode(event.target.value as "dhcp" | "static")}><option value="dhcp">DHCP</option><option value="static">Static</option></select></label>{ipv4Mode === "static" && <><label className="field-label">Address / prefix<input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="10.0.10.20/24" /></label><label className="field-label">Gateway<input value={gateway} onChange={(event) => setGateway(event.target.value)} /></label></>}</>}
    {step === 6 && <><label className="field-label">DNS<input value={dns} onChange={(event) => setDns(event.target.value)} placeholder="optional" /></label><label className="field-label">Cloud-init user<input value={cloudUser} onChange={(event) => setCloudUser(event.target.value)} placeholder="optional" /></label><label className="field-label">SSH public key<textarea rows={5} value={sshKey} onChange={(event) => setSshKey(event.target.value)} placeholder="ssh-ed25519 AAAA…" /></label><p>No cloud-init password is accepted or stored. Use an SSH public key or the central credential/secrets system after enrollment.</p></>}
    {step === 7 && <section className="module-info"><h4>Review</h4><dl><dt>Connection</dt><dd>{active.find((item) => item.id === connectionId)?.name || connectionId}</dd><dt>VM</dt><dd>{name} · VMID {vmid} · {node}</dd><dt>CPU</dt><dd>{sockets} socket(s) · {cores} cores</dd><dt>RAM</dt><dd>{memory} MiB</dd><dt>Disk</dt><dd>{disk} GiB · {storage}</dd><dt>Network</dt><dd>{bridge}{vlan ? ` · VLAN ${vlan}` : ""} · {ipv4Mode}</dd><dt>Cloud-init</dt><dd>{cloudUser || "default user"} · {sshKey ? "SSH key configured" : "no SSH key"}</dd></dl><p>After Proxmox returns UPID, the task is monitored centrally. Host Registry synchronization runs after successful completion.</p></section>}
  </Modal>;
}
