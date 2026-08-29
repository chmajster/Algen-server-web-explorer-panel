import { AlertTriangle, Database, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { storageManagerClient, type StorageDetails } from "../../modules/storage-manager/api/client";


type Props = {
  locale?: string;
};

const bytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
};

export function StorageAdvancedPanel({ locale = "en" }: Props) {
  const polish = locale.toLowerCase().startsWith("pl");
  const [details, setDetails] = useState<StorageDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setDetails(await storageManagerClient.details());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const inactivePersistent = useMemo(
    () => details?.fstab.filter((item) => item.state === "inactive").length ?? 0,
    [details?.fstab],
  );

  if (loading && !details) {
    return <div className="storage-manager__empty">{polish ? "Pobieranie rozszerzonego inventory…" : "Loading advanced inventory…"}</div>;
  }

  return (
    <div className="storage-manager__content">
      {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}

      <section className="storage-manager__panel">
        <div className="storage-manager__panel-title">
          <div>
            <h2>{polish ? "Rozszerzone inventory" : "Advanced inventory"}</h2>
            <p>{polish ? "LVM, swap, trwałość mountów i liczniki I/O. Wszystkie operacje są tylko do odczytu." : "LVM, swap, mount persistence and I/O counters. All operations are read-only."}</p>
          </div>
          <button type="button" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={15} className={loading ? "storage-manager__spin" : ""} />
            {polish ? "Odśwież" : "Refresh"}
          </button>
        </div>
        {details ? (
          <div className="storage-manager__metrics">
            <article><span>LVM PV</span><strong>{details.lvm.physical_volumes.length}</strong></article>
            <article><span>LVM VG</span><strong>{details.lvm.volume_groups.length}</strong></article>
            <article><span>LVM LV</span><strong>{details.lvm.logical_volumes.length}</strong></article>
            <article><span>{polish ? "Nieaktywne wpisy fstab" : "Inactive fstab entries"}</span><strong>{inactivePersistent}</strong></article>
          </div>
        ) : null}
      </section>

      {details ? (
        <>
          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title">
              <div><h2>LVM — Physical Volumes</h2><p>{polish ? "Fizyczne wolumeny wykryte przez pvs." : "Physical volumes detected by pvs."}</p></div>
            </div>
            <div className="storage-manager__table-wrap">
              <table>
                <thead><tr><th>PV</th><th>VG</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "Wolne" : "Free"}</th><th>Attr</th></tr></thead>
                <tbody>
                  {details.lvm.physical_volumes.length ? details.lvm.physical_volumes.map((item) => (
                    <tr key={item.path}><td><code>{item.path}</code></td><td>{item.volume_group || "—"}</td><td>{bytes(item.size)}</td><td>{bytes(item.free)}</td><td><code>{item.attributes || "—"}</code></td></tr>
                  )) : <tr><td colSpan={5}>{polish ? "Brak fizycznych wolumenów LVM lub narzędzia pvs." : "No LVM physical volumes or pvs is unavailable."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title">
              <div><h2>LVM — Volume Groups</h2><p>{polish ? "Pojemność i liczba PV/LV w grupach wolumenów." : "Capacity and PV/LV counts for volume groups."}</p></div>
            </div>
            <div className="storage-manager__table-wrap">
              <table>
                <thead><tr><th>VG</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "Wolne" : "Free"}</th><th>PV</th><th>LV</th><th>Attr</th></tr></thead>
                <tbody>
                  {details.lvm.volume_groups.length ? details.lvm.volume_groups.map((item) => (
                    <tr key={item.name}><td><strong>{item.name}</strong></td><td>{bytes(item.size)}</td><td>{bytes(item.free)}</td><td>{item.pv_count}</td><td>{item.lv_count}</td><td><code>{item.attributes || "—"}</code></td></tr>
                  )) : <tr><td colSpan={6}>{polish ? "Brak grup wolumenów LVM." : "No LVM volume groups."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title">
              <div><h2>LVM — Logical Volumes</h2><p>{polish ? "Wolumeny logiczne, thin-pool i wykorzystanie danych/metadanych." : "Logical volumes, thin pools and data/metadata utilization."}</p></div>
            </div>
            <div className="storage-manager__table-wrap">
              <table>
                <thead><tr><th>LV</th><th>VG</th><th>{polish ? "Ścieżka" : "Path"}</th><th>{polish ? "Rozmiar" : "Size"}</th><th>Data %</th><th>Meta %</th><th>Attr</th></tr></thead>
                <tbody>
                  {details.lvm.logical_volumes.length ? details.lvm.logical_volumes.map((item) => (
                    <tr key={`${item.volume_group}/${item.name}`}><td><strong>{item.name}</strong>{item.pool ? <small>pool: {item.pool}</small> : null}{item.origin ? <small>origin: {item.origin}</small> : null}</td><td>{item.volume_group || "—"}</td><td><code>{item.path || "—"}</code></td><td>{bytes(item.size)}</td><td>{item.data_percent == null ? "—" : `${item.data_percent}%`}</td><td>{item.metadata_percent == null ? "—" : `${item.metadata_percent}%`}</td><td><code>{item.attributes || "—"}</code></td></tr>
                  )) : <tr><td colSpan={7}>{polish ? "Brak wolumenów logicznych LVM." : "No LVM logical volumes."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title">
              <div><h2>Swap</h2><p>{polish ? "Aktywne partycje i pliki swap wraz z wykorzystaniem." : "Active swap partitions and files with utilization."}</p></div>
            </div>
            <div className="storage-manager__table-wrap">
              <table>
                <thead><tr><th>{polish ? "Źródło" : "Source"}</th><th>{polish ? "Typ" : "Type"}</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "Użyte" : "Used"}</th><th>{polish ? "Priorytet" : "Priority"}</th></tr></thead>
                <tbody>
                  {details.swap.length ? details.swap.map((item) => (
                    <tr key={item.name}><td><code>{item.name}</code></td><td>{item.type}</td><td>{bytes(item.size)}</td><td>{bytes(item.used)}</td><td>{item.priority}</td></tr>
                  )) : <tr><td colSpan={5}>{polish ? "Brak aktywnego swapu lub narzędzia swapon." : "No active swap or swapon is unavailable."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title">
              <div><h2>/etc/fstab</h2><p>{polish ? "Porównanie trwałej konfiguracji mountów z aktualnie zamontowanymi systemami plików." : "Persistent mount configuration compared with currently mounted filesystems."}</p></div>
            </div>
            <div className="storage-manager__table-wrap">
              <table>
                <thead><tr><th>{polish ? "Punkt" : "Mount point"}</th><th>{polish ? "Źródło" : "Source"}</th><th>FS</th><th>{polish ? "Stan" : "State"}</th><th>{polish ? "Opcje" : "Options"}</th><th>{polish ? "Ochrona" : "Protection"}</th></tr></thead>
                <tbody>
                  {details.fstab.length ? details.fstab.map((item) => (
                    <tr key={`${item.mount_point}:${item.source}`}><td><code>{item.mount_point}</code></td><td><code>{item.source}</code>{item.active && item.current_source && item.current_source !== item.source ? <small>{polish ? "aktywnie" : "active"}: {item.current_source}</small> : null}</td><td>{item.filesystem}</td><td><span className={`storage-manager__badge state-${item.state === "active" ? "ok" : item.state === "disabled" ? "degraded" : "failed"}`}>{item.state}</span></td><td><code>{item.options.join(",") || "—"}</code></td><td>{item.protected ? <span className="storage-manager__badge protected">{polish ? "chronione" : "protected"}</span> : "—"}</td></tr>
                  )) : <tr><td colSpan={6}>{polish ? "Brak wpisów mount w /etc/fstab." : "No mount entries in /etc/fstab."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="storage-manager__panel storage-manager__table-panel">
            <div className="storage-manager__panel-title">
              <div><h2>{polish ? "Liczniki I/O dysków" : "Disk I/O counters"}</h2><p>{polish ? "Skumulowane liczniki jądra z /proc/diskstats dla fizycznych dysków." : "Cumulative kernel counters from /proc/diskstats for physical disks."}</p></div>
            </div>
            <div className="storage-manager__table-wrap">
              <table>
                <thead><tr><th>{polish ? "Dysk" : "Disk"}</th><th>{polish ? "Odczyty" : "Reads"}</th><th>{polish ? "Przeczytano" : "Read bytes"}</th><th>{polish ? "Zapisy" : "Writes"}</th><th>{polish ? "Zapisano" : "Written bytes"}</th><th>{polish ? "W toku" : "In flight"}</th><th>I/O ms</th></tr></thead>
                <tbody>
                  {details.disk_io.length ? details.disk_io.map((item) => (
                    <tr key={item.name}><td><Database size={14} /> <code>/dev/{item.name}</code></td><td>{item.reads_completed.toLocaleString()}</td><td>{bytes(item.bytes_read)}</td><td>{item.writes_completed.toLocaleString()}</td><td>{bytes(item.bytes_written)}</td><td>{item.io_in_progress}</td><td>{item.io_ms.toLocaleString()}</td></tr>
                  )) : <tr><td colSpan={7}>{polish ? "Brak liczników I/O dla wykrytych dysków." : "No I/O counters for detected disks."}</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="storage-manager__panel">
            <div className="storage-manager__panel-title"><div><h2>{polish ? "Narzędzia rozszerzone" : "Advanced tools"}</h2><p>{polish ? "Dostępność narzędzi używanych do inventory." : "Availability of tools used for advanced inventory."}</p></div></div>
            <div className="storage-manager__tool-grid">
              {Object.entries(details.tools).map(([tool, available]) => <div key={tool}><code>{tool}</code><span className={available ? "ok" : "muted"}>{available ? (polish ? "dostępne" : "available") : (polish ? "brak" : "missing")}</span></div>)}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
