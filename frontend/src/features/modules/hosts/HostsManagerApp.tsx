import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Download,
  Filter,
  Network,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Tags,
  Terminal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  type HostsManagerApmid,
  type HostsManagerBackup,
  type HostsManagerCapability,
  type HostsManagerCredential,
  type HostsManagerDashboard,
  type HostsManagerEnrollmentToken,
  type HostsManagerEnvironment,
  type HostsManagerGroup,
  type HostsManagerHostnamePattern,
  type HostsManagerHost,
  type HostsManagerOperation,
  type HostsManagerPowerProfile,
  type HostsManagerRepository,
  type HostsManagerSettings,
  type HostsManagerSettingsUpdate,
  type ModuleStatus,
} from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { useRefreshOnConnectionRestored } from "../../connection/ConnectionStatusMonitor";
import {
  ModuleAppShell,
  ModuleHealthCard,
  type ModuleSection,
} from "../common/ModuleAppShell";
import {
  HostsDataTable,
  type HostsDataColumn,
} from "./components/HostsDataTable";

type Props = { permissions: string[]; initialOperationId?: string; t: Translate; toast: ToastFn; onDeepLinkClose?: () => void };
const status: ModuleStatus = {
  installed: true,
  update_available: false,
  service_state: "not_applicable",
  service_enabled: false,
  services: {},
  health: "healthy",
  health_message: "",
  last_action: "",
  last_action_status: "",
  last_error: "",
  metrics: {},
  package_version: "2.0.0",
};
const sections: ModuleSection[] = [
  "overview",
  "hosts",
  "environment",
  "credentials",
  "installer",
  "settings",
  "audit",
];

function hostsManagerError(error: unknown, t: Translate): string {
  if (error instanceof ApiError) {
    const translated: Record<string, string> = {
      APMID_INACTIVE: "hosts.apmid.inactive",
      ENVIRONMENT_INACTIVE: "hosts.environment.inactive",
      APMID_GROUP_CONFLICT: "hosts.apmid.groupConflict",
      APMID_GROUP_SYNC_FAILED: "hosts.apmid.syncError",
      MANAGED_GROUP_PROTECTED: "hosts.group.managedProtected",
    };
    const key = error.code ? translated[error.code] : undefined;
    if (key) return t(key);
  }
  return error instanceof Error ? error.message : t("error.generic");
}

