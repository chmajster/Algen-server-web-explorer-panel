import {
  AlertTriangle,
  Copy,
  Download,
  Filter,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type HostsManagerBackup,
  type HostsManagerCapability,
  type HostsManagerCredential,
  type HostsManagerDashboard,
  type HostsManagerEnrollmentToken,
  type HostsManagerGroup,
  type HostsManagerHost,
  type HostsManagerOperation,
  type HostsManagerPowerProfile,
  type HostsManagerRepository,
  type HostsManagerSettings,
  type ModuleStatus,
} from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import {
  ModuleAppShell,
  ModuleHealthCard,
  type ModuleSection,
} from "../common/ModuleAppShell";
import {
  HostsDataTable,
  type HostsDataColumn,
} from "./components/HostsDataTable";

type Props = { permissions: string[]; t: Translate; toast: ToastFn };
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
  package_version: "1.0.0",
};
const sections: ModuleSection[] = [
  "overview",
  "hosts",
  "groups",
  "enrollment",
  "discovery",
  "inventory",
  "credentials",
  "repositories",
  "power",
  "operations",
  "settings",
  "diagnostics",
  "backups",
];

export function HostsManagerApp({ permissions, t, toast }: Props) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [dashboard, setDashboard] = useState<HostsManagerDashboard | null>(
    null,
  );
  const [hosts, setHosts] = useState<HostsManagerHost[]>([]);
  const [groups, setGroups] = useState<HostsManagerGroup[]>([]);
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

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const base = await Promise.all([
        api.hostsManagerDashboard(),
        api.hostsManagerHosts(),
        api.hostsManagerGroups(),
        api.hostsManagerSettings(),
      ]);
      setDashboard(base[0]);
      setHosts(base[1]);
      setGroups(base[2]);
      setManagerSettings(base[3]);
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

  useEffect(() => {
    void refresh();
  }, [refresh]);
  let content: React.ReactNode;
  if (section === "overview") content = <Dashboard value={dashboard} t={t} />;
  else if (section === "hosts")
    content = (
      <Hosts
        items={hosts}
        groups={groups}
        permissions={permissions}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "groups")
    content = (
      <Groups
        items={groups}
        canManage={can("hosts-manager.hosts.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "enrollment")
    content = (
      <Enrollment
        items={tokens}
        groups={groups}
        settings={managerSettings}
        canManage={can("hosts-manager.hosts.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "operations")
    content = <Operations items={operations} t={t} />;
  else if (section === "discovery")
    content = (
      <Discovery
        canManage={can("hosts-manager.discovery")}
        t={t}
        toast={toast}
      />
    );
  else if (section === "inventory")
    content = (
      <Inventory
        canManage={can("hosts-manager.inventory.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "credentials")
    content = (
      <Credentials
        items={credentials}
        canManage={can("hosts-manager.credentials.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "repositories")
    content = (
      <Repositories
        items={repositories}
        canManage={can("hosts-manager.repositories.manage")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "power")
    content = (
      <PowerProfiles
        items={powerProfiles}
        canManage={can("hosts-manager.configure")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else if (section === "diagnostics")
    content = <Checks items={diagnostics} t={t} />;
  else if (section === "backups")
    content = (
      <Backups
        items={backups}
        canManage={can("hosts-manager.backup")}
        t={t}
        toast={toast}
        refresh={refresh}
      />
    );
  else
    content = (
      <Settings
        value={managerSettings}
        canManage={can("hosts-manager.configure")}
        t={t}
        toast={toast}
        onChange={setManagerSettings}
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
      onSection={setSection}
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
  t,
}: {
  value: HostsManagerDashboard | null;
  t: Translate;
}) {
  if (!value) return null;
  const cards: Array<
    [string, number, "neutral" | "success" | "warning" | "danger"]
  > = [
    ["total", value.total, "neutral"],
    ["online", value.online, "success"],
    ["offline", value.offline, "danger"],
    ["unverified", value.unverified, "warning"],
    ["fingerprintErrors", value.fingerprint_errors, "danger"],
    ["pendingApproval", value.pending_approval, "warning"],
    ["ansibleAvailable", value.ansible_available, "success"],
    ["powerManaged", value.power_managed, "neutral"],
  ];
  return (
    <>
      <div className="module-health-grid ansible-dashboard">
        {cards.map(([key, count, tone]) => (
          <ModuleHealthCard
            key={key}
            title={t(`hosts.dashboard.${key}`)}
            value={count}
            tone={tone}
          />
        ))}
      </div>
      <div className="ansible-panel">
        <h3>{t("hosts.operations.recent")}</h3>
        <Operations items={value.recent_operations} t={t} />
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
  permissions,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerHost[];
  groups: HostsManagerGroup[];
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [cards, setCards] = useState(false);
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
            item.connection_status === statusFilter ||
            item.fingerprint_status === statusFilter),
      ),
    [items, query, statusFilter],
  );
  const canManage = permissions.includes("hosts-manager.hosts.manage");
  async function remove(item: HostsManagerHost) {
    if (!window.confirm(t("hosts.host.deleteConfirm").replace("{name}", item.name))) return;
    try {
      await api.deleteHostsManagerHost(item.id);
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
  const columns: HostsDataColumn<HostsManagerHost>[] = [
    { id: "name", label: t("common.name"), sortValue: (item) => item.name, cell: (item) => <span className="hosts-primary-cell"><strong>{item.name}</strong><small>{item.hostname || t("common.none")}</small></span> },
    { id: "address", label: t("hosts.host.address"), sortValue: (item) => item.address, cell: (item) => `${item.address}:${item.port}` },
    { id: "environment", label: t("hosts.host.environment"), sortValue: (item) => item.environment, cell: (item) => item.environment || t("common.none") },
    { id: "location", label: t("hosts.host.location"), sortValue: (item) => item.location, cell: (item) => item.location || t("common.none") },
    { id: "groups", label: t("hosts.groups.title"), sortValue: (item) => (item.groups || []).join(","), cell: (item) => (item.groups || []).join(", ") || t("common.none") },
    { id: "connection", label: t("common.status"), sortValue: (item) => item.connection_status, cell: (item) => <Status value={item.connection_status} t={t} /> },
    { id: "fingerprint", label: t("hosts.host.fingerprint"), sortValue: (item) => item.fingerprint_status, cell: (item) => <Status value={item.fingerprint_status} t={t} /> },
    { id: "approval", label: t("hosts.host.approval"), sortValue: (item) => item.approved ? 1 : 0, cell: (item) => <Status value={item.approved ? "approved" : "pending_approval"} t={t} /> },
    { id: "activity", label: t("hosts.host.lastActivity"), sortValue: (item) => item.last_test_at || 0, cell: (item) => item.last_test_at ? new Date(item.last_test_at * 1000).toLocaleString() : t("common.none") },
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
            <option value="unverified">{t("hosts.status.unverified")}</option>
            <option value="changed">{t("hosts.status.changed")}</option>
          </select>
        </label>
        <button type="button" onClick={() => setCards((value) => !value)}>
          {t(cards ? "hosts.view.list" : "hosts.view.cards")}
        </button>
      </div>
      {cards ? (
        <div className="card-grid">
          {filtered.map((item) => (
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
          items={filtered}
          columns={columns}
          rowKey={(item) => item.id}
          empty={t("hosts.list.empty")}
          onSelect={(item) => setSelected(item)}
          selectedKey={selected?.id}
        />
      )}
      {editing !== undefined && (
        <HostForm
          value={editing}
          groups={groups}
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
  t,
  toast,
  onClose,
  onSaved,
}: {
  value: HostsManagerHost | null;
  groups: HostsManagerGroup[];
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
          <input
            value={environment}
            onChange={(event) => setEnvironment(event.target.value)}
          />
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
  useEffect(() => {
    void api.hostsManagerCapabilities(value.id).then(setCapabilities);
  }, [value.id]);
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
  return (
    <Modal
      wide
      title={value.name}
      closeLabel={t("action.close")}
      onClose={onClose}
    >
      <div className="ansible-detail-grid">
        <section>
          <h3>{t("hosts.details.summary")}</h3>
          <dl>
            <dt>{t("hosts.host.address")}</dt>
            <dd>
              {value.address}:{value.port}
            </dd>
            <dt>{t("hosts.host.environment")}</dt>
            <dd>{value.environment || t("common.none")}</dd>
            <dt>{t("hosts.host.location")}</dt>
            <dd>{value.location || t("common.none")}</dd>
            <dt>{t("hosts.host.fingerprint")}</dt>
            <dd>
              <Status value={value.fingerprint_status} t={t} />
            </dd>
            <dt>{t("hosts.host.approval")}</dt>
            <dd>{t(value.approved ? "common.yes" : "common.no")}</dd>
          </dl>
        </section>
        <section>
          <h3>{t("hosts.details.facts")}</h3>
          <pre>{JSON.stringify(value.facts || {}, null, 2)}</pre>
        </section>
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
    </Modal>
  );
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
    { id: "name", label: t("common.name"), sortValue: (item) => item.name, cell: (item) => <strong>{item.name}</strong> },
    { id: "description", label: t("hosts.host.description"), sortValue: (item) => item.description, cell: (item) => item.description || t("common.none") },
    { id: "parent", label: t("hosts.group.parent"), sortValue: (item) => items.find((parent) => parent.id === item.parent_id)?.name || "", cell: (item) => items.find((parent) => parent.id === item.parent_id)?.name || t("common.none") },
    { id: "hosts", label: t("hosts.groups.hosts"), align: "end", sortValue: (item) => item.host_ids.length, cell: (item) => item.host_ids.length },
    { id: "status", label: t("common.status"), sortValue: (item) => item.active ? 1 : 0, cell: (item) => <Status value={item.active ? "active" : "disabled"} t={t} /> },
    { id: "updated", label: t("hosts.operation.updated"), sortValue: (item) => item.updated_at, cell: (item) => new Date(item.updated_at * 1000).toLocaleString() },
    { id: "actions", label: t("column.actions"), cell: (item) => <div className="module-row-actions"><button onClick={() => setSelected(item)}>{t("hosts.group.showHosts")}</button>{canManage && <><button onClick={() => edit(item)}>{t("action.edit")}</button><button className="button-danger" onClick={() => void remove(item)}>{t("action.delete")}</button></>}</div> },
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

function Enrollment({
  items,
  groups,
  settings,
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerEnrollmentToken[];
  groups: HostsManagerGroup[];
  settings: HostsManagerSettings | null;
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [minutes, setMinutes] = useState(15);
  const [bootstrapOS, setBootstrapOS] = useState<"linux" | "windows">("linux");
  const [applyHostname, setApplyHostname] = useState(true);
  const [sshUser, setSshUser] = useState("algen-ansible");
  const [port, setPort] = useState(22);
  const [environment, setEnvironment] = useState("");
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
    }
  }, [settings]);
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
    try {
      const item = await api.createHostsManagerEnrollmentToken({
        bootstrap_os: bootstrapOS,
        apply_hostname: applyHostname,
        expires_minutes: minutes,
        port,
        ssh_user: sshUser,
        credential_id: null,
        environment,
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
      toast(
        error instanceof Error ? error.message : t("error.generic"),
        "error",
      );
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
      cell: (item) => new Date(item.expires_at * 1000).toLocaleString(),
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
          <button className="button-primary" onClick={() => setOpen(true)}>
            <Plus />
            {t("hosts.enrollment.generate")}
          </button>
        )}
      </header>
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
            <div className="wide">
              <strong>{t("hosts.enrollment.assignedHostname")}</strong>
              <code>{settings?.next_hostname || "…"}</code>
              <small>{t("hosts.settings.reservationHint")}</small>
            </div>
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
            <label>
              {t("hosts.enrollment.minutes")}
              <input
                type="number"
                min="1"
                max="60"
                value={minutes}
                onChange={(event) => setMinutes(Number(event.target.value))}
              />
            </label>
            <label>
              {t("hosts.host.user")}
              <input
                value={sshUser}
                onChange={(event) => setSshUser(event.target.value)}
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
              {t("hosts.host.environment")}
              <input
                value={environment}
                onChange={(event) => setEnvironment(event.target.value)}
              />
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
          <p>{t("hosts.enrollment.onceHint")}</p>
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
  t,
}: {
  items: HostsManagerOperation[];
  t: Translate;
}) {
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
    <HostsDataTable
      items={items}
      columns={columns}
      rowKey={(item) => item.id}
      empty={t("hosts.operations.empty")}
    />
  );
}
function Discovery({
  canManage,
  t,
  toast,
}: {
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
}) {
  const [cidr, setCidr] = useState("192.168.1.0/24");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  async function scan(event: React.FormEvent) {
    event.preventDefault();
    try {
      setResult(
        await api.startHostsManagerScan({
          cidr,
          start_address: null,
          end_address: null,
          port: 22,
          timeout_seconds: 2,
          concurrency: 32,
          reverse_dns: true,
        }),
      );
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
          <h3>{t("module.section.discovery")}</h3>
          <p>{t("hosts.discovery.hint")}</p>
        </div>
      </header>
      <form className="module-form-grid" onSubmit={scan}>
        <label>
          {t("hosts.discovery.cidr")}
          <input
            value={cidr}
            onChange={(event) => setCidr(event.target.value)}
            disabled={!canManage}
          />
        </label>
        <button className="button-primary" disabled={!canManage}>
          {t("hosts.discovery.scan")}
        </button>
      </form>
      {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
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
  canManage,
  t,
  toast,
  refresh,
}: {
  items: HostsManagerCredential[];
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [secret, setSecret] = useState("");
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api.saveHostsManagerCredential({
        name,
        type: "ssh_password",
        username,
        secret,
        passphrase: "",
        description: "",
        confirm: true,
      });
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
  return (
    <section className="ansible-panel">
      <header>
        <div>
          <h3>{t("hosts.credentials.title")}</h3>
          <p>{t("hosts.credentials.hint")}</p>
        </div>
        {canManage && (
          <button onClick={() => setOpen(true)}>
            <Plus />
            {t("hosts.credentials.add")}
          </button>
        )}
      </header>
      <Records items={items} t={t} />
      {open && (
        <Modal
          title={t("hosts.credentials.add")}
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
              {t("hosts.host.user")}
              <input
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
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
function Settings({
  value,
  canManage,
  t,
  toast,
  onChange,
}: {
  value: HostsManagerSettings | null;
  canManage: boolean;
  t: Translate;
  toast: ToastFn;
  onChange: (value: HostsManagerSettings) => void;
}) {
  const [template, setTemplate] = useState(
    value?.hostname_template || "SCL000XXX",
  );
  const [bootstrapOS, setBootstrapOS] = useState<"linux" | "windows">(
    value?.bootstrap_default_os || "linux",
  );
  const [applyHostname, setApplyHostname] = useState(
    value?.bootstrap_apply_hostname ?? true,
  );
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!value) return;
    setTemplate(value.hostname_template);
    setBootstrapOS(value.bootstrap_default_os);
    setApplyHostname(value.bootstrap_apply_hostname);
  }, [value]);
  const valid =
    /^[A-Za-z0-9-]{1,63}$/.test(template) &&
    !template.startsWith("-") &&
    !template.endsWith("-") &&
    (template.match(/X+/g) || []).length === 1 &&
    /X{1,9}/.test(template);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setSaving(true);
    try {
      const updated = await api.saveHostsManagerSettings({
        hostname_template: template,
        bootstrap_default_os: bootstrapOS,
        bootstrap_apply_hostname: applyHostname,
      });
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
  if (!value) return <div className="loading-state">{t("status.loading")}</div>;
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
        <label>
          {t("hosts.settings.hostnameTemplate")}
          <input
            value={template}
            disabled={!canManage}
            maxLength={63}
            onChange={(event) => setTemplate(event.target.value)}
            aria-invalid={!valid}
          />
          {!valid && (
            <small className="field-error" role="alert">
              {t("hosts.settings.hostnameTemplateInvalid")}
            </small>
          )}
          <small>{t("hosts.settings.hostnameTemplateHint")}</small>
        </label>
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
        <label>
          {t("hosts.enrollment.os")}
          <select
            disabled={!canManage}
            value={bootstrapOS}
            onChange={(event) =>
              setBootstrapOS(event.target.value as "linux" | "windows")
            }
          >
            <option value="linux">{t("hosts.enrollment.os.linux")}</option>
            <option value="windows">{t("hosts.enrollment.os.windows")}</option>
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            disabled={!canManage}
            checked={applyHostname}
            onChange={(event) => setApplyHostname(event.target.checked)}
          />
          {t("hosts.enrollment.applyHostname")}
        </label>
        <p>{t("hosts.settings.reservationHint")}</p>
        {canManage && (
          <button className="button-primary" disabled={!valid || saving}>
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
