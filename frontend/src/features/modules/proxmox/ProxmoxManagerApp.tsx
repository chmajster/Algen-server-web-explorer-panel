import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type HostsManagerCredential, type ModuleStatus, type ProxmoxConnection, type ProxmoxVm } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { useRefreshOnConnectionRestored } from "../../connection/ConnectionStatusMonitor";
import { ModuleAppShell, type ModuleSection } from "../common/ModuleAppShell";
import { ProxmoxAdvanced } from "./Advanced";
import { ProxmoxClusterView } from "./Cluster";
import { ProxmoxConnections } from "./Connections";
import { ProxmoxNodes } from "./Nodes";
import { ProxmoxOverview } from "./Overview";
import { ProxmoxStorageView } from "./Storage";
import { ProxmoxTasksView } from "./Tasks";
import { ProxmoxVmList } from "./VmList";

export { buildEndpoint, splitEndpoint } from "./utils";

const sections: ModuleSection[] = ["overview", "inventory", "hosts", "repositories", "environment", "operations", "audit", "settings"];
const sectionLabels: Partial<Record<ModuleSection, string>> = {
  overview: "Overview",
  inventory: "Virtual Machines",
  hosts: "Nodes",
  repositories: "Storage",
  environment: "Cluster",
  operations: "Tasks",
  audit: "Advanced 361–380",
  settings: "Settings",
};

const initialStatus: ModuleStatus = {
  installed: true,
  package_version: "1.0.0",
  update_available: false,
  service_state: "not_applicable",
  service_enabled: false,
  services: {},
  health: "unknown",
  health_message: "",
  last_action: "",
  last_action_status: "",
  last_error: "",
  metrics: {},
};

function dashboardNumber(dashboard: Record<string, unknown>, key: string): number {
  return typeof dashboard[key] === "number" ? Number(dashboard[key]) : 0;
}

export function ProxmoxManagerApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [connections, setConnections] = useState<ProxmoxConnection[]>([]);
  const [vms, setVms] = useState<ProxmoxVm[]>([]);
  const [credentials, setCredentials] = useState<HostsManagerCredential[]>([]);
  const [dashboard, setDashboard] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [connectionItems, vmResult, credentialItems, dashboardResult] = await Promise.all([
        api.proxmoxConnections(),
        api.proxmoxVms(),
        api.hostsManagerCredentials().catch(() => [] as HostsManagerCredential[]),
        api.proxmoxDashboard(),
      ]);
      setConnections(connectionItems);
      setVms(vmResult.vms);
      setCredentials(credentialItems.filter((item) => ["proxmox_api", "username_password"].includes(item.type) && (item.shared_with || []).includes("proxmox-manager")));
      setDashboard(dashboardResult);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useRefreshOnConnectionRestored(() => { void refresh(); });

  const status = useMemo<ModuleStatus>(() => {
    const errors = Array.isArray(dashboard.errors) ? dashboard.errors.length : 0;
    const active = connections.some((item) => item.active);
    return {
      ...initialStatus,
      health: errors ? "degraded" : active ? "healthy" : "unknown",
      health_message: errors ? `${errors} Proxmox API error(s).` : active ? "Proxmox API connections are active." : "Configure a Proxmox connection.",
      metrics: {
        connections: connections.length,
        nodes: dashboardNumber(dashboard, "nodes"),
        vms: dashboardNumber(dashboard, "vms"),
        lxc: dashboardNumber(dashboard, "lxc"),
        active_tasks: dashboardNumber(dashboard, "active_tasks"),
      },
    };
  }, [connections, dashboard]);

  const content = section === "overview"
    ? <ProxmoxOverview dashboard={dashboard} connections={connections} vms={vms} />
    : section === "inventory"
      ? <ProxmoxVmList vms={vms} connections={connections} permissions={permissions} t={t} toast={toast} onChanged={refresh} />
      : section === "hosts"
        ? <ProxmoxNodes refreshKey={refreshKey} t={t} toast={toast} />
        : section === "repositories"
          ? <ProxmoxStorageView refreshKey={refreshKey} t={t} toast={toast} />
          : section === "environment"
            ? <ProxmoxClusterView refreshKey={refreshKey} t={t} toast={toast} />
            : section === "operations"
              ? <ProxmoxTasksView refreshKey={refreshKey} t={t} toast={toast} />
              : section === "audit"
                ? <ProxmoxAdvanced connections={connections} permissions={permissions} t={t} toast={toast} />
                : <ProxmoxConnections connections={connections} credentials={credentials} permissions={permissions} t={t} toast={toast} onChanged={refresh} />;

  return <ModuleAppShell
    className="proxmox-manager-app"
    name="Proxmox Manager"
    status={status}
    section={section}
    sections={sections}
    sectionLabels={sectionLabels}
    t={t}
    onSection={setSection}
    actions={<button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>}
  >
    {loading && !connections.length && !vms.length ? <div className="loading-state">{t("common.loading")}</div> : content}
  </ModuleAppShell>;
}