export function HostsManagerApp({ permissions, initialOperationId, t, toast, onDeepLinkClose }: Props) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [dashboard, setDashboard] = useState<HostsManagerDashboard | null>(
    null,
  );
  const [hosts, setHosts] = useState<HostsManagerHost[]>([]);
  const [groups, setGroups] = useState<HostsManagerGroup[]>([]);
  const [environments, setEnvironments] = useState<HostsManagerEnvironment[]>([]);
  const [apmids, setApmids] = useState<HostsManagerApmid[]>([]);
  const [hostnamePatterns, setHostnamePatterns] = useState<HostsManagerHostnamePattern[]>([]);
  const [tokens, setTokens] = useState<HostsManagerEnrollmentToken[]>([]);
  const [managerSettings, setManagerSettings] =
    useState<HostsManagerSettings | null>(null);
  const [operations, setOperations] = useState<HostsManagerOperation[]>([]);
  const [credentials, setCredentials] = useState<HostsManagerCredential[]>([]);
  const [repositories, setRepositories] = useState<HostsManagerRepository[]>(
    [],
  );
  const [powerProfiles, setPowerProfiles] = useState<
    HostsManagerPowerProfile[]
  >([]);
  const [diagnostics, setDiagnostics] = useState<
    Array<{ id: string; status: string; message: string }>
  >([]);
  const [backups, setBackups] = useState<HostsManagerBackup[]>([]);
  const [loading, setLoading] = useState(true);
  const can = (permission: string) => permissions.includes(permission);
  useEffect(() => {
    if (initialOperationId) setSection("audit");
  }, [initialOperationId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const base = await Promise.all([
        api.hostsManagerDashboard(),
        api.hostsManagerHosts(),
        api.hostsManagerGroups(),
        api.hostsManagerSettings(),
        api.hostsManagerEnvironments(),
        api.hostsManagerHostnamePatterns(),
        api.hostsManagerApmids(),
      ]);
      setDashboard(base[0]);
      setHosts(base[1]);
      setGroups(base[2]);
      setManagerSettings(base[3]);
      setEnvironments(base[4]);
      setHostnamePatterns(base[5]);
      setApmids(base[6]);
      if (permissions.includes("hosts-manager.hosts.manage"))
        setTokens(await api.hostsManagerEnrollmentTokens());
      if (permissions.includes("hosts-manager.audit.view"))
        setOperations(await api.hostsManagerOperations());
      if (permissions.includes("hosts-manager.credentials.view"))
        setCredentials(await api.hostsManagerCredentials());
      if (permissions.includes("hosts-manager.repositories.view"))
        setRepositories(await api.hostsManagerRepositories());
      if (permissions.includes("hosts-manager.power.view"))
        setPowerProfiles(await api.hostsManagerPowerProfiles());
      if (permissions.includes("hosts-manager.configure"))
        setDiagnostics((await api.hostsManagerDiagnostics()).checks);
      if (permissions.includes("hosts-manager.backup"))
        setBackups(await api.hostsManagerBackups());
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
        "admin",
        "hosts-manager",
      );
    } finally {
      setLoading(false);
    }
  }, [permissions, t, toast]);

  useRefreshOnConnectionRestored(() => { void refresh(); });
  useEffect(() => {
    void refresh();
  }, [refresh]);
  let content: React.ReactNode;
  if (section === "overview") content = <Dashboard value={dashboard} hosts={hosts} environments={environments} t={t} />;
  else if (section === "hosts")
    content = (
      <Hosts
        items={hosts}
        groups={groups}
        environments={environments}
        permissions={permissions}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "environment")
    content = (
      <EnvironmentManager
        items={environments}
        apmids={apmids}
        patterns={hostnamePatterns}
        credentials={credentials}
        canManage={can("hosts-manager.hosts.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "installer")
    content = (
      <Installer
        items={tokens}
        apmids={apmids}
        environments={environments}
        credentials={credentials}
        patterns={hostnamePatterns}
        groups={groups}
        settings={managerSettings}
        canManage={can("hosts-manager.hosts.manage")}
        canDiscover={can("hosts-manager.discovery")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "audit")
    content = can("hosts-manager.audit.view") ? (
      <Operations items={operations} initialOperationId={initialOperationId} t={t} toast={toast} onDeepLinkClose={onDeepLinkClose} />
    ) : (
      <div className="empty-state">{t("hosts.audit.permissionRequired")}</div>
    );
  else if (section === "credentials")
    content = (
      <Credentials
        items={credentials}
        environments={environments}
        canManage={can("hosts-manager.credentials.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else
    content = (
      <SettingsWorkspace
        value={managerSettings}
        patterns={hostnamePatterns}
        groups={groups}
        repositories={repositories}
        powerProfiles={powerProfiles}
        diagnostics={diagnostics}
        backups={backups}
        canManageInventory={can("hosts-manager.inventory.manage")}
        canManageRepositories={can("hosts-manager.repositories.manage")}
        canManageBackup={can("hosts-manager.backup")}
        canManageHosts={can("hosts-manager.hosts.manage")}
        canManage={can("hosts-manager.configure")}
        t={t}
        toast={toast}
        onChange={setManagerSettings}
        refresh={refresh}
      />
    );
  return (
    <ModuleAppShell
      className="hosts-manager-app"
      name={t("hosts.name")}
      status={status}
      healthMessage={t("hosts.subtitle")}
      section={section}
      sections={sections}
      t={t}
      onSection={(next) => { setSection(next); if (initialOperationId && next !== "audit") onDeepLinkClose?.(); }}
      actions={
        <button type="button" onClick={() => void refresh()}>
          <RefreshCw className={loading ? "spin" : ""} />
          {t("action.refresh")}
        </button>
      }
    >
      {loading && !dashboard ? (
        <div className="loading-state">{t("status.loading")}</div>
      ) : (
        content
      )}
    </ModuleAppShell>
  );
}

function Dashboard({
  value,
  hosts,
  environments,
  t,
}: {
  value: HostsManagerDashboard | null;
  hosts: HostsManagerHost[];
  environments: HostsManagerEnvironment[];
  t: Translate;
}) {
  const [environment, setEnvironment] = useState("");
  if (!value) return null;
  const scoped = environment ? hosts.filter((item) => item.environment === environment) : hosts;
  const count = (predicate: (item: HostsManagerHost) => boolean, fallback: number) =>
    environment ? scoped.filter(predicate).length : fallback;
  const sum = (selector: (item: HostsManagerHost) => number, fallback: number) =>
    environment ? scoped.reduce((total, item) => total + selector(item), 0) : fallback;
  const now = value.generated_at || 0;
  const staleReport = (item: HostsManagerHost) => {
    if (!item.agent) return false;
    const lastReport = item.agent.last_report_at || 0;
    return !lastReport || now - lastReport > Math.max(item.agent.report_interval_seconds * 3, 900);
  };
  const lowDisk = (item: HostsManagerHost) => {
    const filesystems = item.latest_report?.hardware?.filesystems;
    return Array.isArray(filesystems) && filesystems.some((filesystem) => {
      if (!filesystem || typeof filesystem !== "object") return false;
      const value = filesystem as Record<string, unknown>;
      return Number(value.free_percent ?? 100) < 10 || Number(value.used_percent ?? 0) >= 90;
    });
  };
  const cards: Array<
    [string, number, "neutral" | "success" | "warning" | "danger"]
  > = [
    ["total", environment ? scoped.length : value.total, "neutral"],
    ["online", count((item) => item.connection_status === "online", value.online), "success"],
    ["offline", count((item) => item.connection_status === "offline", value.offline), "danger"],
    ["errors", count((item) => Boolean(item.last_error) || item.agent_status === "error", value.errors || 0), "danger"],
    ["pendingRegistration", count((item) => ["pending", "installing"].includes(item.status || ""), value.pending_registration || 0), "warning"],
    ["availableUpdates", sum((item) => item.available_updates || 0, value.available_updates || 0), "neutral"],
    ["securityUpdates", sum((item) => item.security_updates || 0, value.security_updates || 0), "danger"],
    ["withoutAgent", count((item) => !item.agent, value.without_agent || 0), "warning"],
    ["staleReports", count(staleReport, value.stale_reports || 0), "warning"],
    ["lowDisk", count(lowDisk, value.low_disk || 0), "warning"],
    ["highCpu", count((item) => Number(item.latest_report?.system?.cpu_percent || 0) >= 90, value.high_cpu || 0), "warning"],
    ["highMemory", count((item) => Number(item.latest_report?.system?.memory_percent || 0) >= 90, value.high_memory || 0), "warning"],
    ["unverified", value.unverified, "warning"],
  ];
  return (
    <>
      <div className="hosts-dashboard-toolbar">
        <label>
          {t("hosts.dashboard.environmentFilter")}
          <select value={environment} onChange={(event) => setEnvironment(event.target.value)}>
            <option value="">{t("hosts.dashboard.allEnvironments")}</option>
            {environments.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
      </div>
      <div className="module-health-grid hosts-dashboard-grid">
        {cards.map(([key, count, tone]) => (
          <ModuleHealthCard
            key={key}
            title={t(`hosts.dashboard.${key}`)}
            value={count}
            tone={tone}
          />
        ))}
      </div>
      <div className="hosts-dashboard-columns">
        <section className="ansible-panel">
          <h3>{t("hosts.dashboard.byEnvironment")}</h3>
          <div className="hosts-environment-summary">
            {environments.map((item) => <div key={item.id}><i style={{ background: item.color }} /><span>{item.name}</span><strong>{value.by_environment?.[item.id] ?? item.host_count}</strong></div>)}
          </div>
        </section>
        <section className="ansible-panel">
          <h3>{t("hosts.dashboard.recentHosts")}</h3>
          <div className="hosts-compact-list">
            {(value.recent_hosts || []).map((item) => <div key={item.id}><Server /><span><strong>{item.hostname || item.name}</strong><small>{item.address}</small></span><Status value={item.status || item.connection_status} t={t} /></div>)}
            {!value.recent_hosts?.length && <div className="empty-state">{t("hosts.records.empty")}</div>}
          </div>
        </section>
        <section className="ansible-panel">
          <h3>{t("hosts.dashboard.recentConnections")}</h3>
          <div className="hosts-compact-list">
            {(value.recent_connections || []).map((item) => <div key={item.id}><Radio /><span><strong>{item.hostname || item.name}</strong><small>{item.agent?.last_heartbeat_at ? new Date(item.agent.last_heartbeat_at * 1000).toLocaleString() : t("common.none")}</small></span><Status value={item.agent_status || item.connection_status} t={t} /></div>)}
            {!value.recent_connections?.length && <div className="empty-state">{t("hosts.records.empty")}</div>}
          </div>
        </section>
      </div>
      <div className="hosts-dashboard-activity-grid">
        <section className="ansible-panel">
          <h3>{t("hosts.dashboard.onboardingHistory")}</h3>
          <Operations items={value.onboarding_history || []} t={t} />
        </section>
        <section className="ansible-panel">
          <h3>{t("hosts.dashboard.hostnameChanges")}</h3>
          <Operations items={value.hostname_changes || []} t={t} />
        </section>
      </div>
      <div className="ansible-panel">
        <h3>{t("hosts.dashboard.administrativeOperations")}</h3>
        <Operations items={value.administrative_operations || value.recent_operations} t={t} />
      </div>
      <section className="ansible-panel">
        <h3>{t("hosts.dashboard.recentErrors")}</h3>
        {value.recent_errors.length ? (
          value.recent_errors.map((item) => (
            <article className="module-diagnostic" key={item.id}>
              <AlertTriangle />
              <strong>{item.name}</strong>
              <span>{item.last_error}</span>
            </article>
          ))
        ) : (
          <div className="empty-state">
            {t("hosts.dashboard.noRecentErrors")}
          </div>
        )}
      </section>
    </>
  );
}

function Hosts({
  items,
  groups,
  environments,
  permissions,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerHost[];
  groups: HostsManagerGroup[];
  environments: HostsManagerEnvironment[];
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [environmentFilter, setEnvironmentFilter] = useState("");
  const [osFilter, setOsFilter] = useState("");
  const [cards, setCards] = useState(false);
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [editing, setEditing] = useState<HostsManagerHost | null | undefined>();
  const [selected, setSelected] = useState<HostsManagerHost | null>(null);
  const filtered = useMemo(
    () =>
      items.filter(
        (item) =>
          (!query ||
            `${item.name} ${item.address} ${item.hostname} ${item.tags.join(" ")}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (!statusFilter ||
            item.status === statusFilter ||
            item.connection_status === statusFilter ||
            item.agent_status === statusFilter) &&
          (!environmentFilter || item.environment === environmentFilter) &&
          (!osFilter || item.distribution === osFilter),
      ),
    [environmentFilter, items, osFilter, query, statusFilter],
  );
  const pageSize = 25;
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const paged = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const operatingSystems = [...new Set(items.map((item) => item.distribution || "").filter(Boolean))].sort();
  const canManage = permissions.includes("hosts-manager.hosts.manage");
  async function remove(item: HostsManagerHost) {
    if (!window.confirm(t("hosts.host.deleteConfirm").replace("{name}", item.name))) return;
    try {
      await api.deleteHostsManagerHost(item.id, item.name);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function disable(item: HostsManagerHost) {
    if (!window.confirm(t("hosts.host.disableConfirm").replace("{name}", item.name))) return;
    try {
      await api.disableHostsManagerHost(item.id);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function bulkDisable() {
    if (!selectedIds.length || !window.confirm(t("hosts.bulk.disableConfirm").replace("{count}", String(selectedIds.length)))) return;
    try {
      await Promise.all(selectedIds.map((id) => api.disableHostsManagerHost(id)));
      setSelectedIds([]);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  function toggle(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }
  const columns: HostsDataColumn<HostsManagerHost>[] = [
    { id: "select", label: "", cell: (item) => <input type="checkbox" aria-label={t("hosts.host.select").replace("{name}", item.name)} checked={selectedIds.includes(item.id)} onClick={(event) => event.stopPropagation()} onChange={() => toggle(item.id)} /> },
    { id: "status", label: t("common.status"), sortValue: (item) => item.status || item.connection_status, cell: (item) => <Status value={item.status || item.connection_status} t={t} /> },
    { id: "name", label: t("hosts.host.hostname"), sortValue: (item) => item.hostname || item.name, cell: (item) => <span className="hosts-primary-cell"><strong>{item.hostname || item.name}</strong><small>{item.fqdn || item.name}</small></span> },
    { id: "address", label: t("hosts.host.address"), sortValue: (item) => item.address, cell: (item) => item.address },
    { id: "distribution", label: t("hosts.host.distribution"), sortValue: (item) => item.distribution || "", cell: (item) => item.distribution || t("common.none") },
    { id: "systemVersion", label: t("hosts.host.systemVersion"), sortValue: (item) => item.system_version || "", cell: (item) => item.system_version || t("common.none") },
    { id: "environment", label: t("hosts.host.environment"), sortValue: (item) => item.environment, cell: (item) => environments.find((environment) => environment.id === item.environment)?.name || item.environment || t("common.none") },
    { id: "agentVersion", label: t("hosts.host.agentVersion"), sortValue: (item) => item.agent_version || "", cell: (item) => item.agent_version || t("common.none") },
    { id: "agentState", label: t("hosts.host.agentState"), sortValue: (item) => item.agent_status || "", cell: (item) => <Status value={item.agent_status || "not_installed"} t={t} /> },
    { id: "lastConnection", label: t("hosts.host.lastConnection"), sortValue: (item) => item.agent?.last_heartbeat_at || 0, cell: (item) => item.agent?.last_heartbeat_at ? new Date(item.agent.last_heartbeat_at * 1000).toLocaleString() : t("common.none") },
    { id: "updates", label: t("hosts.host.updates"), sortValue: (item) => item.available_updates || 0, align: "end", cell: (item) => item.available_updates || 0 },
    { id: "created", label: t("hosts.host.createdAt"), sortValue: (item) => item.created_at, cell: (item) => new Date(item.created_at * 1000).toLocaleDateString() },
    { id: "actions", label: t("column.actions"), cell: (item) => <div className="module-row-actions"><button onClick={() => setSelected(item)}>{t("hosts.host.details")}</button>{canManage && <><button onClick={() => setEditing(item)}>{t("action.edit")}</button>{item.active && <button onClick={() => void disable(item)}>{t("action.disable")}</button>}<button className="button-danger" onClick={() => void remove(item)}>{t("action.delete")}</button></>}</div> },
  ];
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.list.title")}</h3>
          <p>{t("hosts.list.hint")}</p>
        </div>
        {canManage && (
          <button className="button-primary" onClick={() => setEditing(null)}>
            <Plus />
            {t("hosts.host.add")}
          </button>
        )}
      </header>
      <div className="module-section-toolbar">
        <label>
          <Search />
          <input
            aria-label={t("action.search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("hosts.search.placeholder")}
          />
        </label>
        <label>
          <Filter />
          <select
            aria-label={t("hosts.filter.status")}
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">{t("hosts.filter.all")}</option>
            <option value="online">{t("hosts.status.online")}</option>
            <option value="offline">{t("hosts.status.offline")}</option>
            <option value="warning">{t("hosts.status.warning")}</option>
            <option value="error">{t("hosts.status.error")}</option>
            <option value="pending">{t("hosts.status.pending")}</option>
            <option value="unregistered">{t("hosts.status.unregistered")}</option>
          </select>
        </label>
        <label>
          <Tags />
          <select aria-label={t("hosts.filter.environment")} value={environmentFilter} onChange={(event) => { setEnvironmentFilter(event.target.value); setPage(1); }}>
            <option value="">{t("hosts.filter.allEnvironments")}</option>
            {environments.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label>
          <Terminal />
          <select aria-label={t("hosts.filter.os")} value={osFilter} onChange={(event) => { setOsFilter(event.target.value); setPage(1); }}>
            <option value="">{t("hosts.filter.allSystems")}</option>
            {operatingSystems.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <a className="button" href="/api/modules/hosts-manager/hosts-export.csv" download>{t("hosts.list.exportCsv")}</a>
        {canManage && selectedIds.length > 0 && <button type="button" onClick={() => void bulkDisable()}>{t("hosts.bulk.disable")} ({selectedIds.length})</button>}
        <button type="button" onClick={() => setCards((value) => !value)}>
          {t(cards ? "hosts.view.list" : "hosts.view.cards")}
        </button>
      </div>
      {cards ? (
        <div className="card-grid">
          {paged.map((item) => (
            <article className="data-card" key={item.id}>
              <header>
                <Server />
                <strong>{item.name}</strong>
                <Status value={item.connection_status} t={t} />
              </header>
              <p>
                {item.address}:{item.port}
              </p>
              <small>
                {item.environment || t("common.none")} ·{" "}
                {item.location || t("common.none")}
              </small>
              <button onClick={() => setSelected(item)}>
                {t("hosts.host.details")}
              </button>
            </article>
          ))}
        </div>
      ) : (
        <HostsDataTable
          items={paged}
          columns={columns}
          rowKey={(item) => item.id}
          empty={t("hosts.list.empty")}
          onSelect={(item) => setSelected(item)}
          selectedKey={selected?.id}
        />
      )}
      <footer className="hosts-pagination">
        <span>{t("hosts.pagination.summary").replace("{from}", String(filtered.length ? (currentPage - 1) * pageSize + 1 : 0)).replace("{to}", String(Math.min(currentPage * pageSize, filtered.length))).replace("{total}", String(filtered.length))}</span>
        <div>
          <button type="button" disabled={currentPage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>{t("action.previous")}</button>
          <strong>{currentPage} / {pages}</strong>
          <button type="button" disabled={currentPage >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))}>{t("action.next")}</button>
        </div>
      </footer>
      {editing !== undefined && (
        <HostForm
          value={editing}
          groups={groups}
          environments={environments}
          t={t}
          toast={toast}
          onClose={() => setEditing(undefined)}
          onSaved={refresh}
        />
      )}
      {selected && (
        <HostDetails
          value={selected}
          permissions={permissions}
          t={t}
          toast={toast}
          onClose={() => setSelected(null)}
          refresh={refresh}
        />
      )}
    </section>
  );
}

function HostForm({
  value,
  groups,
  environments,
  t,
  toast,
  onClose,
  onSaved,
}: {
  value: HostsManagerHost | null;
  groups: HostsManagerGroup[];
  environments: HostsManagerEnvironment[];
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(value?.name || "");
  const [address, setAddress] = useState(value?.address || "");
  const [port, setPort] = useState(value?.port || 22);
  const [user, setUser] = useState(value?.ssh_user || "algen-ansible");
  const [environment, setEnvironment] = useState(value?.environment || "");
  const [location, setLocation] = useState(value?.location || "");
  const [description, setDescription] = useState(value?.description || "");
  const [tags, setTags] = useState(value?.tags.join(", ") || "");
  const [groupIds, setGroupIds] = useState(value?.group_ids || []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerHost(
        {
          name,
          hostname: value?.hostname || "",
          fqdn: value?.fqdn || "",
          address,
          management_address: value?.management_address || "",
          port,
          connection_type: value?.connection_type || "ssh",
          ssh_user: user,
          credential_id: value?.credential_id || null,
          python_interpreter: value?.python_interpreter || "auto_silent",
          environment,
          location,
          description,
          tags: tags
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          variables: value?.variables || {},
          group_ids: groupIds,
          active: value?.active ?? true,
          approved: value?.approved ?? false,
          power_profile_id: null,
        },
        value?.id,
      );
      toast(t("hosts.host.saved"), "ok");
      await onSaved();
      onClose();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  return (
    <Modal
      wide
      title={t(value ? "hosts.host.edit" : "hosts.host.add")}
      closeLabel={t("action.close")}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>{t("action.cancel")}</button>
          <button
            className="button-primary"
            type="submit"
            form="hosts-host-form"
          >
            {t("action.save")}
          </button>
        </>
      }
    >
      <form id="hosts-host-form" className="module-form-grid" onSubmit={save}>
        <label>
          {t("common.name")}
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          {t("hosts.host.address")}
          <input
            required
            value={address}
            onChange={(event) => setAddress(event.target.value)}
          />
        </label>
        <label>
          {t("hosts.host.port")}
          <input
            type="number"
            min="1"
            max="65535"
            value={port}
            onChange={(event) => setPort(Number(event.target.value))}
          />
        </label>
        <label>
          {t("hosts.host.user")}
          <input
            required
            value={user}
            onChange={(event) => setUser(event.target.value)}
          />
        </label>
        <label>
          {t("hosts.host.environment")}
          <select value={environment} onChange={(event) => setEnvironment(event.target.value)}>
            <option value="">{t("common.none")}</option>
            {environments.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label>
          {t("hosts.host.location")}
          <input
            value={location}
            onChange={(event) => setLocation(event.target.value)}
          />
        </label>
        <label className="wide">
          {t("hosts.host.description")}
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="wide">
          {t("hosts.host.tags")}
          <input
            value={tags}
            onChange={(event) => setTags(event.target.value)}
          />
        </label>
        <fieldset className="wide">
          <legend>{t("hosts.groups.title")}</legend>
          {groups.map((group) => (
            <label className="check" key={group.id}>
              <input
                type="checkbox"
                checked={groupIds.includes(group.id)}
                onChange={(event) =>
                  setGroupIds((current) =>
                    event.target.checked
                      ? [...current, group.id]
                      : current.filter((id) => id !== group.id),
                  )
                }
              />
              {group.name}
            </label>
          ))}
        </fieldset>
      </form>
    </Modal>
  );
}

function HostDetails({
  value,
  permissions,
  t,
  toast,
  onClose,
  refresh,
}: {
  value: HostsManagerHost;
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  refresh: () => Promise<void>;
}) {
  const [capabilities, setCapabilities] = useState<HostsManagerCapability[]>(
    [],
  );
  const [plan, setPlan] = useState<{
    capability: HostsManagerCapability;
    value: Record<string, unknown>;
  } | null>(null);
  const [tab, setTab] = useState<"summary" | "hardware" | "system" | "repositories" | "packages" | "agent" | "history">("summary");
  const [history, setHistory] = useState<{ identities: Array<Record<string, unknown>>; reports: Array<Record<string, unknown>>; versions: Array<Record<string, unknown>>; operations: HostsManagerOperation[] } | null>(null);
  const [agentToken, setAgentToken] = useState("");
  useEffect(() => {
    void api.hostsManagerCapabilities(value.id).then(setCapabilities);
  }, [value.id]);
  useEffect(() => {
    if (tab !== "history" || !permissions.includes("hosts-manager.audit.view")) return;
    void api.hostsManagerAgentHistory(value.id).then(setHistory).catch(() => setHistory(null));
  }, [permissions, tab, value.id]);
  async function review(capability: HostsManagerCapability) {
    try {
      setPlan({
        capability,
        value: await api.hostsManagerActionPlan(value.id, capability.id),
      });
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  async function execute() {
    if (!plan) return;
    try {
      await api.executeHostsManagerAction(
        value.id,
        plan.capability.id,
        {},
        value.name,
      );
      toast(t("hosts.action.queued"), "ok");
      setPlan(null);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  async function regenerateIdentity() {
    if (!window.confirm(t("hosts.agent.regenerateConfirm"))) return;
    try {
      const result = await api.regenerateHostsManagerAgentIdentity(value.id);
      setAgentToken(result.token);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function invalidateIdentity() {
    if (!window.confirm(t("hosts.agent.invalidateConfirm"))) return;
    try {
      await api.invalidateHostsManagerAgentIdentity(value.id);
      toast(t("hosts.agent.identityInvalidated"), "ok");
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  const report = value.latest_report || {};
  const basic = report.basic || {};
  const hardware = report.hardware || {};
  const system = report.system || {};
  const packages = report.packages || {};
  const filesystems = Array.isArray(hardware.filesystems)
    ? (hardware.filesystems as Array<Record<string, unknown>>)
    : [];
  const diskUsed = filesystems.reduce(
    (highest, item) => Math.max(highest, Number(item.used_percent || 0)),
    0,
  );
  const failedServices =
    (system.services as { failed?: unknown[] } | undefined)?.failed || [];
  const alerts = [
    ...(Number(system.cpu_percent || 0) >= 90 ? [t("hosts.alert.highCpu")] : []),
    ...(Number(system.memory_percent || 0) >= 90
      ? [t("hosts.alert.highMemory")]
      : []),
    ...(diskUsed >= 90 ? [t("hosts.alert.lowDisk")] : []),
    ...(failedServices.length ? [t("hosts.alert.failedServices")] : []),
    ...((value.security_updates || 0) > 0
      ? [t("hosts.alert.securityUpdates")]
      : []),
  ];
  return (
    <Modal
      wide
      title={value.name}
      closeLabel={t("action.close")}
      onClose={onClose}
    >
      <header className="hosts-detail-hero">
        <div><Server /><span><strong>{value.hostname || value.name}</strong><small>{value.address} · {value.environment_details?.name || value.environment || t("common.none")}</small></span></div>
        <Status value={value.status || value.connection_status} t={t} />
        <dl>
          <div><dt>{t("hosts.host.distribution")}</dt><dd>{value.distribution || t("common.none")} {value.system_version || ""}</dd></div>
          <div><dt>{t("hosts.host.agentVersion")}</dt><dd>{value.agent_version || t("common.none")}</dd></div>
          <div><dt>{t("hosts.host.lastReport")}</dt><dd>{value.agent?.last_report_at ? new Date(value.agent.last_report_at * 1000).toLocaleString() : t("common.none")}</dd></div>
        </dl>
      </header>
      <nav className="hosts-detail-tabs" aria-label={t("hosts.details.tabs")}>
        {(["summary", "hardware", "system", "repositories", "packages", "agent", "history"] as const).map((item) => <button key={item} type="button" className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{t(`hosts.details.tab.${item}`)}</button>)}
      </nav>
      <div className="hosts-detail-content">
        {tab === "summary" && <div className="hosts-summary-layout">
          <div className="module-health-grid">
            <ModuleHealthCard title={t("hosts.metric.cpu")} value={`${Number(system.cpu_percent || 0).toFixed(1)}%`} tone={Number(system.cpu_percent || 0) >= 90 ? "danger" : "neutral"} />
            <ModuleHealthCard title={t("hosts.metric.memory")} value={`${Number(system.memory_percent || 0).toFixed(1)}%`} tone={Number(system.memory_percent || 0) >= 90 ? "danger" : "neutral"} />
            <ModuleHealthCard title={t("hosts.metric.disk")} value={`${diskUsed.toFixed(1)}%`} tone={diskUsed >= 90 ? "danger" : "neutral"} />
            <ModuleHealthCard title={t("hosts.metric.uptime")} value={formatDuration(Number(basic.uptime_seconds || 0))} />
            <ModuleHealthCard title={t("hosts.host.updates")} value={value.available_updates || 0} tone={(value.security_updates || 0) > 0 ? "danger" : "neutral"} />
          </div>
          <section className="hosts-detail-card"><h3>{t("hosts.details.summary")}</h3><dl className="hosts-definition-grid">
            <dt>{t("hosts.host.address")}</dt><dd>{value.address}:{value.port}</dd>
            <dt>{t("hosts.host.fqdn")}</dt><dd>{value.fqdn || String(basic.fqdn || t("common.none"))}</dd>
            <dt>{t("hosts.host.environment")}</dt><dd>{value.environment_details?.name || value.environment || t("common.none")}</dd>
            <dt>{t("hosts.host.fingerprint")}</dt><dd><Status value={value.fingerprint_status} t={t} /></dd>
            <dt>{t("hosts.host.approval")}</dt><dd>{t(value.approved ? "common.yes" : "common.no")}</dd>
          </dl></section>
          <section className="hosts-detail-card"><h3>{t("hosts.alert.active")}</h3>{alerts.length ? alerts.map((item) => <div className="module-diagnostic" key={item}><AlertTriangle /><span>{item}</span></div>) : <div className="empty-state">{t("hosts.alert.none")}</div>}</section>
        </div>}
        {tab === "hardware" && <ReportPanel title={t("hosts.details.tab.hardware")} value={hardware} empty={t("hosts.details.noReport")} />}
        {tab === "system" && <ReportPanel title={t("hosts.details.tab.system")} value={{ ...basic, ...system, legacy_facts: value.facts || {} }} empty={t("hosts.details.noReport")} />}
        {tab === "repositories" && <ReportPanel title={t("hosts.details.tab.repositories")} value={{ manager: packages.manager, repositories: packages.repositories || [] }} empty={t("hosts.details.noReport")} />}
        {tab === "packages" && <ReportPanel title={t("hosts.details.tab.packages")} value={packages} empty={t("hosts.details.noReport")} />}
        {tab === "agent" && <div className="hosts-agent-panel">
          <section className="hosts-detail-card"><h3>{t("hosts.details.tab.agent")}</h3><dl className="hosts-definition-grid">
            <dt>{t("common.status")}</dt><dd><Status value={value.agent_status || "not_installed"} t={t} /></dd>
            <dt>{t("hosts.host.agentVersion")}</dt><dd>{value.agent?.agent_version || t("common.none")}</dd>
            <dt>{t("hosts.agent.port")}</dt><dd>{value.agent?.communication_port || t("common.none")}</dd>
            <dt>{t("hosts.agent.installedAt")}</dt><dd>{value.agent?.installed_at ? new Date(value.agent.installed_at * 1000).toLocaleString() : t("common.none")}</dd>
            <dt>{t("hosts.host.lastConnection")}</dt><dd>{value.agent?.last_heartbeat_at ? new Date(value.agent.last_heartbeat_at * 1000).toLocaleString() : t("common.none")}</dd>
            <dt>{t("hosts.agent.identifier")}</dt><dd><code>{value.agent?.id || t("common.none")}</code></dd>
            <dt>{t("hosts.agent.identityStatus")}</dt><dd><Status value={String(value.identity?.status || "unregistered")} t={t} /></dd>
            <dt>{t("hosts.agent.reportInterval")}</dt><dd>{value.agent?.report_interval_seconds ? `${value.agent.report_interval_seconds}s` : t("common.none")}</dd>
          </dl></section>
          {permissions.includes("hosts-manager.hosts.manage") && <div className="module-section-toolbar">
            {value.agent && <><button type="button" onClick={() => void regenerateIdentity()}>{t("hosts.agent.regenerateIdentity")}</button><button className="button-danger" type="button" onClick={() => void invalidateIdentity()}>{t("hosts.agent.invalidateIdentity")}</button></>}
          </div>}
          <ReportPanel title={t("hosts.agent.logs")} value={{ entries: system.agent_log || [] }} empty={t("hosts.details.noReport")} />
        </div>}
        {tab === "history" && (permissions.includes("hosts-manager.audit.view") ? <div className="hosts-history-panels">
          <section className="hosts-detail-card"><h3>{t("hosts.agent.identityHistory")}</h3><pre>{JSON.stringify(history?.identities || [], null, 2)}</pre></section>
          <section className="hosts-detail-card"><h3>{t("hosts.agent.versionHistory")}</h3><pre>{JSON.stringify(history?.versions || [], null, 2)}</pre></section>
          <section className="hosts-detail-card"><h3>{t("hosts.operations.recent")}</h3><Operations items={history?.operations || []} t={t} /></section>
        </div> : <div className="empty-state">{t("hosts.audit.permissionRequired")}</div>)}
      </div>
      <section>
        <h3>{t("hosts.details.actions")}</h3>
        <div className="module-section-toolbar">
          {capabilities
            .filter((item) => permissions.includes(item.permission))
            .map((item) => (
              <button key={item.id} onClick={() => void review(item)}>
                {item.name}
              </button>
            ))}
          {!value.approved &&
            permissions.includes("hosts-manager.hosts.approve") && (
              <button
                onClick={() =>
                  void api.approveHostsManagerHost(value.id).then(refresh)
                }
              >
                <ShieldCheck />
                {t("hosts.action.approve")}
              </button>
            )}
        </div>
      </section>
      {plan && (
        <Modal
          title={t("hosts.action.plan")}
          closeLabel={t("action.close")}
          onClose={() => setPlan(null)}
          footer={
            <>
              <button onClick={() => setPlan(null)}>
                {t("action.cancel")}
              </button>
              <button className="button-primary" onClick={() => void execute()}>
                {t("hosts.action.execute")}
              </button>
            </>
          }
        >
          <pre>{JSON.stringify(plan.value, null, 2)}</pre>
        </Modal>
      )}
      {agentToken && <Modal title={t("hosts.agent.newToken")} closeLabel={t("action.close")} onClose={() => setAgentToken("")}><p>{t("hosts.agent.newTokenHint")}</p><code className="hosts-secret-once">{agentToken}</code><button type="button" onClick={() => void navigator.clipboard.writeText(agentToken)}><Copy />{t("action.copy")}</button></Modal>}
    </Modal>
  );
}

function formatDuration(seconds: number) {
  if (!seconds) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return `${days}d ${hours}h`;
}

function ReportPanel({ title, value, empty }: { title: string; value: Record<string, unknown>; empty: string }) {
  return <section className="hosts-detail-card"><h3>{title}</h3>{Object.keys(value).length ? <pre>{JSON.stringify(value, null, 2)}</pre> : <div className="empty-state">{empty}</div>}</section>;
}

function EnvironmentManager({
  items,
  apmids,
  patterns,
  credentials,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerEnvironment[];
  apmids: HostsManagerApmid[];
  patterns: HostsManagerHostnamePattern[];
  credentials: HostsManagerCredential[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<HostsManagerEnvironment | null | undefined>();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#187eb1");
  const [patternId, setPatternId] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [agentPort, setAgentPort] = useState(8443);
  const [reportInterval, setReportInterval] = useState(300);
  function edit(item: HostsManagerEnvironment | null) {
    setEditing(item);
    setName(item?.name || "");
    setSlug(item?.slug || "");
    setDescription(item?.description || "");
    setColor(item?.color || "#187eb1");
    setPatternId(item?.default_hostname_pattern_id || "");
    setCredentialId(item?.default_credential_id || "");
    setAgentPort(item?.default_agent_port || 8443);
    setReportInterval(item?.report_interval_seconds || 300);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerEnvironment({
        name,
        slug: slug || name.toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_]+/g, "-"),
        description,
        color,
        default_hostname_pattern_id: patternId || null,
        default_credential_id: credentialId || null,
        default_agent_port: agentPort,
        report_interval_seconds: reportInterval,
        active: editing?.active ?? true,
      }, editing?.id);
      setEditing(undefined);
      toast(t("hosts.environment.saved"), "ok");
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function remove(item: HostsManagerEnvironment) {
    if (!window.confirm(t("hosts.environment.deleteConfirm").replace("{name}", item.name))) return;
    try {
      await api.deleteHostsManagerEnvironment(item.id);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  return <div className="hosts-environment-workspace"><section className="ansible-panel hosts-environments">
    <header><div><h3>{t("hosts.environment.title")}</h3><p>{t("hosts.environment.hint")}</p></div>{canManage && <button className="button-primary" type="button" onClick={() => edit(null)}><Plus />{t("hosts.environment.create")}</button>}</header>
    <div className="hosts-environment-grid">
      {items.map((item) => <article key={item.id} className="hosts-environment-card" style={{ "--environment-color": item.color } as React.CSSProperties}>
        <header><i /><div><strong>{item.name}</strong><small>{item.slug}</small></div><Status value={item.active ? "active" : "disabled"} t={t} /></header>
        <p>{item.description || t("common.none")}</p>
        <dl><div><dt>{t("hosts.environment.hostCount")}</dt><dd>{item.host_count}</dd></div><div><dt>{t("hosts.environment.pattern")}</dt><dd>{patterns.find((pattern) => pattern.id === item.default_hostname_pattern_id)?.name || t("common.none")}</dd></div><div><dt>{t("hosts.agent.port")}</dt><dd>{item.default_agent_port}</dd></div><div><dt>{t("hosts.agent.reportInterval")}</dt><dd>{item.report_interval_seconds}s</dd></div></dl>
        {canManage && <footer><button type="button" onClick={() => edit(item)}>{t("action.edit")}</button><button className="button-danger" type="button" disabled={item.host_count > 0} title={item.host_count > 0 ? t("hosts.environment.moveFirst") : undefined} onClick={() => void remove(item)}>{t("action.delete")}</button></footer>}
      </article>)}
    </div>
    {editing !== undefined && <Modal wide title={t(editing ? "hosts.environment.edit" : "hosts.environment.create")} closeLabel={t("action.close")} onClose={() => setEditing(undefined)} footer={<><button type="button" onClick={() => setEditing(undefined)}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="hosts-environment-form">{t("action.save")}</button></>}>
      <form id="hosts-environment-form" className="module-form-grid" onSubmit={save}>
        <label>{t("common.name")}<input autoFocus required value={name} onChange={(event) => { setName(event.target.value); if (!editing) setSlug(event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); }} /></label>
        <label>{t("hosts.environment.slug")}<input required pattern="[a-z0-9][a-z0-9-]*" value={slug} onChange={(event) => setSlug(event.target.value)} /></label>
        <label>{t("hosts.environment.color")}<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label>
        <label>{t("hosts.environment.pattern")}<select value={patternId} onChange={(event) => setPatternId(event.target.value)}><option value="">{t("common.none")}</option>{patterns.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.next_hostname}</option>)}</select></label>
        <label>{t("hosts.environment.credential")}<select value={credentialId} onChange={(event) => setCredentialId(event.target.value)}><option value="">{t("common.none")}</option>{credentials.filter((item) => item.active && ["ssh_password", "ssh_private_key"].includes(item.type)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>{t("hosts.agent.port")}<input type="number" min={1} max={65535} value={agentPort} onChange={(event) => setAgentPort(Number(event.target.value))} /></label>
        <label>{t("hosts.agent.reportInterval")}<input type="number" min={30} max={86400} value={reportInterval} onChange={(event) => setReportInterval(Number(event.target.value))} /></label>
        <label className="wide">{t("hosts.host.description")}<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      </form>
    </Modal>}
  </section><ApmidManager items={apmids} canManage={canManage} t={t} toast={toast} refresh={refresh} /></div>;
}

function ApmidManager({
  items,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerApmid[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<HostsManagerApmid | null | undefined>();
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [active, setActive] = useState(true);
  const [syncing, setSyncing] = useState(false);
  function edit(item: HostsManagerApmid | null) {
    setEditing(item);
    setCode(item?.code || "");
    setDescription(item?.description || "");
    setActive(item?.active ?? true);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerApmid({ code, description, active }, editing?.id);
      setEditing(undefined);
      toast(t("hosts.apmid.saved"), "ok");
      await refresh();
    } catch (error) {
      toast(hostsManagerError(error, t), "error");
    }
  }
  async function remove(item: HostsManagerApmid) {
    if (!window.confirm(t("hosts.apmid.deleteConfirm").replace("{code}", item.code))) return;
    try {
      await api.deleteHostsManagerApmid(item.id);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function sync() {
    setSyncing(true);
    try {
      const result = await api.syncHostsManagerApmidGroups();
      toast(t("hosts.apmid.syncComplete").replace("{count}", String(result.total)), "ok");
      await refresh();
    } catch (error) {
      toast(hostsManagerError(error, t), "error");
    } finally {
      setSyncing(false);
    }
  }
  return <section className="ansible-panel hosts-apmids">
    <header>
      <div><h3>{t("hosts.apmid.title")}</h3><p>{t("hosts.apmid.hint")}</p></div>
      {canManage && <div className="hosts-header-actions"><button type="button" disabled={syncing} onClick={() => void sync()}><RefreshCw />{t("hosts.apmid.sync")}</button><button className="button-primary" type="button" onClick={() => edit(null)}><Plus />{t("hosts.apmid.create")}</button></div>}
    </header>
    {items.length ? <div className="hosts-environment-grid">
      {items.map((item) => <article key={item.id} className="hosts-environment-card hosts-apmid-card">
        <header><div><strong>{item.code}</strong><small>{t("hosts.apmid.managedGroups").replace("{count}", String(item.environment_groups.length))}</small></div><Status value={item.active ? "active" : "disabled"} t={t} /></header>
        <p>{item.description || t("common.none")}</p>
        <ul>{item.environment_groups.map((group) => <li key={group.group_id}><code>{group.group_name}</code><Status value={group.active ? "active" : "disabled"} t={t} /></li>)}</ul>
        {canManage && <footer><button type="button" onClick={() => edit(item)}>{t("action.edit")}</button><button className="button-danger" type="button" onClick={() => void remove(item)}>{t("action.delete")}</button></footer>}
      </article>)}
    </div> : <div className="empty-state">{t("hosts.apmid.empty")}</div>}
    {editing !== undefined && <Modal title={t(editing ? "hosts.apmid.edit" : "hosts.apmid.create")} closeLabel={t("action.close")} onClose={() => setEditing(undefined)} footer={<><button type="button" onClick={() => setEditing(undefined)}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="hosts-apmid-form">{t("action.save")}</button></>}>
      <form id="hosts-apmid-form" className="module-form-grid" onSubmit={save}>
        <label>{t("hosts.apmid.code")}<input autoFocus required maxLength={64} pattern="[A-Za-z0-9_-]+" value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} /></label>
        <label className="check"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />{t("common.enabled")}</label>
        <label className="wide">{t("hosts.host.description")}<textarea maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
      </form>
    </Modal>}
  </section>;
}

function Groups({
  items,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerGroup[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<HostsManagerGroup | null | undefined>();
  const [selected, setSelected] = useState<HostsManagerGroup | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [parentId, setParentId] = useState("");
  const [active, setActive] = useState(true);
  const visible = items.filter((item) =>
    `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase()),
  );
  function edit(item: HostsManagerGroup | null) {
    setEditing(item);
    setName(item?.name || "");
    setDescription(item?.description || "");
    setParentId(item?.parent_id || "");
    setActive(item?.active ?? true);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerGroup({
        name,
        description,
        parent_id: parentId || null,
        variables: editing?.variables || {},
        host_ids: editing?.host_ids || [],
        active,
      }, editing?.id);
      setEditing(undefined);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function remove(item: HostsManagerGroup) {
    if (!window.confirm(t("hosts.group.deleteConfirm").replace("{name}", item.name))) return;
    try {
      await api.deleteHostsManagerGroup(item.id);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  const columns: HostsDataColumn<HostsManagerGroup>[] = [
    { id: "name", label: t("common.name"), sortValue: (item) => item.name, cell: (item) => <span><strong>{item.name}</strong>{item.managed && <small>{t("hosts.group.managed")}</small>}</span> },
    { id: "description", label: t("hosts.host.description"), sortValue: (item) => item.description, cell: (item) => item.description || t("common.none") },
    { id: "parent", label: t("hosts.group.parent"), sortValue: (item) => items.find((parent) => parent.id === item.parent_id)?.name || "", cell: (item) => items.find((parent) => parent.id === item.parent_id)?.name || t("common.none") },
    { id: "hosts", label: t("hosts.groups.hosts"), align: "end", sortValue: (item) => item.host_ids.length, cell: (item) => item.host_ids.length },
    { id: "status", label: t("common.status"), sortValue: (item) => item.active ? 1 : 0, cell: (item) => <Status value={item.active ? "active" : "disabled"} t={t} /> },
    { id: "updated", label: t("hosts.operation.updated"), sortValue: (item) => item.updated_at, cell: (item) => new Date(item.updated_at * 1000).toLocaleString() },
    { id: "actions", label: t("column.actions"), cell: (item) => <div className="module-row-actions"><button onClick={() => setSelected(item)}>{t("hosts.group.showHosts")}</button>{canManage && !item.managed && <><button onClick={() => edit(item)}>{t("action.edit")}</button><button className="button-danger" onClick={() => void remove(item)}>{t("action.delete")}</button></>}</div> },
  ];
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.groups.title")}</h3>
          <p>{t("hosts.groups.hint")}</p>
        </div>
        {canManage && (
          <button onClick={() => edit(null)}>
            <Plus />
            {t("hosts.group.add")}
          </button>
        )}
      </header>
      <div className="module-section-toolbar">
        <label>
          <Search />
          <input aria-label={t("action.search")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("hosts.search.placeholder")} />
        </label>
      </div>
      <HostsDataTable items={visible} columns={columns} rowKey={(item) => item.id} empty={t("hosts.records.empty")} onSelect={(item) => setSelected(item)} selectedKey={selected?.id} />
      {editing !== undefined && (
        <Modal
          title={t(editing ? "hosts.group.edit" : "hosts.group.add")}
          closeLabel={t("action.close")}
          onClose={() => setEditing(undefined)}
          footer={
            <button
              className="button-primary"
              type="submit"
              form="hosts-group-form"
            >
              {t("action.save")}
            </button>
          }
        >
          <form id="hosts-group-form" className="module-form-grid" onSubmit={save}>
            <label>
              {t("common.name")}
              <input autoFocus required value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>{t("hosts.host.description")}<input value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <label>{t("hosts.group.parent")}<select value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">{t("common.none")}</option>{items.filter((item) => item.id !== editing?.id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label className="check"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />{t("common.enabled")}</label>
          </form>
        </Modal>
      )}
      {selected && <Modal title={selected.name} closeLabel={t("action.close")} onClose={() => setSelected(null)}><h3>{t("hosts.group.memberHosts")}</h3>{selected.host_ids.length ? <ul>{selected.host_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul> : <div className="empty-state">{t("hosts.list.empty")}</div>}</Modal>}
    </section>
  );
}

function Installer({
  items,
  apmids,
  environments,
  credentials,
  patterns,
  groups,
  settings,
  canManage,
  canDiscover,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerEnrollmentToken[];
  apmids: HostsManagerApmid[];
  environments: HostsManagerEnvironment[];
  credentials: HostsManagerCredential[];
  patterns: HostsManagerHostnamePattern[];
  groups: HostsManagerGroup[];
  settings: HostsManagerSettings | null;
  canManage: boolean;
  canDiscover: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [tab, setTab] = useState<"discovery" | "wizard" | "script">("discovery");
  return <div className="hosts-installer">
    <div className="hosts-installer-actions">
      <button type="button" className={tab === "discovery" ? "active" : ""} onClick={() => setTab("discovery")}><Network /><span><strong>{t("hosts.installer.discovery")}</strong><small>{t("hosts.installer.discoveryHint")}</small></span></button>
      <button type="button" className={tab === "wizard" ? "active" : ""} onClick={() => setTab("wizard")}><Terminal /><span><strong>{t("hosts.installer.wizard")}</strong><small>{t("hosts.installer.wizardHint")}</small></span></button>
      <button type="button" className={tab === "script" ? "active" : ""} onClick={() => setTab("script")}><Download /><span><strong>{t("hosts.installer.script")}</strong><small>{t("hosts.installer.scriptHint")}</small></span></button>
    </div>
    {tab === "discovery" && <Discovery canManage={canDiscover} environments={environments} credentials={credentials} patterns={patterns} t={t} toast={toast} refresh={refresh} />}
    {tab === "wizard" && <OnboardingWizard canManage={canManage} apmids={apmids} environments={environments} credentials={credentials} patterns={patterns} settings={settings} t={t} toast={toast} />}
    {tab === "script" && <Enrollment items={items} apmids={apmids} environments={environments} patterns={patterns} groups={groups} settings={settings} canManage={canManage} t={t} toast={toast} refresh={refresh} />}
  </div>;
}

function OnboardingWizard({
  canManage,
  apmids,
  environments,
  credentials,
  patterns,
  settings,
  t,
  toast,
}: {
  canManage: boolean;
  apmids: HostsManagerApmid[];
  environments: HostsManagerEnvironment[];
  credentials: HostsManagerCredential[];
  patterns: HostsManagerHostnamePattern[];
  settings: HostsManagerSettings | null;
  t: Translate;
  toast: ToastFn;
}) {
  const [step, setStep] = useState(1);
  const [target, setTarget] = useState("");
  const [sshPort, setSshPort] = useState(settings?.ssh_default_port || 22);
  const [sshUser, setSshUser] = useState("root");
  const [credentialId, setCredentialId] = useState("");
  const [useSudo, setUseSudo] = useState(true);
  const [apmidId, setApmidId] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [patternId, setPatternId] = useState("");
  const [agentPort, setAgentPort] = useState(settings?.agent_default_port || 8443);
  const [reportInterval, setReportInterval] = useState(settings?.report_interval_seconds || 300);
  const [applyHostname, setApplyHostname] = useState(true);
  const [connectionResult, setConnectionResult] = useState<
    (Record<string, unknown> & {
      keys?: Array<{ fingerprint: string; key_type: string }>;
      accepted_key?: { fingerprint: string; key_type: string };
      requires_fingerprint_confirmation?: boolean;
      login_available?: boolean;
    }) | null
  >(null);
  const [acceptedFingerprint, setAcceptedFingerprint] = useState("");
  const [created, setCreated] = useState<{
    host: HostsManagerHost;
    log: string;
    status: string;
  } | null>(null);
  useEffect(() => {
    const activeApmids = apmids.filter((item) => item.active);
    if (!activeApmids.some((item) => item.id === apmidId)) setApmidId(activeApmids[0]?.id || "");
  }, [apmidId, apmids]);
  useEffect(() => {
    const activeEnvironments = environments.filter((item) => item.active);
    if (activeEnvironments.some((item) => item.id === environmentId)) return;
    const selected = activeEnvironments[0];
    setEnvironmentId(selected?.id || "");
    if (selected?.default_hostname_pattern_id) setPatternId(selected.default_hostname_pattern_id);
    if (selected) {
      setAgentPort(selected.default_agent_port);
      setReportInterval(selected.report_interval_seconds);
    }
  }, [environmentId, environments]);
  async function testConnection(fingerprint = "") {
    try {
      const result = await api.probeHostsManagerSshOnboarding({
        address: target,
        port: sshPort,
        ssh_user: sshUser,
        credential_id: credentialId,
        use_sudo: useSudo,
        accepted_fingerprint: fingerprint,
      });
      setConnectionResult(result);
      if (fingerprint) setAcceptedFingerprint(fingerprint);
      setStep(result.login_available ? 3 : 2);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
      setStep(1);
    }
  }
  async function prepareInstallation() {
    try {
      const item = await api.installHostsManagerAgentOverSsh({
        address: target,
        port: sshPort,
        ssh_user: sshUser,
        credential_id: credentialId,
        use_sudo: useSudo,
        accepted_fingerprint: acceptedFingerprint,
        apmid_id: apmidId,
        environment_id: environmentId,
        hostname_pattern_id: patternId || null,
        agent_port: agentPort,
        report_interval_seconds: reportInterval,
        apply_hostname: applyHostname,
        confirm: true,
      });
      setCreated(item);
      setStep(5);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  const labels = ["connection", "test", "configuration", "installation", "registration", "summary"];
  return <section className="ansible-panel hosts-onboarding-wizard">
    <header><div><h3>{t("hosts.installer.wizard")}</h3><p>{t("hosts.onboarding.hint")}</p></div></header>
    <ol className="hosts-wizard-steps">{labels.map((label, index) => <li key={label} className={step === index + 1 ? "active" : step > index + 1 ? "done" : ""}><span>{step > index + 1 ? <CheckCircle2 /> : index + 1}</span>{t(`hosts.onboarding.step.${label}`)}</li>)}</ol>
    <div className="hosts-wizard-body">
      {step === 1 && <div className="module-form-grid">
        <label>{t("hosts.onboarding.target")}<input required value={target} placeholder="192.168.1.10" onChange={(event) => setTarget(event.target.value)} /></label>
        <label>{t("hosts.host.port")}<input type="number" min={1} max={65535} value={sshPort} onChange={(event) => setSshPort(Number(event.target.value))} /></label>
        <label>{t("hosts.host.user")}<input value={sshUser} onChange={(event) => setSshUser(event.target.value)} /></label>
        <label>{t("hosts.environment.credential")}<select value={credentialId} onChange={(event) => setCredentialId(event.target.value)}><option value="">{t("common.none")}</option>{credentials.filter((item) => item.active && ["ssh_password", "ssh_private_key"].includes(item.type)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="check"><input type="checkbox" checked={useSudo} onChange={(event) => setUseSudo(event.target.checked)} />{t("hosts.onboarding.useSudo")}</label>
      </div>}
      {step === 2 && !connectionResult && <div className="hosts-connection-test"><Radio className="pulse" /><h4>{t("hosts.onboarding.testing")}</h4><p>{t("hosts.onboarding.testingHint")}</p></div>}
      {step === 2 && connectionResult?.requires_fingerprint_confirmation && <div className="hosts-fingerprint-confirm"><ShieldCheck /><h4>{t("hosts.onboarding.verifyFingerprint")}</h4><p>{t("hosts.onboarding.verifyFingerprintHint")}</p>{connectionResult.keys?.map((key) => <button type="button" key={key.fingerprint} onClick={() => { setConnectionResult(null); void testConnection(key.fingerprint); }}><span>{key.key_type}</span><code>{key.fingerprint}</code></button>)}</div>}
      {step === 2 && connectionResult && !connectionResult.requires_fingerprint_confirmation && !connectionResult.login_available && <div className="hosts-connection-test"><AlertTriangle /><h4>{t("hosts.onboarding.loginFailed")}</h4><p>{String(connectionResult.error || t("error.generic"))}</p><button type="button" onClick={() => { setConnectionResult(null); void testConnection(acceptedFingerprint); }}>{t("action.retry")}</button></div>}
      {step === 3 && <><div className="module-diagnostic"><CheckCircle2 /><strong>{t("hosts.onboarding.sshReachable")}</strong><span>{JSON.stringify(connectionResult)}</span></div><div className="module-form-grid">
        <label>{t("hosts.apmid.code")}<select required value={apmidId} onChange={(event) => setApmidId(event.target.value)}>{apmids.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.code}</option>)}</select></label>
        <label>{t("hosts.host.environment")}<select value={environmentId} onChange={(event) => {
          const id = event.target.value; setEnvironmentId(id);
          const environment = environments.find((item) => item.id === id);
          if (environment?.default_hostname_pattern_id) setPatternId(environment.default_hostname_pattern_id);
          if (environment) { setAgentPort(environment.default_agent_port); setReportInterval(environment.report_interval_seconds); }
        }}>{environments.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>{t("hosts.environment.pattern")}<select value={patternId} onChange={(event) => setPatternId(event.target.value)}><option value="">{t("hosts.enrollment.legacyPattern")}</option>{patterns.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.next_hostname}</option>)}</select></label>
        <label>{t("hosts.agent.port")}<input type="number" min={1} max={65535} value={agentPort} onChange={(event) => setAgentPort(Number(event.target.value))} /></label>
        <label>{t("hosts.agent.reportInterval")}<input type="number" min={30} value={reportInterval} onChange={(event) => setReportInterval(Number(event.target.value))} /></label>
        <label className="check"><input type="checkbox" checked={applyHostname} onChange={(event) => setApplyHostname(event.target.checked)} />{t("hosts.enrollment.applyHostname")}</label>
      </div></>}
      {step === 4 && <div className="hosts-install-plan"><Terminal /><h4>{t("hosts.onboarding.installationPlan")}</h4><ol><li>{t("hosts.onboarding.backupConfig")}</li><li>{t("hosts.onboarding.changeHostname")}</li><li>{t("hosts.onboarding.installAgent")}</li><li>{t("hosts.onboarding.enableService")}</li><li>{t("hosts.onboarding.testCommunication")}</li></ol><p>{t("hosts.onboarding.safeExecutionHint")}</p></div>}
      {step === 5 && <div className="hosts-registration-ready"><CheckCircle2 /><h4>{t("hosts.onboarding.registrationReady")}</h4><code>{created?.host.hostname || created?.host.name || patterns.find((item) => item.id === patternId)?.next_hostname}</code><pre>{created?.log}</pre><p>{t("hosts.onboarding.installLogHint")}</p></div>}
      {step === 6 && <div className="hosts-registration-ready"><CheckCircle2 /><h4>{t("hosts.onboarding.summary")}</h4><dl className="hosts-definition-grid"><dt>{t("hosts.host.hostname")}</dt><dd>{created?.host.hostname || created?.host.name}</dd><dt>{t("hosts.host.address")}</dt><dd>{target}</dd><dt>{t("hosts.host.environment")}</dt><dd>{environments.find((item) => item.id === environmentId)?.name || t("common.none")}</dd><dt>{t("hosts.host.agentState")}</dt><dd><Status value={created?.host.agent_status || "pending"} t={t} /></dd><dt>{t("hosts.onboarding.communicationResult")}</dt><dd><Status value={created?.status || "completed"} t={t} /></dd></dl></div>}
    </div>
    <footer className="hosts-wizard-footer">
      <button type="button" disabled={step <= 1} onClick={() => setStep((value) => Math.max(1, value - 1))}>{t("action.previous")}</button>
      {step === 1 && <button className="button-primary" type="button" disabled={!canManage || !target || !sshUser || !credentialId} onClick={() => { setConnectionResult(null); setStep(2); void testConnection(); }}>{t("hosts.onboarding.testConnection")}</button>}
      {step === 3 && <button className="button-primary" type="button" disabled={!canManage || !apmidId || !environmentId} onClick={() => setStep(4)}>{t("action.next")}</button>}
      {step === 4 && <button className="button-primary" type="button" disabled={!canManage || !apmidId || !environmentId} onClick={() => void prepareInstallation()}>{t("hosts.onboarding.prepareInstall")}</button>}
      {step === 5 && <button className="button-primary" type="button" onClick={() => setStep(6)}>{t("action.next")}</button>}
    </footer>
  </section>;
}

function Enrollment({
  items,
  apmids,
  environments,
  patterns,
  groups,
  settings,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerEnrollmentToken[];
  apmids: HostsManagerApmid[];
  environments: HostsManagerEnvironment[];
  patterns: HostsManagerHostnamePattern[];
  groups: HostsManagerGroup[];
  settings: HostsManagerSettings | null;
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [minutes, setMinutes] = useState(15);
  const [mode, setMode] = useState<"one_time" | "permanent">("one_time");
  const [apmidId, setApmidId] = useState("");
  const [patternId, setPatternId] = useState("");
  const [boundAddress, setBoundAddress] = useState("");
  const [agentPort, setAgentPort] = useState(8443);
  const [reportInterval, setReportInterval] = useState(300);
  const [bootstrapOS, setBootstrapOS] = useState<"linux" | "windows">("linux");
  const [applyHostname, setApplyHostname] = useState(true);
  const [environmentId, setEnvironmentId] = useState("");
  const [location, setLocation] = useState("");
  const [tags, setTags] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [requireApproval, setRequireApproval] = useState(true);
  const [filter, setFilter] = useState("");
  const [created, setCreated] = useState<HostsManagerEnrollmentToken | null>(
    null,
  );
  useEffect(() => {
    if (settings) {
      setBootstrapOS(settings.bootstrap_default_os);
      setApplyHostname(settings.bootstrap_apply_hostname);
      setMinutes(settings.token_ttl_minutes || 15);
      if (!environmentId) {
        setAgentPort(settings.agent_default_port || 8443);
        setReportInterval(settings.report_interval_seconds || 300);
      }
    }
  }, [environmentId, settings]);
  useEffect(() => {
    const activeApmids = apmids.filter((item) => item.active);
    if (!activeApmids.some((item) => item.id === apmidId)) setApmidId(activeApmids[0]?.id || "");
  }, [apmidId, apmids]);
  useEffect(() => {
    const activeEnvironments = environments.filter((item) => item.active);
    if (activeEnvironments.some((item) => item.id === environmentId)) return;
    const selected = activeEnvironments[0];
    setEnvironmentId(selected?.id || "");
    setPatternId(selected?.default_hostname_pattern_id || settings?.default_hostname_pattern_id || "");
    if (selected) {
      setAgentPort(selected.default_agent_port);
      setReportInterval(selected.report_interval_seconds);
    }
  }, [environmentId, environments, settings?.default_hostname_pattern_id]);
  const visible = items.filter(
    (item) =>
      !filter ||
      (filter === "active"
        ? !item.used && !item.expired && !item.revoked
        : filter === "used"
          ? item.used
          : filter === "expired"
            ? item.expired
            : item.revoked),
  );
  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!apmidId || !environmentId) {
      toast(t(!apmidId ? "hosts.enrollment.noActiveApmid" : "hosts.enrollment.noActiveEnvironment"), "error");
      return;
    }
    try {
      const item = await api.createHostsManagerEnrollmentToken({
        bootstrap_os: bootstrapOS,
        apply_hostname: applyHostname,
        expires_minutes: mode === "one_time" ? minutes : null,
        mode,
        apmid_id: apmidId,
        environment_id: environmentId,
        hostname_pattern_id: patternId || null,
        bound_address: boundAddress,
        agent_port: agentPort,
        report_interval_seconds: reportInterval,
        location,
        tags: tags
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        group_ids: groupIds,
        require_approval: requireApproval,
        onboard_ansible: false,
      });
      setCreated(item);
      setOpen(false);
      await refresh();
    } catch (error) {
      toast(hostsManagerError(error, t), "error");
    }
  }
  async function copy(value: string) {
    await navigator.clipboard.writeText(value);
    toast(t("hosts.enrollment.copied"), "ok");
  }
  async function download() {
    if (!created?.script_url || !created.token) return;
    try {
      const blob = await api.downloadHostsManagerEnrollmentScript(
        created.script_url,
        created.token,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download =
        created.filename ||
        `webnas-enroll.${created.bootstrap_os === "windows" ? "ps1" : "sh"}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  const columns: HostsDataColumn<HostsManagerEnrollmentToken>[] = [
    {
      id: "mode",
      label: t("hosts.enrollment.mode"),
      sortValue: (item) => item.mode || "one_time",
      cell: (item) => t(`hosts.enrollment.mode.${item.mode || "one_time"}`),
    },
    {
      id: "apmid",
      label: t("hosts.apmid.code"),
      sortValue: (item) => item.apmid_code || "",
      cell: (item) => item.apmid_code || t("hosts.enrollment.legacyToken"),
    },
    {
      id: "environment",
      label: t("hosts.host.environment"),
      sortValue: (item) => item.environment_name || "",
      cell: (item) => item.environment_name || t("hosts.enrollment.legacyToken"),
    },
    {
      id: "managed-group",
      label: t("hosts.enrollment.managedGroup"),
      sortValue: (item) => item.managed_group_name || "",
      cell: (item) => item.managed_group_name || t("hosts.enrollment.legacyToken"),
    },
    {
      id: "hostname",
      label: t("hosts.enrollment.assignedHostname"),
      sortValue: (item) => item.assigned_hostname || item.hostname_pattern,
      cell: (item) => item.assigned_hostname || item.hostname_pattern,
    },
    {
      id: "os",
      label: t("hosts.enrollment.os"),
      sortValue: (item) => item.bootstrap_os,
      cell: (item) => t(`hosts.enrollment.os.${item.bootstrap_os || "linux"}`),
    },
    {
      id: "creator",
      label: t("hosts.enrollment.creator"),
      sortValue: (item) => item.created_by || "",
      cell: (item) => item.created_by || t("common.none"),
    },
    {
      id: "created",
      label: t("hosts.enrollment.created"),
      sortValue: (item) => item.created_at || 0,
      cell: (item) =>
        item.created_at
          ? new Date(item.created_at * 1000).toLocaleString()
          : t("common.none"),
    },
    {
      id: "expires",
      label: t("hosts.enrollment.expires"),
      sortValue: (item) => item.expires_at,
      cell: (item) => item.expires_at ? new Date(item.expires_at * 1000).toLocaleString() : t("hosts.enrollment.never"),
    },
    {
      id: "status",
      label: t("common.status"),
      cell: (item) => (
        <Status
          value={
            item.used
              ? "used"
              : item.expired
                ? "expired"
                : item.revoked
                  ? "revoked"
                  : "active"
          }
          t={t}
        />
      ),
    },
    {
      id: "reported",
      label: t("hosts.enrollment.usedHostname"),
      cell: (item) => item.used_hostname || t("common.none"),
    },
    {
      id: "actions",
      label: t("column.actions"),
      cell: (item) =>
        canManage && !item.used && !item.expired && !item.revoked ? (
          <button
            onClick={() =>
              void api.revokeHostsManagerEnrollmentToken(item.id).then(refresh)
            }
          >
            <X />
            {t("hosts.enrollment.revoke")}
          </button>
        ) : null,
    },
  ];
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.enrollment.title")}</h3>
          <p>{t("hosts.enrollment.hint")}</p>
        </div>
        {canManage && (
          <button
            className="button-primary"
            disabled={!apmids.some((item) => item.active) || !environments.some((item) => item.active)}
            onClick={() => setOpen(true)}
          >
            <Plus />
            {t("hosts.enrollment.generate")}
          </button>
        )}
      </header>
      {!apmids.some((item) => item.active) && <div className="module-diagnostic warning"><AlertTriangle /><strong>{t("hosts.enrollment.noActiveApmid")}</strong></div>}
      {!environments.some((item) => item.active) && <div className="module-diagnostic warning"><AlertTriangle /><strong>{t("hosts.enrollment.noActiveEnvironment")}</strong></div>}
      <div className="module-section-toolbar">
        <label>
          <Filter />
          <select
            aria-label={t("hosts.enrollment.statusFilter")}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="">{t("hosts.filter.all")}</option>
            <option value="active">{t("hosts.status.active")}</option>
            <option value="used">{t("hosts.status.used")}</option>
            <option value="expired">{t("hosts.status.expired")}</option>
            <option value="revoked">{t("hosts.status.revoked")}</option>
          </select>
        </label>
      </div>
      <HostsDataTable
        items={visible}
        columns={columns}
        rowKey={(item) => item.id}
        empty={t("hosts.records.empty")}
      />
      {open && (
        <Modal
          wide
          title={t("hosts.enrollment.generate")}
          closeLabel={t("action.close")}
          onClose={() => setOpen(false)}
          footer={
            <button
              className="button-primary"
              type="submit"
              form="enrollment-form"
              disabled={!apmidId || !environmentId}
            >
              {t("hosts.enrollment.generate")}
            </button>
          }
        >
          <form
            id="enrollment-form"
            className="module-form-grid"
            onSubmit={create}
          >
            <fieldset className="hosts-enrollment-section wide">
              <legend>{t("hosts.enrollment.basic")}</legend>
              <div className="module-form-grid">
            <div className="wide hosts-enrollment-hostname">
              <strong>{t("hosts.enrollment.assignedHostname")}</strong>
              <code>{patterns.find((item) => item.id === patternId)?.next_hostname || settings?.next_hostname || "…"}</code>
              <small>{t("hosts.settings.reservationHint")}</small>
            </div>
            <label>
              {t("hosts.enrollment.mode")}
              <select value={mode} onChange={(event) => setMode(event.target.value as "one_time" | "permanent")}>
                <option value="one_time">{t("hosts.enrollment.mode.one_time")}</option>
                <option value="permanent">{t("hosts.enrollment.mode.permanent")}</option>
              </select>
            </label>
            <label>
              {t("hosts.environment.pattern")}
              <select value={patternId} onChange={(event) => setPatternId(event.target.value)}>
                <option value="">{t("hosts.enrollment.legacyPattern")}</option>
                {patterns.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.next_hostname}</option>)}
              </select>
            </label>
            <label>
              {t("hosts.enrollment.os")}
              <select
                value={bootstrapOS}
                onChange={(event) =>
                  setBootstrapOS(event.target.value as "linux" | "windows")
                }
              >
                <option value="linux">{t("hosts.enrollment.os.linux")}</option>
                <option value="windows">
                  {t("hosts.enrollment.os.windows")}
                </option>
              </select>
            </label>
            {mode === "one_time" && <label>
              {t("hosts.enrollment.minutes")}
              <input
                required
                type="number"
                min="1"
                max="525600"
                value={minutes}
                onChange={(event) => setMinutes(Number(event.target.value))}
              />
            </label>}
            <label>
              {t("hosts.host.environment")}
              <select required value={environmentId} onChange={(event) => {
                const id = event.target.value;
                setEnvironmentId(id);
                const selected = environments.find((item) => item.id === id);
                setPatternId(selected?.default_hostname_pattern_id || settings?.default_hostname_pattern_id || "");
                if (selected) {
                  setAgentPort(selected.default_agent_port);
                  setReportInterval(selected.report_interval_seconds);
                }
              }}>
                {environments.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>
              {t("hosts.apmid.code")}
              <select required value={apmidId} onChange={(event) => setApmidId(event.target.value)}>
                {apmids.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.code}</option>)}
              </select>
            </label>
            <label>
              {t("hosts.host.location")}
              <input
                value={location}
                onChange={(event) => setLocation(event.target.value)}
              />
            </label>
            <label className="wide">
              {t("hosts.host.tags")}
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={applyHostname}
                onChange={(event) => setApplyHostname(event.target.checked)}
              />
              {t("hosts.enrollment.applyHostname")}
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={requireApproval}
                onChange={(event) => setRequireApproval(event.target.checked)}
              />
              {t("hosts.enrollment.requireApproval")}
            </label>
              </div>
            </fieldset>
            <fieldset className="hosts-enrollment-section wide">
              <legend>{t("hosts.enrollment.advanced")}</legend>
              <div className="module-form-grid">
            <label>
              {t("hosts.agent.port")}
              <input type="number" min={1} max={65535} value={agentPort} onChange={(event) => setAgentPort(Number(event.target.value))} />
            </label>
            <label>
              {t("hosts.agent.reportInterval")}
              <input type="number" min={30} max={86400} value={reportInterval} onChange={(event) => setReportInterval(Number(event.target.value))} />
            </label>
            <label>
              {t("hosts.enrollment.boundAddress")}
              <input value={boundAddress} placeholder="192.168.1.10" onChange={(event) => setBoundAddress(event.target.value)} />
            </label>
            <fieldset className="wide hosts-enrollment-groups">
              <legend>{t("hosts.enrollment.additionalGroups")}</legend>
              {groups.filter((group) => !group.managed).length ? groups.filter((group) => !group.managed).map((group) => (
                <label className="check" key={group.id}>
                  <input
                    type="checkbox"
                    checked={groupIds.includes(group.id)}
                    onChange={(event) =>
                      setGroupIds((current) =>
                        event.target.checked
                          ? [...current, group.id]
                          : current.filter((id) => id !== group.id),
                      )
                    }
                  />
                  {group.name}
                </label>
              )) : <small>{t("hosts.enrollment.noAdditionalGroups")}</small>}
            </fieldset>
              </div>
            </fieldset>
          </form>
        </Modal>
      )}
      {created?.command && (
        <Modal
          title={t("hosts.enrollment.ready")}
          closeLabel={t("action.close")}
          onClose={() => setCreated(null)}
          footer={
            <>
              <button onClick={() => void copy(created.command || "")}>
                <Copy />
                {t("hosts.enrollment.copy")}
              </button>
              <button onClick={() => void download()}>
                <Download />
                {t("hosts.enrollment.download")}
              </button>
            </>
          }
        >
          <p>
            <strong>{created.assigned_hostname}</strong>
          </p>
          <dl className="hosts-definition-grid">
            <dt>{t("hosts.apmid.code")}</dt><dd>{created.apmid_code}</dd>
            <dt>{t("hosts.host.environment")}</dt><dd>{created.environment_name}</dd>
            <dt>{t("hosts.enrollment.managedGroup")}</dt><dd><code>{created.managed_group_name}</code></dd>
          </dl>
          <p>{t(created.mode === "permanent" ? "hosts.enrollment.permanentHint" : "hosts.enrollment.onceHint")}</p>
          {created.bootstrap_os === "windows" && created.apply_hostname && (
            <p>{t("hosts.enrollment.windowsRestart")}</p>
          )}
          <pre>{created.command}</pre>
        </Modal>
      )}
    </section>
  );
}

function Operations({
  items,
  initialOperationId,
  t,
  toast,
  onDeepLinkClose,
}: {
  items: HostsManagerOperation[];
  initialOperationId?: string;
  t: Translate;
  toast?: ToastFn;
  onDeepLinkClose?: () => void;
}) {
  const [selected, setSelected] = useState<HostsManagerOperation | null>(null);
  useEffect(() => {
    if (!initialOperationId) return;
    void api.hostsManagerOperation(initialOperationId).then(setSelected).catch((error: unknown) => {
      toast?.(error instanceof Error ? error.message : t("error.generic"), "error");
      onDeepLinkClose?.();
    });
  }, [initialOperationId, onDeepLinkClose, t, toast]);
  const columns: HostsDataColumn<HostsManagerOperation>[] = [
    {
      id: "host",
      label: t("hosts.operation.host"),
      sortValue: (item) => item.host_id || "",
      cell: (item) => item.host_id?.slice(0, 12) || t("common.none"),
    },
    {
      id: "action",
      label: t("hosts.operation.action"),
      sortValue: (item) => item.capability_id,
      cell: (item) => item.capability_id,
    },
    {
      id: "module",
      label: t("hosts.operation.module"),
      sortValue: (item) => item.module_id,
      cell: (item) => item.module_id,
    },
    {
      id: "status",
      label: t("common.status"),
      sortValue: (item) => item.status,
      cell: (item) => <Status value={item.status} t={t} />,
    },
    {
      id: "progress",
      label: t("hosts.operation.progress"),
      sortValue: (item) => item.progress,
      cell: (item) => `${item.progress}%`,
    },
    {
      id: "created",
      label: t("hosts.operation.started"),
      sortValue: (item) => item.created_at,
      cell: (item) => new Date(item.created_at * 1000).toLocaleString(),
    },
    {
      id: "updated",
      label: t("hosts.operation.updated"),
      sortValue: (item) => item.updated_at,
      cell: (item) => new Date(item.updated_at * 1000).toLocaleString(),
    },
    {
      id: "details",
      label: t("hosts.operation.details"),
      cell: (item) => item.error || item.stage || t("common.none"),
    },
  ];
  return (
    <>
      <HostsDataTable
        items={items}
        columns={columns}
        rowKey={(item) => item.id}
        empty={t("hosts.operations.empty")}
        selectedKey={selected?.id}
        onSelect={(item) => { if (initialOperationId && item.id !== initialOperationId) onDeepLinkClose?.(); setSelected(item); }}
      />
      {selected && <Modal wide title={t("actions.hostsOperationDetails")} closeLabel={t("action.close")} onClose={() => { setSelected(null); if (selected.id === initialOperationId) onDeepLinkClose?.(); }}>
        <dl className="settings-details">
          <dt>{t("hosts.operation.action")}</dt><dd>{selected.capability_id}</dd>
          <dt>{t("common.status")}</dt><dd><Status value={selected.status} t={t} /></dd>
          <dt>{t("hosts.operation.progress")}</dt><dd>{selected.progress}%</dd>
          <dt>{t("hosts.operation.details")}</dt><dd>{selected.stage || t("common.none")}</dd>
        </dl>
        {selected.error && <pre className="error-log">{selected.error}</pre>}
        <pre>{JSON.stringify(selected.details, null, 2)}</pre>
      </Modal>}
    </>
  );
}
function Discovery({
  canManage,
  environments,
  credentials,
  patterns,
  t,
  toast,
  refresh,
}: {
  canManage: boolean;
  environments: HostsManagerEnvironment[];
  credentials: HostsManagerCredential[];
  patterns: HostsManagerHostnamePattern[];
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  type ScanHost = { id: string; address: string; hostname: string; port: number; latency_ms: number; ssh_status: string };
  const [target, setTarget] = useState("192.168.1.0/24");
  const [port, setPort] = useState(22);
  const [timeout, setTimeout] = useState(2);
  const [credentialId, setCredentialId] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [patternId, setPatternId] = useState("");
  const [result, setResult] = useState<{ id: string; status: string; results: ScanHost[]; discovered: number } | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  async function scan(event: React.FormEvent) {
    event.preventDefault();
    try {
      const range = target.includes("-") ? target.split("-", 2).map((item) => item.trim()) : null;
      setResult(await api.startHostsManagerScan({
          cidr: target.includes("/") ? target : null,
          start_address: range?.[0] || (!target.includes("/") ? target : null),
          end_address: range?.[1] || (!target.includes("/") ? target : null),
          port,
          timeout_seconds: timeout,
          concurrency: 32,
          reverse_dns: true,
        }) as { id: string; status: string; results: ScanHost[]; discovered: number });
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  async function addHost(item: ScanHost) {
    try {
      await api.saveHostsManagerHost({
        name: item.hostname || item.address.replace(/:/g, "-"),
        hostname: item.hostname,
        fqdn: "",
        address: item.address,
        management_address: "",
        port: item.port,
        connection_type: "ssh",
        ssh_user: credentials.find((credential) => credential.id === credentialId)?.username || "root",
        credential_id: credentialId || null,
        python_interpreter: "auto_silent",
        environment: environmentId,
        location: "",
        description: "",
        tags: ["discovered"],
        variables: { hostname_pattern_id: patternId || undefined },
        group_ids: [],
        active: true,
        approved: false,
        power_profile_id: null,
      });
      toast(t("hosts.discovery.hostAdded"), "ok");
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }
  async function addSelected() {
    for (const item of result?.results || []) {
      if (selectedIds.includes(item.id)) await addHost(item);
    }
    setSelectedIds([]);
  }
  const columns: HostsDataColumn<ScanHost>[] = [
    { id: "select", label: "", cell: (item) => <input type="checkbox" checked={selectedIds.includes(item.id)} aria-label={t("hosts.discovery.select").replace("{address}", item.address)} onClick={(event) => event.stopPropagation()} onChange={() => setSelectedIds((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])} /> },
    { id: "address", label: t("hosts.host.address"), sortValue: (item) => item.address, cell: (item) => item.address },
    { id: "port", label: t("hosts.host.port"), sortValue: (item) => item.port, cell: (item) => item.port },
    { id: "status", label: t("common.status"), sortValue: (item) => item.ssh_status, cell: (item) => <Status value={item.ssh_status} t={t} /> },
    { id: "hostname", label: t("hosts.host.hostname"), sortValue: (item) => item.hostname, cell: (item) => item.hostname || t("common.none") },
    { id: "login", label: t("hosts.discovery.login"), cell: () => t(credentialId ? "hosts.discovery.readyToTest" : "hosts.discovery.notTested") },
    { id: "agent", label: t("hosts.host.agentState"), cell: () => t("hosts.discovery.unknown") },
    { id: "environment", label: t("hosts.host.environment"), cell: () => environments.find((item) => item.id === environmentId)?.name || t("common.none") },
    { id: "actions", label: t("column.actions"), cell: (item) => <button type="button" onClick={() => void addHost(item)}>{t("hosts.discovery.addHost")}</button> },
  ];
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("module.section.discovery")}</h3>
          <p>{t("hosts.discovery.hint")}</p>
        </div>
      </header>
      <form className="hosts-discovery-form" onSubmit={scan}>
        <label>
          {t("hosts.discovery.target")}
          <input
            value={target}
            placeholder="192.168.1.10, 192.168.1.10-192.168.1.100, 192.168.1.0/24"
            onChange={(event) => setTarget(event.target.value)}
            disabled={!canManage}
          />
        </label>
        <label>{t("hosts.host.port")}<input type="number" min={1} max={65535} value={port} onChange={(event) => setPort(Number(event.target.value))} /></label>
        <label>{t("hosts.discovery.timeout")}<input type="number" min={0.2} max={15} step={0.2} value={timeout} onChange={(event) => setTimeout(Number(event.target.value))} /></label>
        <label>{t("hosts.environment.credential")}<select value={credentialId} onChange={(event) => setCredentialId(event.target.value)}><option value="">{t("common.none")}</option>{credentials.filter((item) => item.active && ["ssh_password", "ssh_private_key"].includes(item.type)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>{t("hosts.host.environment")}<select value={environmentId} onChange={(event) => {
          const id = event.target.value; setEnvironmentId(id);
          const environment = environments.find((item) => item.id === id);
          if (environment?.default_credential_id) setCredentialId(environment.default_credential_id);
          if (environment?.default_hostname_pattern_id) setPatternId(environment.default_hostname_pattern_id);
        }}><option value="">{t("common.none")}</option>{environments.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>{t("hosts.environment.pattern")}<select value={patternId} onChange={(event) => setPatternId(event.target.value)}><option value="">{t("common.none")}</option>{patterns.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <button className="button-primary" disabled={!canManage}>
          {t("hosts.discovery.scan")}
        </button>
      </form>
      <p className="hosts-security-note"><ShieldCheck />{t("hosts.discovery.privateOnly")}</p>
      {result && <><div className="module-section-toolbar"><strong>{t("hosts.discovery.found").replace("{count}", String(result.discovered))}</strong>{selectedIds.length > 0 && <button className="button-primary" type="button" onClick={() => void addSelected()}>{t("hosts.discovery.addSelected")} ({selectedIds.length})</button>}</div><HostsDataTable items={result.results} columns={columns} rowKey={(item) => item.id} empty={t("hosts.discovery.empty")} /></>}
    </section>
  );
}
function Inventory({
  canManage,
  t,
  toast,
  refresh,
}: {
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [content, setContent] = useState("all:\n  hosts: {}\n");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  async function validate() {
    try {
      setPreview(await api.validateHostsManagerInventory(content));
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  async function importData() {
    try {
      await api.importHostsManagerInventory(content);
      toast(t("hosts.inventory.imported"), "ok");
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("module.section.inventory")}</h3>
          <p>{t("hosts.inventory.hint")}</p>
        </div>
        <a
          className="button"
          href="/api/modules/hosts-manager/inventory/export"
        >
          {t("hosts.inventory.export")}
        </a>
      </header>
      <textarea
        className="ansible-editor"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        readOnly={!canManage}
      />
      <div className="module-section-toolbar">
        <button disabled={!canManage} onClick={() => void validate()}>
          {t("hosts.inventory.validate")}
        </button>
        <button
          className="button-primary"
          disabled={!canManage || !preview}
          onClick={() => void importData()}
        >
          {t("hosts.inventory.import")}
        </button>
      </div>
      {preview && <pre>{JSON.stringify(preview, null, 2)}</pre>}
    </section>
  );
}
function Credentials({
  items,
  environments,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerCredential[];
  environments: HostsManagerEnvironment[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<HostsManagerCredential | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<
    "ssh_password" | "ssh_private_key" | "become_password"
  >("ssh_password");
  const [username, setUsername] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [description, setDescription] = useState("");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");

  function showEditor(item?: HostsManagerCredential) {
    setEditing(item || null);
    setName(item?.name || "");
    setType(
      item?.type === "ssh_private_key" || item?.type === "become_password"
        ? item.type
        : "ssh_password",
    );
    setUsername(item?.username || "");
    setEnvironmentId(item?.environment_id || "");
    setDescription(item?.description || "");
    setSecret("");
    setPassphrase("");
    setOpen(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerCredential(
        {
          name,
          type,
          username,
          environment_id: environmentId || null,
          secret,
          passphrase,
          description,
          active: true,
          confirm: true,
        },
        editing?.id,
      );
      setSecret("");
      setOpen(false);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }

  async function remove(item: HostsManagerCredential) {
    if (!window.confirm(t("hosts.credentials.deleteConfirm"))) return;
    try {
      await api.deleteHostsManagerCredential(item.id);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }

  const environmentNames = new Map(
    environments.map((item) => [item.id, item.name]),
  );
  const columns: HostsDataColumn<HostsManagerCredential>[] = [
    {
      id: "name",
      label: t("common.name"),
      sortValue: (item) => item.name,
      cell: (item) => <strong>{item.name}</strong>,
    },
    {
      id: "type",
      label: t("hosts.credentials.type"),
      sortValue: (item) => item.type,
      cell: (item) => t(`hosts.credentials.type.${item.type}`),
    },
    {
      id: "username",
      label: t("hosts.host.user"),
      sortValue: (item) => item.username,
      cell: (item) => item.username || t("common.none"),
    },
    {
      id: "environment",
      label: t("hosts.environment.title"),
      sortValue: (item) => environmentNames.get(item.environment_id || "") || "",
      cell: (item) =>
        environmentNames.get(item.environment_id || "") ||
        t("hosts.environment.all"),
    },
    {
      id: "hosts",
      label: t("hosts.credentials.hostCount"),
      sortValue: (item) => item.host_count || 0,
      cell: (item) => item.host_count || 0,
    },
    {
      id: "created",
      label: t("hosts.credentials.createdAt"),
      sortValue: (item) => item.created_at || 0,
      cell: (item) => new Date(item.created_at * 1000).toLocaleString(),
    },
    {
      id: "lastUsed",
      label: t("hosts.credentials.lastUsed"),
      sortValue: (item) => item.last_used_at || 0,
      cell: (item) =>
        item.last_used_at
          ? new Date(item.last_used_at * 1000).toLocaleString()
          : t("common.none"),
    },
    {
      id: "actions",
      label: t("common.actions"),
      cell: (item) =>
        canManage ? (
          <div className="hosts-table-actions">
            <button type="button" onClick={() => showEditor(item)}>
              {t("action.edit")}
            </button>
            <button
              className="button-danger"
              type="button"
              onClick={() => void remove(item)}
            >
              {t("action.delete")}
            </button>
          </div>
        ) : null,
    },
  ];

  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.credentials.title")}</h3>
          <p>{t("hosts.credentials.hint")}</p>
        </div>
        {canManage && (
          <button onClick={() => showEditor()}>
            <Plus />
            {t("hosts.credentials.add")}
          </button>
        )}
      </header>
      <HostsDataTable
        items={items}
        columns={columns}
        rowKey={(item) => item.id}
        empty={t("hosts.credentials.empty")}
      />
      {open && (
        <Modal
          title={
            editing
              ? t("hosts.credentials.edit")
              : t("hosts.credentials.add")
          }
          closeLabel={t("action.close")}
          onClose={() => setOpen(false)}
          footer={
            <button
              className="button-primary"
              type="submit"
              form="credential-form"
            >
              {t("action.save")}
            </button>
          }
        >
          <form
            id="credential-form"
            className="module-form-grid"
            onSubmit={save}
          >
            <label>
              {t("common.name")}
              <input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.credentials.type")}
              <select
                value={type}
                onChange={(event) =>
                  setType(
                    event.target.value as
                      | "ssh_password"
                      | "ssh_private_key"
                      | "become_password",
                  )
                }
              >
                <option value="ssh_password">
                  {t("hosts.credentials.type.ssh_password")}
                </option>
                <option value="ssh_private_key">
                  {t("hosts.credentials.type.ssh_private_key")}
                </option>
                <option value="become_password">
                  {t("hosts.credentials.type.become_password")}
                </option>
              </select>
            </label>
            <label>
              {t("hosts.host.user")}
              <input
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.environment.title")}
              <select
                value={environmentId}
                onChange={(event) => setEnvironmentId(event.target.value)}
              >
                <option value="">{t("hosts.environment.all")}</option>
                {environments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="module-form-span">
              {t("common.description")}
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.credentials.secret")}
              <input
                type="password"
                required
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
                autoComplete="new-password"
              />
            </label>
            {type === "ssh_private_key" && (
              <label>
                {t("hosts.credentials.passphrase")}
                <input
                  type="password"
                  value={passphrase}
                  onChange={(event) => setPassphrase(event.target.value)}
                  autoComplete="new-password"
                />
              </label>
            )}
          </form>
        </Modal>
      )}
    </section>
  );
}
function Repositories({
  items,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerRepository[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerRepository({
        name,
        description: "",
        url,
        revision: "main",
        credential_id: null,
        host_ids: [],
        group_ids: [],
        sync_before_use: true,
        active: true,
      });
      setOpen(false);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.repositories.title")}</h3>
          <p>{t("hosts.repositories.hint")}</p>
        </div>
        {canManage && (
          <button onClick={() => setOpen(true)}>
            <Plus />
            {t("hosts.repositories.add")}
          </button>
        )}
      </header>
      <div className="card-grid">
        {items.map((item) => (
          <article className="data-card" key={item.id}>
            <header>
              <strong>{item.name}</strong>
            </header>
            <p>{item.url}</p>
            <small>{item.last_commit || t("common.none")}</small>
            {canManage && (
              <button
                onClick={() =>
                  void api.syncHostsManagerRepository(item.id).then(refresh)
                }
              >
                {t("hosts.repositories.sync")}
              </button>
            )}
          </article>
        ))}
      </div>
      {open && (
        <Modal
          title={t("hosts.repositories.add")}
          closeLabel={t("action.close")}
          onClose={() => setOpen(false)}
          footer={
            <button
              className="button-primary"
              type="submit"
              form="repository-form"
            >
              {t("action.save")}
            </button>
          }
        >
          <form
            id="repository-form"
            className="module-form-grid"
            onSubmit={save}
          >
            <label>
              {t("common.name")}
              <input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.repositories.url")}
              <input
                type="url"
                required
                value={url}
                onChange={(event) => setUrl(event.target.value)}
              />
            </label>
          </form>
        </Modal>
      )}
    </section>
  );
}
function PowerProfiles({
  items,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerPowerProfile[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [mac, setMac] = useState("");
  const [broadcast, setBroadcast] = useState("");
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerPowerProfile({
        name,
        provider: "wol",
        credential_id: null,
        address: "",
        mac_address: mac,
        broadcast_address: broadcast,
        node: "",
        resource_id: null,
        verify_tls: true,
        ca_certificate: "",
        active: true,
      });
      setOpen(false);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.power.title")}</h3>
          <p>{t("hosts.power.hint")}</p>
        </div>
        {canManage && (
          <button onClick={() => setOpen(true)}>
            <Plus />
            {t("hosts.power.add")}
          </button>
        )}
      </header>
      <Records items={items} t={t} />
      {open && (
        <Modal
          title={t("hosts.power.add")}
          closeLabel={t("action.close")}
          onClose={() => setOpen(false)}
          footer={
            <button className="button-primary" type="submit" form="power-form">
              {t("action.save")}
            </button>
          }
        >
          <form id="power-form" className="module-form-grid" onSubmit={save}>
            <label>
              {t("common.name")}
              <input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.power.mac")}
              <input
                required
                value={mac}
                onChange={(event) => setMac(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.power.broadcast")}
              <input
                required
                value={broadcast}
                onChange={(event) => setBroadcast(event.target.value)}
              />
            </label>
          </form>
        </Modal>
      )}
    </section>
  );
}
function Backups({
  items,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerBackup[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  async function create() {
    try {
      await api.createHostsManagerBackup(t("hosts.backups.manual"));
      toast(t("hosts.backups.created"), "ok");
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.backups.title")}</h3>
          <p>{t("hosts.backups.hint")}</p>
        </div>
        {canManage && (
          <button onClick={() => void create()}>
            <Plus />
            {t("hosts.backups.create")}
          </button>
        )}
      </header>
      <Records items={items} t={t} />
    </section>
  );
}
type SettingsView =
  | "general"
  | "hostname"
  | "groups"
  | "inventory"
  | "repositories"
  | "power"
  | "maintenance";

function SettingsWorkspace({
  value,
  patterns,
  groups,
  repositories,
  powerProfiles,
  diagnostics,
  backups,
  canManageInventory,
  canManageRepositories,
  canManageBackup,
  canManageHosts,
  canManage,
  t,
  toast,
  onChange,
  refresh,
}: {
  value: HostsManagerSettings | null;
  patterns: HostsManagerHostnamePattern[];
  groups: HostsManagerGroup[];
  repositories: HostsManagerRepository[];
  powerProfiles: HostsManagerPowerProfile[];
  diagnostics: Array<{ id: string; status: string; message: string }>;
  backups: HostsManagerBackup[];
  canManageInventory: boolean;
  canManageRepositories: boolean;
  canManageBackup: boolean;
  canManageHosts: boolean;
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  onChange: (value: HostsManagerSettings) => void;
  refresh: () => Promise<void>;
}) {
  const [view, setView] = useState<SettingsView>("general");
  const views: SettingsView[] = [
    "general",
    "hostname",
    "groups",
    "inventory",
    "repositories",
    "power",
    "maintenance",
  ];
  let content: React.ReactNode;
  if (view === "hostname")
    content = (
      <HostnamePatterns
        items={patterns}
        canManage={canManage}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (view === "groups")
    content = (
      <Groups
        items={groups}
        canManage={canManageHosts}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (view === "inventory")
    content = (
      <Inventory
        canManage={canManageInventory}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (view === "repositories")
    content = (
      <Repositories
        items={repositories}
        canManage={canManageRepositories}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (view === "power")
    content = (
      <PowerProfiles
        items={powerProfiles}
        canManage={canManage}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (view === "maintenance")
    content = (
      <div className="hosts-settings-stack">
        <Checks items={diagnostics} t={t} />
        <Backups
          items={backups}
          canManage={canManageBackup}
          t={t}
          toast={toast}
          refresh={refresh}
        />
      </div>
    );
  else
    content = (
      <Settings
        value={value}
        patterns={patterns}
        canManage={canManage}
        t={t}
        toast={toast}
        onChange={onChange}
      />
    );
  return (
    <div className="hosts-settings-workspace">
      <nav className="hosts-settings-nav" aria-label={t("hosts.settings.navigation")}>
        {views.map((item) => (
          <button
            className={view === item ? "active" : ""}
            key={item}
            type="button"
            onClick={() => setView(item)}
          >
            {t(`hosts.settings.view.${item}`)}
          </button>
        ))}
      </nav>
      <div className="hosts-settings-content">{content}</div>
    </div>
  );
}

function HostnamePatterns({
  items,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerHostnamePattern[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [editing, setEditing] =
    useState<HostsManagerHostnamePattern | null | undefined>();
  const [name, setName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [suffix, setSuffix] = useState("");
  const [digits, setDigits] = useState(3);
  const [startValue, setStartValue] = useState(1);
  const [step, setStep] = useState(1);
  const [description, setDescription] = useState("");
  const [active, setActive] = useState(true);

  function edit(item: HostsManagerHostnamePattern | null) {
    setEditing(item);
    setName(item?.name || "");
    setPrefix(item?.prefix || "");
    setSuffix(item?.suffix || "");
    setDigits(item?.digits || 3);
    setStartValue(item?.start_value || 1);
    setStep(item?.step || 1);
    setDescription(item?.description || "");
    setActive(item?.active ?? true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerHostnamePattern(
        {
          name,
          prefix,
          suffix,
          digits,
          start_value: startValue,
          step,
          description,
          active,
        },
        editing?.id,
      );
      setEditing(undefined);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }

  async function remove(item: HostsManagerHostnamePattern) {
    if (
      !window.confirm(
        t("hosts.pattern.deleteConfirm").replace("{name}", item.name),
      )
    )
      return;
    try {
      await api.deleteHostsManagerHostnamePattern(item.id);
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }

  async function skip(item: HostsManagerHostnamePattern) {
    try {
      await api.skipHostsManagerHostnamePattern(
        item.id,
        1,
        t("hosts.pattern.manualSkip"),
      );
      await refresh();
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    }
  }

  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.pattern.title")}</h3>
          <p>{t("hosts.pattern.hint")}</p>
        </div>
        {canManage && (
          <button type="button" onClick={() => edit(null)}>
            <Plus />
            {t("hosts.pattern.add")}
          </button>
        )}
      </header>
      <div className="hosts-pattern-grid">
        {items.map((item) => (
          <article className="data-card hosts-pattern-card" key={item.id}>
            <header>
              <div>
                <strong>{item.name}</strong>
                <Status value={item.active ? "active" : "disabled"} t={t} />
              </div>
              <code>{item.template}</code>
            </header>
            <p>{item.description || t("common.none")}</p>
            <div className="hosts-settings-preview">
              {item.preview_hostnames.map((hostname) => (
                <code key={hostname}>{hostname}</code>
              ))}
            </div>
            <dl>
              <dt>{t("hosts.pattern.next")}</dt>
              <dd>
                <code>{item.next_hostname}</code>
              </dd>
              <dt>{t("hosts.pattern.last")}</dt>
              <dd>{item.last_value ?? t("common.none")}</dd>
            </dl>
            {canManage && (
              <div className="hosts-table-actions">
                <button type="button" onClick={() => void skip(item)}>
                  {t("hosts.pattern.skip")}
                </button>
                <button type="button" onClick={() => edit(item)}>
                  {t("action.edit")}
                </button>
                <button
                  className="button-danger"
                  type="button"
                  onClick={() => void remove(item)}
                >
                  {t("action.delete")}
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
      {!items.length && (
        <div className="empty-state">{t("hosts.pattern.empty")}</div>
      )}
      {editing !== undefined && (
        <Modal
          title={t(editing ? "hosts.pattern.edit" : "hosts.pattern.add")}
          closeLabel={t("action.close")}
          onClose={() => setEditing(undefined)}
          footer={
            <button
              className="button-primary"
              type="submit"
              form="hostname-pattern-form"
            >
              {t("action.save")}
            </button>
          }
        >
          <form
            id="hostname-pattern-form"
            className="module-form-grid"
            onSubmit={save}
          >
            <label>
              {t("common.name")}
              <input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.pattern.prefix")}
              <input
                value={prefix}
                onChange={(event) => setPrefix(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.pattern.suffix")}
              <input
                value={suffix}
                onChange={(event) => setSuffix(event.target.value)}
              />
            </label>
            <label>
              {t("hosts.pattern.digits")}
              <input
                type="number"
                min={1}
                max={9}
                value={digits}
                onChange={(event) => setDigits(Number(event.target.value))}
              />
            </label>
            <label>
              {t("hosts.pattern.start")}
              <input
                type="number"
                min={0}
                value={startValue}
                onChange={(event) => setStartValue(Number(event.target.value))}
              />
            </label>
            <label>
              {t("hosts.pattern.step")}
              <input
                type="number"
                min={1}
                value={step}
                onChange={(event) => setStep(Number(event.target.value))}
              />
            </label>
            <label className="module-form-span">
              {t("common.description")}
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={active}
                onChange={(event) => setActive(event.target.checked)}
              />
              {t("common.enabled")}
            </label>
          </form>
        </Modal>
      )}
    </section>
  );
}

function settingsPayload(value: HostsManagerSettings): HostsManagerSettingsUpdate {
  const payload: Record<string, unknown> = { ...value };
  [
    "next_hostname",
    "sequence_width",
    "preview_hostnames",
    "updated_at",
    "updated_by",
  ].forEach((key) => delete payload[key]);
  return payload as HostsManagerSettingsUpdate;
}

function Settings({
  value,
  patterns,
  canManage,
  t,
  toast,
  onChange,
}: {
  value: HostsManagerSettings | null;
  patterns: HostsManagerHostnamePattern[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  onChange: (value: HostsManagerSettings) => void;
}) {
  const [draft, setDraft] = useState<HostsManagerSettingsUpdate | null>(
    value ? settingsPayload(value) : null,
  );
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!value) return;
    setDraft(settingsPayload(value));
  }, [value]);
  const template = draft?.hostname_template || "";
  const valid =
    /^[A-Za-z0-9-]{1,63}$/.test(template) &&
    !template.startsWith("-") &&
    !template.endsWith("-") &&
    (template.match(/X+/g) || []).length === 1 &&
    /X{1,9}/.test(template);
  function update<K extends keyof HostsManagerSettingsUpdate>(
    key: K,
    next: HostsManagerSettingsUpdate[K],
  ) {
    setDraft((current) =>
      current ? { ...current, [key]: next } : current,
    );
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || !draft) return;
    setSaving(true);
    try {
      const updated = await api.saveHostsManagerSettings(draft);
      onChange(updated);
      toast(t("hosts.settings.saved"), "ok");
    } catch (error) {
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
    } finally {
      setSaving(false);
    }
  }
  if (!value || !draft)
    return <div className="loading-state">{t("status.loading")}</div>;
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("module.section.settings")}</h3>
          <p>{t("hosts.settings.hint")}</p>
        </div>
      </header>
      <form
        className="hosts-settings-form"
        onSubmit={(event) => void save(event)}
      >
        <fieldset>
          <legend>{t("hosts.settings.communication")}</legend>
          <div className="module-form-grid">
            <label>
              {t("hosts.settings.serverUrl")}
              <input
                type="url"
                value={draft.server_url}
                disabled={!canManage}
                onChange={(event) => update("server_url", event.target.value)}
              />
            </label>
            <label>
              {t("hosts.settings.protocol")}
              <select
                value={draft.agent_protocol}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "agent_protocol",
                    event.target.value as "https" | "wss",
                  )
                }
              >
                <option value="https">HTTPS</option>
                <option value="wss">WSS</option>
              </select>
            </label>
            <label>
              {t("hosts.agent.port")}
              <input
                type="number"
                min={1}
                max={65535}
                value={draft.agent_default_port}
                disabled={!canManage}
                onChange={(event) =>
                  update("agent_default_port", Number(event.target.value))
                }
              />
            </label>
            <label>
              {t("hosts.settings.connectionTimeout")}
              <input
                type="number"
                min={1}
                value={draft.connection_timeout_seconds}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "connection_timeout_seconds",
                    Number(event.target.value),
                  )
                }
              />
            </label>
            <label>
              {t("hosts.agent.heartbeatInterval")}
              <input
                type="number"
                min={10}
                value={draft.heartbeat_interval_seconds}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "heartbeat_interval_seconds",
                    Number(event.target.value),
                  )
                }
              />
            </label>
            <label>
              {t("hosts.agent.reportInterval")}
              <input
                type="number"
                min={30}
                value={draft.report_interval_seconds}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "report_interval_seconds",
                    Number(event.target.value),
                  )
                }
              />
            </label>
            <label>
              {t("hosts.settings.maxRetries")}
              <input
                type="number"
                min={0}
                value={draft.max_connection_retries}
                disabled={!canManage}
                onChange={(event) =>
                  update("max_connection_retries", Number(event.target.value))
                }
              />
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("hosts.settings.ssh")}</legend>
          <div className="module-form-grid">
            <label>
              {t("hosts.settings.sshPort")}
              <input
                type="number"
                min={1}
                max={65535}
                value={draft.ssh_default_port}
                disabled={!canManage}
                onChange={(event) =>
                  update("ssh_default_port", Number(event.target.value))
                }
              />
            </label>
            <label>
              {t("hosts.settings.sshTimeout")}
              <input
                type="number"
                min={1}
                value={draft.ssh_timeout_seconds}
                disabled={!canManage}
                onChange={(event) =>
                  update("ssh_timeout_seconds", Number(event.target.value))
                }
              />
            </label>
            <label>
              {t("hosts.settings.sshConcurrency")}
              <input
                type="number"
                min={1}
                value={draft.ssh_max_concurrency}
                disabled={!canManage}
                onChange={(event) =>
                  update("ssh_max_concurrency", Number(event.target.value))
                }
              />
            </label>
            <label>
              {t("hosts.settings.hostKeyPolicy")}
              <select
                value={draft.ssh_new_host_key_policy}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "ssh_new_host_key_policy",
                    event.target.value as "ask" | "reject" | "accept_new",
                  )
                }
              >
                <option value="ask">{t("hosts.settings.hostKey.ask")}</option>
                <option value="reject">
                  {t("hosts.settings.hostKey.reject")}
                </option>
                <option value="accept_new">
                  {t("hosts.settings.hostKey.acceptNew")}
                </option>
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.ssh_verify_fingerprint}
                disabled={!canManage}
                onChange={(event) =>
                  update("ssh_verify_fingerprint", event.target.checked)
                }
              />
              {t("hosts.settings.verifyFingerprint")}
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("hosts.settings.agent")}</legend>
          <div className="module-form-grid">
            <label>
              {t("hosts.settings.minimumAgentVersion")}
              <input
                value={draft.agent_min_version}
                disabled={!canManage}
                onChange={(event) =>
                  update("agent_min_version", event.target.value)
                }
              />
            </label>
            <label>
              {t("hosts.settings.updateChannel")}
              <select
                value={draft.agent_update_channel}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "agent_update_channel",
                    event.target.value as "stable" | "beta" | "pinned",
                  )
                }
              >
                <option value="stable">
                  {t("hosts.settings.channel.stable")}
                </option>
                <option value="beta">
                  {t("hosts.settings.channel.beta")}
                </option>
                <option value="pinned">
                  {t("hosts.settings.channel.pinned")}
                </option>
              </select>
            </label>
            <label>
              {t("hosts.settings.repositoryUrl")}
              <input
                type="url"
                value={draft.agent_repository_url}
                disabled={!canManage}
                onChange={(event) =>
                  update("agent_repository_url", event.target.value)
                }
              />
            </label>
            <label>
              {t("hosts.settings.logLevel")}
              <select
                value={draft.agent_log_level}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "agent_log_level",
                    event.target.value as HostsManagerSettingsUpdate["agent_log_level"],
                  )
                }
              >
                {["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map(
                  (level) => (
                    <option key={level}>{level}</option>
                  ),
                )}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.agent_auto_update}
                disabled={!canManage}
                onChange={(event) =>
                  update("agent_auto_update", event.target.checked)
                }
              />
              {t("hosts.settings.autoUpdate")}
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.agent_enforce_tls}
                disabled={!canManage}
                onChange={(event) =>
                  update("agent_enforce_tls", event.target.checked)
                }
              />
              {t("hosts.settings.enforceTls")}
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("hosts.settings.security")}</legend>
          <div className="module-form-grid">
            <label>
              {t("hosts.settings.tokenTtl")}
              <input
                type="number"
                min={1}
                value={draft.token_ttl_minutes}
                disabled={!canManage}
                onChange={(event) =>
                  update("token_ttl_minutes", Number(event.target.value))
                }
              />
            </label>
            <label>
              {t("hosts.settings.maxAuthFailures")}
              <input
                type="number"
                min={1}
                value={draft.max_auth_failures}
                disabled={!canManage}
                onChange={(event) =>
                  update("max_auth_failures", Number(event.target.value))
                }
              />
            </label>
            <label className="module-form-span">
              {t("hosts.settings.allowedNetworks")}
              <textarea
                value={draft.allowed_registration_networks.join("\n")}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "allowed_registration_networks",
                    event.target.value
                      .split(/[\n,]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                  )
                }
              />
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("hosts.settings.namingDefaults")}</legend>
          <div className="module-form-grid">
            <label>
              {t("hosts.settings.defaultPattern")}
              <select
                value={draft.default_hostname_pattern_id || ""}
                disabled={!canManage}
                onChange={(event) =>
                  update(
                    "default_hostname_pattern_id",
                    event.target.value || null,
                  )
                }
              >
                <option value="">{t("common.none")}</option>
                {patterns.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.next_hostname})
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("hosts.settings.hostnameTemplate")}
              <input
                value={template}
                disabled={!canManage}
                maxLength={63}
                onChange={(event) =>
                  update("hostname_template", event.target.value)
                }
                aria-invalid={!valid}
              />
              {!valid && (
                <small className="field-error" role="alert">
                  {t("hosts.settings.hostnameTemplateInvalid")}
                </small>
              )}
              <small>{t("hosts.settings.hostnameTemplateHint")}</small>
            </label>
            <label>
              {t("hosts.enrollment.os")}
              <select
                disabled={!canManage}
                value={draft.bootstrap_default_os}
                onChange={(event) =>
                  update(
                    "bootstrap_default_os",
                    event.target.value as "linux" | "windows",
                  )
                }
              >
                <option value="linux">{t("hosts.enrollment.os.linux")}</option>
                <option value="windows">
                  {t("hosts.enrollment.os.windows")}
                </option>
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                disabled={!canManage}
                checked={draft.bootstrap_apply_hostname}
                onChange={(event) =>
                  update("bootstrap_apply_hostname", event.target.checked)
                }
              />
              {t("hosts.enrollment.applyHostname")}
            </label>
          </div>
          <div>
            <strong>{t("hosts.settings.preview")}</strong>
            <div className="hosts-settings-preview">
              {value.preview_hostnames.map((item) => (
                <code key={item}>{item}</code>
              ))}
            </div>
          </div>
          <dl>
            <dt>{t("hosts.settings.nextHostname")}</dt>
            <dd>
              <code>{value.next_hostname}</code>
            </dd>
          </dl>
          <p>{t("hosts.settings.reservationHint")}</p>
        </fieldset>
        {canManage && (
          <button
            className="button-primary hosts-settings-save"
            disabled={!valid || saving}
          >
            {t("action.save")}
          </button>
        )}
      </form>
    </section>
  );
}
function Records<T extends object>({ items, t }: { items: T[]; t: Translate }) {
  const normalized = items.map((value, index) => {
    const item = value as {
      id?: string;
      name?: string;
      filename?: string;
      description?: string;
      type?: string;
      provider?: string;
      status?: string;
      updated_at?: number;
    };
    return {
      key: item.id || item.filename || String(index),
      name: item.name || item.filename || item.id || t("common.none"),
      description:
        item.description ||
        item.type ||
        item.provider ||
        item.status ||
        t("common.none"),
      updated: item.updated_at,
    };
  });
  const columns: HostsDataColumn<(typeof normalized)[number]>[] = [
    {
      id: "name",
      label: t("common.name"),
      sortValue: (item) => item.name,
      cell: (item) => <strong>{item.name}</strong>,
    },
    {
      id: "description",
      label: t("hosts.operation.details"),
      sortValue: (item) => item.description,
      cell: (item) => item.description,
    },
    {
      id: "updated",
      label: t("hosts.operation.updated"),
      sortValue: (item) => item.updated || 0,
      cell: (item) =>
        item.updated
          ? new Date(item.updated * 1000).toLocaleString()
          : t("common.none"),
    },
  ];
  return (
    <HostsDataTable
      items={normalized}
      columns={columns}
      rowKey={(item) => item.key}
      empty={t("hosts.records.empty")}
    />
  );
}
function Checks({
  items,
  t,
}: {
  items: Array<{ id: string; status: string; message: string }>;
  t: Translate;
}) {
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.diagnostics.title")}</h3>
          <p>{t("hosts.diagnostics.hint")}</p>
        </div>
      </header>
      {items.map((item) => (
        <article className="module-diagnostic" key={item.id}>
          <Status value={item.status} t={t} />
          <strong>{t(`hosts.diagnostics.${item.id}`)}</strong>
          <span>{item.message}</span>
        </article>
      ))}
    </section>
  );
}
function Status({ value, t }: { value: string; t: Translate }) {
  return (
    <span className={`package-status hosts-status-pill ui-status-${value}`}>
      {t(`hosts.status.${value}`)}
    </span>
  );
}
