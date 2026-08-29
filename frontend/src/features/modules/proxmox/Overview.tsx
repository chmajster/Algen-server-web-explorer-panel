import type { ProxmoxConnection, ProxmoxVm } from "../../../api";
import { ModuleHealthCard } from "../common/ModuleAppShell";
import { bytes, percent } from "./utils";

function number(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function ProxmoxOverview({ dashboard, connections, vms }: { dashboard: Record<string, unknown>; connections: ProxmoxConnection[]; vms: ProxmoxVm[] }) {
  const errors = Array.isArray(dashboard.errors) ? dashboard.errors.length : 0;
  const running = number(dashboard.running);
  const stopped = number(dashboard.stopped);
  const ramUsed = number(dashboard.ram_used);
  const ramTotal = number(dashboard.ram_total);
  const storageUsed = number(dashboard.storage_used);
  const storageTotal = number(dashboard.storage_total);
  const lastSync = typeof dashboard.last_sync_at === "number" ? new Date(dashboard.last_sync_at * 1000).toLocaleString() : "—";
  const nextSync = typeof dashboard.next_sync_at === "number" ? new Date(dashboard.next_sync_at * 1000).toLocaleString() : "—";

  return <>
    <div className="module-health-grid">
      <ModuleHealthCard title="Connections" value={number(dashboard.active_connections)} detail={`${connections.length} configured`} />
      <ModuleHealthCard title="Nodes" value={number(dashboard.nodes)} detail={`${number(dashboard.nodes_online)} online`} tone={number(dashboard.nodes) === number(dashboard.nodes_online) && number(dashboard.nodes) ? "success" : "warning"} />
      <ModuleHealthCard title="Virtual Machines" value={number(dashboard.vms)} detail={`${running} running · ${stopped} stopped`} />
      <ModuleHealthCard title="LXC" value={number(dashboard.lxc)} detail={`${number(dashboard.templates)} templates`} />
      <ModuleHealthCard title="CPU utilization" value={percent(number(dashboard.cpu_utilization))} />
      <ModuleHealthCard title="RAM utilization" value={percent(number(dashboard.ram_utilization))} detail={`${bytes(ramUsed)} / ${bytes(ramTotal)}`} />
      <ModuleHealthCard title="Storage utilization" value={percent(number(dashboard.storage_utilization))} detail={`${bytes(storageUsed)} / ${bytes(storageTotal)}`} />
      <ModuleHealthCard title="Cluster quorum" value={dashboard.quorum === null || dashboard.quorum === undefined ? "—" : dashboard.quorum ? "OK" : "Lost"} tone={dashboard.quorum === false ? "danger" : "success"} />
      <ModuleHealthCard title="HA resources" value={number(dashboard.ha_resources)} />
      <ModuleHealthCard title="Active tasks" value={number(dashboard.active_tasks)} />
      <ModuleHealthCard title="Failed tasks" value={number(dashboard.failed_tasks)} tone={number(dashboard.failed_tasks) ? "danger" : "success"} />
      <ModuleHealthCard title="API errors" value={errors} tone={errors ? "danger" : "success"} />
    </div>
    <section className="module-info">
      <h3>Inventory ownership</h3>
      <p>Host Registry remains the source of truth. Proxmox Manager reads live Proxmox state and links VMID + connection ID to the existing Host Registry host.</p>
      <dl>
        <dt>Registered hosts</dt><dd>{vms.filter((item) => item.host_id).length} / {vms.length}</dd>
        <dt>Last synchronization</dt><dd>{lastSync}</dd>
        <dt>Next automatic synchronization</dt><dd>{nextSync}</dd>
      </dl>
    </section>
  </>;
}
