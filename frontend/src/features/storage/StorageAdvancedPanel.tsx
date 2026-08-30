import { AlertTriangle, Database, HardDrive, ShieldCheck } from "lucide-react";

import type { StorageDetails } from "../../modules/storage-manager/api/client";


type Section = "lvm" | "pools" | "mounts" | "io" | "advanced";

type Props = {
  locale?: string;
  details: StorageDetails | null;
  loading: boolean;
  error: string;
  section: Section;
};

const bytes = (value: number) => {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
};

const percent = (value: number | null) => value == null ? "—" : `${value.toFixed(1)}%`;

export function StorageAdvancedPanel({ locale = "en", details, loading, error, section }: Props) {
  const polish = locale.toLowerCase().startsWith("pl");

  if (loading && !details) {
    return <div className="storage-manager__empty">{polish ? "Pobieranie rozszerzonego inventory…" : "Loading advanced inventory…"}</div>;
  }
  if (!details) {
    return <div className="storage-manager__error"><AlertTriangle size={18} /> {error || (polish ? "Rozszerzone inventory jest niedostępne." : "Advanced inventory is unavailable.")}</div>;
  }

  if (section === "lvm") {
    return (
      <div className="storage-manager__content">
        {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}
        <section className="storage-manager__metrics">
          <article><span>Physical Volumes</span><strong>{details.lvm.physical_volumes.length}</strong></article>
          <article><span>Volume Groups</span><strong>{details.lvm.volume_groups.length}</strong></article>
          <article><span>Logical Volumes</span><strong>{details.lvm.logical_volumes.length}</strong></article>
          <article><span>Thin / pool</span><strong>{details.lvm.logical_volumes.filter((item) => item.thin_pool).length}</strong></article>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>LVM — Physical Volumes</h2><p>{polish ? "PV i przypisanie do VG." : "Physical volumes and VG assignment."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>PV</th><th>VG</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "Wolne" : "Free"}</th><th>Attr</th></tr></thead><tbody>
            {details.lvm.physical_volumes.map((item) => <tr key={item.path}><td><code>{item.path}</code></td><td>{item.volume_group || "—"}</td><td>{bytes(item.size)}</td><td>{bytes(item.free)}</td><td><code>{item.attributes}</code></td></tr>)}
          </tbody></table></div>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>LVM — Volume Groups</h2><p>{polish ? "Pojemność oraz zależności PV → VG → LV." : "Capacity and PV → VG → LV relationships."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>VG</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "Wolne" : "Free"}</th><th>PV</th><th>LV</th><th>{polish ? "Zależności" : "Relationships"}</th></tr></thead><tbody>
            {details.lvm.volume_groups.map((item) => {
              const relation = details.lvm.relationships.find((entry) => entry.volume_group === item.name);
              return <tr key={item.name}><td><strong>{item.name}</strong><small><code>{item.attributes}</code></small></td><td>{bytes(item.size)}</td><td>{bytes(item.free)}</td><td>{item.pv_count}</td><td>{item.lv_count}</td><td><small>{relation?.physical_volumes.join(", ") || "—"}<br />{relation?.logical_volumes.join(", ") || "—"}</small></td></tr>;
            })}
          </tbody></table></div>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>LVM — Logical Volumes</h2><p>{polish ? "LV, thin pools i wykorzystanie data/metadata." : "Logical volumes, thin pools and data/metadata utilization."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>LV</th><th>VG</th><th>{polish ? "Ścieżka" : "Path"}</th><th>{polish ? "Rozmiar" : "Size"}</th><th>Pool / Origin</th><th>Data</th><th>Metadata</th></tr></thead><tbody>
            {details.lvm.logical_volumes.map((item) => <tr key={`${item.volume_group}:${item.name}`}><td><strong>{item.name}</strong><small><code>{item.attributes}</code></small></td><td>{item.volume_group}</td><td><code>{item.path || "—"}</code></td><td>{bytes(item.size)}</td><td>{item.pool || item.origin || "—"}{item.thin_pool ? <span className="storage-manager__badge">thin</span> : null}</td><td>{percent(item.data_percent)}</td><td>{percent(item.metadata_percent)}</td></tr>)}
          </tbody></table></div>
        </section>
      </div>
    );
  }

  if (section === "pools") {
    return (
      <div className="storage-manager__content">
        {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}
        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>mdraid</h2><p>{polish ? "Stan macierzy, członkowie i postęp recovery/resync." : "Array state, members and recovery/resync progress."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>{polish ? "Macierz" : "Array"}</th><th>RAID</th><th>{polish ? "Stan" : "State"}</th><th>{polish ? "Członkowie" : "Members"}</th><th>{polish ? "Brakujące" : "Missing"}</th><th>{polish ? "Operacja" : "Operation"}</th><th>{polish ? "Postęp" : "Progress"}</th></tr></thead><tbody>
            {details.pools.raid.map((item) => <tr key={item.name}><td><strong>{item.name}</strong></td><td>{item.level}</td><td><span className={`storage-manager__badge state-${item.state}`}>{item.state}</span></td><td>{item.active_members}/{item.expected_members}<small>{item.members.join(", ")}</small></td><td>{item.missing_members}</td><td>{item.operation || "—"}<small>{item.speed || ""}</small></td><td>{percent(item.progress_percent)}<small>{item.finish || ""}</small></td></tr>)}
          </tbody></table></div>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>ZFS Pools</h2><p>{polish ? "Health, vdevy, błędy i scrub/resilver." : "Health, vdevs, errors and scrub/resilver status."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>Pool</th><th>Health</th><th>{polish ? "Pojemność" : "Capacity"}</th><th>{polish ? "Członkowie" : "Members"}</th><th>Scan</th><th>{polish ? "Błędy" : "Errors"}</th></tr></thead><tbody>
            {details.pools.zfs.pools.map((pool) => <tr key={pool.name}><td><strong>{pool.name}</strong></td><td><span className={`storage-manager__badge state-${pool.state}`}>{pool.health}</span></td><td>{bytes(pool.allocated)} / {bytes(pool.size)}<small>{bytes(pool.free)} {polish ? "wolne" : "free"}</small></td><td>{pool.members.length || "—"}<small>{pool.members.map((item) => `${item.name}:${item.state}`).join(" · ")}</small></td><td>{pool.scan.action || "—"}<small>{pool.scan.state} {pool.scan.progress_percent == null ? "" : percent(pool.scan.progress_percent)}</small></td><td>{pool.errors || "—"}</td></tr>)}
          </tbody></table></div>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>ZFS Datasets</h2><p>{polish ? "Datasety i ich wykorzystanie przestrzeni." : "Datasets and capacity usage."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>Dataset</th><th>{polish ? "Typ" : "Type"}</th><th>{polish ? "Użyte" : "Used"}</th><th>{polish ? "Dostępne" : "Available"}</th><th>Referenced</th><th>Mount</th></tr></thead><tbody>
            {details.pools.zfs.datasets.map((item) => <tr key={item.name}><td><code>{item.name}</code></td><td>{item.type}</td><td>{bytes(item.used)}</td><td>{bytes(item.available)}</td><td>{bytes(item.referenced)}</td><td><code>{item.mount_point}</code></td></tr>)}
          </tbody></table></div>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>Btrfs</h2><p>{polish ? "Urządzenia, profile DATA/METADATA/SYSTEM, błędy i scrub." : "Devices, DATA/METADATA/SYSTEM profiles, errors and scrub."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>Mount</th><th>{polish ? "Stan" : "State"}</th><th>UUID / Label</th><th>{polish ? "Urządzenia" : "Devices"}</th><th>{polish ? "Profile" : "Profiles"}</th><th>{polish ? "Błędy" : "Errors"}</th><th>Scrub</th></tr></thead><tbody>
            {details.pools.btrfs.map((item) => <tr key={item.mount_point}><td><code>{item.mount_point}</code></td><td><span className={`storage-manager__badge state-${item.state}`}>{item.state}</span></td><td>{item.uuid || "—"}<small>{item.label}</small></td><td>{item.devices.map((device) => device.path).join(", ") || "—"}</td><td>{item.profiles.map((profile) => `${profile.kind}:${profile.profile}`).join(" · ") || "—"}</td><td>{item.total_errors}</td><td>{item.scrub.state}<small>{percent(item.scrub.progress_percent)}</small></td></tr>)}
          </tbody></table></div>
        </section>
      </div>
    );
  }

  if (section === "mounts") {
    return (
      <div className="storage-manager__content">
        {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}
        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>/etc/fstab</h2><p>{polish ? "Trwałe mounty porównane z aktualnym stanem systemu." : "Persistent mounts correlated with the current system state."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>{polish ? "Źródło" : "Source"}</th><th>Mount</th><th>FS</th><th>{polish ? "Stan" : "State"}</th><th>{polish ? "Dopasowanie" : "Match"}</th><th>Options</th><th>{polish ? "Ochrona" : "Protection"}</th></tr></thead><tbody>
            {details.fstab.map((item) => <tr key={`${item.source}:${item.mount_point}`}><td><code>{item.source}</code><small>{item.resolved_source && item.resolved_source !== item.source ? `→ ${item.resolved_source}` : ""}</small></td><td><code>{item.mount_point}</code></td><td>{item.filesystem}</td><td><span className={`storage-manager__badge ${item.state === "active" ? "state-ok" : item.state === "inactive" ? "state-degraded" : ""}`}>{item.state}</span><small>{item.automount ? "systemd automount" : item.noauto ? "noauto" : ""}</small></td><td>{item.active ? (item.source_mismatch ? (polish ? "różne źródło" : "source mismatch") : (polish ? "zgodne" : "matched")) : "—"}</td><td><small>{item.options.join(", ")}</small></td><td>{item.protected ? <span className="storage-manager__badge protected"><ShieldCheck size={12} /> {polish ? "chronione" : "protected"}</span> : item.network ? <span className="storage-manager__badge">network</span> : "—"}</td></tr>)}
          </tbody></table></div>
        </section>

        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>Swap</h2><p>{polish ? "Aktywne partycje i pliki swap." : "Active swap partitions and files."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>{polish ? "Źródło" : "Source"}</th><th>{polish ? "Typ" : "Type"}</th><th>{polish ? "Rozmiar" : "Size"}</th><th>{polish ? "Użyte" : "Used"}</th><th>Priority</th></tr></thead><tbody>
            {details.swap.map((item) => <tr key={item.name}><td><code>{item.name}</code></td><td>{item.type}</td><td>{bytes(item.size)}</td><td>{bytes(item.used)}</td><td>{item.priority}</td></tr>)}
          </tbody></table></div>
        </section>
      </div>
    );
  }

  if (section === "io") {
    return (
      <div className="storage-manager__content">
        {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}
        <section className="storage-manager__panel storage-manager__table-panel">
          <div className="storage-manager__panel-title"><div><h2>/proc/diskstats</h2><p>{polish ? "Liczniki są kumulacyjne. Znacznik monotoniczny umożliwia późniejsze liczenie IOPS i throughput z dwóch próbek." : "Counters are cumulative. The monotonic timestamp is ready for future IOPS and throughput deltas between samples."}</p></div></div>
          <div className="storage-manager__table-wrap"><table><thead><tr><th>{polish ? "Dysk" : "Disk"}</th><th>Reads</th><th>{polish ? "Odczytano" : "Read bytes"}</th><th>Writes</th><th>{polish ? "Zapisano" : "Written bytes"}</th><th>{polish ? "W toku" : "In flight"}</th><th>I/O ms</th><th>Discards</th></tr></thead><tbody>
            {details.io.devices.map((item) => <tr key={item.name}><td><code>{item.name}</code></td><td>{item.reads_completed.toLocaleString()}</td><td>{bytes(item.bytes_read)}</td><td>{item.writes_completed.toLocaleString()}</td><td>{bytes(item.bytes_written)}</td><td>{item.io_in_progress}</td><td>{item.io_ms.toLocaleString()}</td><td>{item.discards_completed.toLocaleString()}<small>{bytes(item.bytes_discarded)}</small></td></tr>)}
          </tbody></table></div>
          <div className="storage-manager__eyebrow">{polish ? "Próbka" : "Sample"}: {new Date(details.io.sampled_at * 1000).toLocaleString()} · monotonic_ns={details.io.monotonic_ns}</div>
        </section>
      </div>
    );
  }

  return (
    <div className="storage-manager__content">
      {error ? <div className="storage-manager__error"><AlertTriangle size={18} /> {error}</div> : null}
      <section className="storage-manager__metrics">
        <article><span>device-mapper</span><strong>{details.dashboard.device_mapper_entries}</strong></article>
        <article><span>LUKS / crypt</span><strong>{details.dashboard.encrypted_entries}</strong></article>
        <article><span>{polish ? "Narzędzia dostępne" : "Tools available"}</span><strong>{Object.values(details.tools).filter(Boolean).length}/{Object.keys(details.tools).length}</strong></article>
        <article><span>{polish ? "Tryb" : "Mode"}</span><strong>{details.management.mode}</strong></article>
      </section>

      <section className="storage-manager__panel">
        <div className="storage-manager__panel-title"><div><h2>{polish ? "Narzędzia rozszerzone" : "Advanced tools"}</h2><p>{polish ? "Każde polecenie ma stały kształt argv i allowlistę; brak shell=True." : "Every command uses a fixed argv shape and allowlist; shell=True is never used."}</p></div></div>
        <div className="storage-manager__tool-grid">
          {Object.entries(details.tools).map(([tool, available]) => <div key={tool}><code>{tool}</code><span className={available ? "ok" : "muted"}>{available ? (polish ? "dostępne" : "available") : (polish ? "brak" : "missing")}</span></div>)}
        </div>
      </section>

      <section className="storage-manager__panel">
        <div className="storage-manager__panel-title"><div><h2>{polish ? "Kontrakt przyszłego trybu zarządzania" : "Future management contract"}</h2><p>{polish ? "Operacje zapisu pozostają wyłączone w tym PR." : "Write operations remain disabled in this PR."}</p></div></div>
        <div className="storage-manager__tool-grid">
          {details.management.future_guardrails.map((item) => <div key={item}><ShieldCheck size={14} /><span>{item}</span></div>)}
        </div>
      </section>

      <section className="storage-manager__health-grid">
        <article><Database size={18} /><div><strong>LVM</strong><span>{details.dashboard.lvm_pv} PV · {details.dashboard.lvm_vg} VG · {details.dashboard.lvm_lv} LV</span></div></article>
        <article><HardDrive size={18} /><div><strong>RAID / ZFS / Btrfs</strong><span>{details.dashboard.raid_arrays} / {details.dashboard.zfs_pools} / {details.dashboard.btrfs_filesystems}</span></div></article>
        <article><AlertTriangle size={18} /><div><strong>{polish ? "Ryzyka" : "Risks"}</strong><span>{details.dashboard.unhealthy_devices} health · {details.dashboard.low_space_filesystems} low space</span></div></article>
      </section>
    </div>
  );
}
