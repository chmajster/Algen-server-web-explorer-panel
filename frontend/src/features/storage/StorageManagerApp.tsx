import { AlertTriangle, Database, HardDrive, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { storageManagerClient, type StorageDevice, type StorageSnapshot } from "../../modules/storage-manager/api/client";
import "./storage-manager.css";


type Props = {
  locale?: string;
};

type Tab = "overview" | "devices" | "filesystems" | "health";

const bytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
};

const flattenDevices = (devices: StorageDevice[], depth = 0): Array<{ item: StorageDevice; depth: number }> => devices.flatMap((item) => [
  { item, depth },
  ...flattenDevices(item.children ?? [], depth + 1),
]);

export function StorageManagerApp({ locale = "en" }: Props) {
  const polish = locale.toLowerCase().startsWith("pl");
  const [snapshot, setSnapshot] = useState<StorageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSnapshot(await storageManagerClient.summary());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const devices = useMemo(() => flattenDevices(snapshot?.devices ?? []), [snapshot?.devices]);
  const physicalDisks = devices.filter(({ item }) => item.type === "disk").length;
  const protectedCount = devices.filter(({ item }) => item.protected).length;
  const unhealthy = snapshot?.issues.length ?? 0;

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "overview", label: polish ? "Przegląd" : "Overview" },
    { id: "devices", label: polish ? "Urządzenia" : "Devices" },
    { id: "filesystems", label: polish ? "Systemy plików" : "Filesystems" },
    { id: "health", label: polish ? "Stan" : "Health" },
  ];

  return (
    <div className="storage-manager">
      <header className="storage-manager__header">
        <div>
          <div className="storage-manager__eyebrow">{polish ? "Infrastruktura / Storage" : "Infrastructure / Storage"}</div>
          <h1><HardDrive size={23} /> Storage Manager</h1>
          <p>
            {polish
              ? "Bezpieczny, tylko do odczytu, widok dysków, systemów plików, RAID i kondycji nośników."
              : "Safe read-only inventory of disks, filesystems, RAID and device health."}
          </p>
        </div>
        <div className="storage-manager__actions">
          <span className="storage-manager__readonly"><ShieldCheck size={15} /> {polish ? "Tryb tylko do odczytu" : "Read-only mode"}</span>
          <button type="button" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={16} className={loading ? "storage-manager__spin" : ""} />
            {polish ? "Odśwież" : "Refresh"}
          </button>
        </div>
      </header>

      {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}

      <nav className="storage-manager__tabs" aria-label="Storage Manager">
        {tabs.map((item) => (
          <button key={item.id} type="button" className={tab === item.id ? "is-active" : ""} onClick={() => setTab(item.id)}>
            {item.label}
          </button>
        ))}
      </nav>

      {loading && !snapshot ? <div className="storage-manager__empty">{polish ? "Pobieranie stanu storage…" : "Loading storage state…"}</div> : null}

      {snapshot && tab === "overview" ? (
        <div className="storage-manager__content">
          <section className="storage-manager__metrics">
            <article><span>{polish ? "Stan" : "State"}</span><strong className={`state-${snapshot.state}`}>{snapshot.state}</strong></article>
            <article><span>{polish ? "Dyski fizyczne" : "Physical disks"}</span><strong>{physicalDisks}</strong></article>
            <article><span>{polish ? "Systemy plików" : "Filesystems"}</span><strong>{snapshot.filesystems.length}</strong></article>
            <article><span>{polish ? "Problemy" : "Issues"}</span><strong>{unhealthy}</strong></article>
          </section>

          <section className="storage-manager__panel">
            <div className="storage-manager__panel-title">
              <div><h2>{polish ? "Diagnostyka" : "Diagnostics"}</h2><p>{polish ? "Problemy wykryte przez bezpieczne sondy systemowe." : "Problems detected by safe system probes."}</p></div>
            </div>
            {snapshot.issues.length ? (
              <div className="storage-manager__issues">
                {snapshot.issues.map((issue) => (
                  <article key={`${issue.code}:${issue.target}`} className={`severity-${issue.severity}`}>
                    <AlertTriangle size={17} />
                    <div><strong>{issue.message}</strong><span>{issue.target} · {issue.code}</span></div>
                  </article>
                ))}
              </div>
            ) : <div className="storage-manager__healthy"><ShieldCheck size={19} /> {polish ? "Nie wykryto problemów ze storage." : "No storage problems detected."}</div>}
          </section>

          <section className="storage-manager__panel">
            <div className="storage-manager__panel-title"><div><h2>{polish ? "Narzędzia diagnostyczne" : "Diagnostic tools"}</h2><p>{polish ? "Dostępność lokalnych narzędzi używanych wyłącznie przez backend." : "Availability of local tools used only by the backend."}</p></div></div>
            <div className="storage-manager__tool-grid">
              {Object.entries(snapshot.tools).map(([tool, available]) => <div key={tool}><code>{tool}</code><span className={available ? "ok" : "muted"}>{available ? (polish ? "dostępne" : "available") : (polish ? "brak" : "missing")}</span></div>)}
            </div>
          </section>
        </div>
      ) : null}

      {snapshot && tab === "devices" ? (
        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>{polish ? "Topologia blokowa" : "Block topology"}</h2><p>{polish ? `${protectedCount} elementów oznaczono jako chronione.` : `${protectedCount} entries are marked protected.`}</p></div></div>
          <div className="storage-manager__table-wrap">
            <table><thead><tr><th>{polish ? "Urządzenie" : "Device"}</th><th>{polish ? "Typ" : "Type"}</th><th>{polish ? "Model" : "Model"}</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "FS / montowanie" : "FS / mount"}</th><th>{polish ? "Ochrona" : "Protection"}</th></tr></thead>
              <tbody>{devices.map(({ item, depth }) => <tr key={item.path}><td><div className="storage-manager__device" style={{ paddingLeft: `${depth * 18}px` }}><HardDrive size={15} /><code>{item.path}</code></div></td><td>{item.type || "—"}</td><td>{item.model || item.label || "—"}</td><td>{bytes(item.size)}</td><td>{item.filesystem || "—"}<small>{item.mountpoints.join(", ") || ""}</small></td><td>{item.protected ? <span className="storage-manager__badge protected"><ShieldCheck size={13} /> {polish ? "chronione" : "protected"}</span> : <span className="storage-manager__badge">{polish ? "dane" : "data"}</span>}</td></tr>)}</tbody>
            </table>
          </div>
        </section>
      ) : null}

      {snapshot && tab === "filesystems" ? (
        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>{polish ? "Pojemność systemów plików" : "Filesystem capacity"}</h2><p>{polish ? "Lokalne mounty; pseudo-FS i zasoby sieciowe są pomijane." : "Local mounts only; pseudo filesystems and network resources are excluded."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>{polish ? "Punkt montowania" : "Mount point"}</th><th>{polish ? "Źródło" : "Source"}</th><th>FS</th><th>{polish ? "Użycie" : "Usage"}</th><th>{polish ? "Wolne" : "Free"}</th><th>{polish ? "Tryb" : "Mode"}</th></tr></thead><tbody>
            {snapshot.filesystems.map((fs) => {
              const usedPercent = fs.total ? Math.max(0, Math.min(100, (fs.used / fs.total) * 100)) : 0;
              return <tr key={fs.mount_point}><td><code>{fs.mount_point}</code>{fs.protected ? <span className="storage-manager__badge protected"><ShieldCheck size={12} /> {polish ? "chronione" : "protected"}</span> : null}</td><td><code>{fs.source}</code></td><td>{fs.filesystem}</td><td><div className="storage-manager__capacity"><span style={{ width: `${usedPercent}%` }} /></div><small>{bytes(fs.used)} / {bytes(fs.total)}</small></td><td>{bytes(fs.free)}<small>{fs.free_percent.toFixed(1)}%</small></td><td>{fs.read_only ? "ro" : "rw"}</td></tr>;
            })}
          </tbody></table></div>
        </section>
      ) : null}

      {snapshot && tab === "health" ? (
        <div className="storage-manager__content">
          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title"><div><h2>SMART / NVMe</h2><p>{polish ? "Kondycja fizycznych nośników." : "Physical device health."}</p></div></div>
            <div className="storage-manager__table-wrap"><table><thead><tr><th>{polish ? "Dysk" : "Disk"}</th><th>{polish ? "Dostawca" : "Provider"}</th><th>{polish ? "Stan" : "State"}</th><th>{polish ? "Temperatura" : "Temperature"}</th><th>{polish ? "Zużycie" : "Wear"}</th><th>{polish ? "Błędy medium" : "Media errors"}</th></tr></thead><tbody>
              {snapshot.device_health.map((item) => <tr key={item.device}><td><code>{item.device}</code><small>{item.model || item.serial || ""}</small></td><td>{item.provider}</td><td><span className={`storage-manager__badge state-${item.state}`}>{item.state}</span></td><td>{item.temperature_c == null ? "—" : `${item.temperature_c} °C`}</td><td>{item.percentage_used == null ? "—" : `${item.percentage_used}%`}</td><td>{item.media_errors ?? "—"}</td></tr>)}
            </tbody></table></div>
          </section>

          <section className="storage-manager__health-grid">
            <article><Database size={18} /><div><strong>mdadm</strong><span>{snapshot.md_arrays.length ? snapshot.md_arrays.map((item) => `${item.name}: ${item.state}`).join(" · ") : (polish ? "brak macierzy" : "no arrays")}</span></div></article>
            <article><Database size={18} /><div><strong>ZFS</strong><span>{snapshot.zfs_pools.length ? snapshot.zfs_pools.map((item) => `${item.name}: ${item.health}`).join(" · ") : (polish ? "brak puli" : "no pools")}</span></div></article>
            <article><Database size={18} /><div><strong>Btrfs</strong><span>{snapshot.btrfs_filesystems.length ? snapshot.btrfs_filesystems.map((item) => `${item.mount_point}: ${item.state}`).join(" · ") : (polish ? "brak lokalnych Btrfs" : "no local Btrfs")}</span></div></article>
          </section>
        </div>
      ) : null}
    </div>
  );
}
