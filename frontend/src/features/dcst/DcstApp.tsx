import { Activity, Globe, Pencil, Plus, RefreshCw, Search, Shield, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ToastFn, Translate } from "../../app/types";
import { dcstClient, type DcstIPSet, type DcstPort, type DcstService, type DcstServiceInput, type DcstTag } from "../../modules/dcst/api/client";
import { DcstConfirmDialog, type DcstConfirmAction } from "./components/DcstConfirmDialog";
import { DcstHeader } from "./components/DcstHeader";
import { DcstInfoDrawer, DcstIPSetDrawer, DcstPortDrawer } from "./components/DcstObjectDrawers";
import { DcstEmptyState, DcstStatusBadge } from "./components/DcstPrimitives";
import { DcstOverview } from "./components/DcstOverview";
import { DcstServiceDetails } from "./components/DcstServiceDetails";
import { DcstServiceDrawer, type DcstServiceErrors } from "./components/DcstServiceDrawer";
import { DcstServiceTable } from "./components/DcstServiceTable";
import { DcstTabs, type DcstTab } from "./components/DcstTabs";

const blankService: DcstServiceInput = {
  name: "",
  description: "",
  direction: "OUT",
  action: "ACCEPT",
  source_type: "tag",
  source_value: "",
  destination_type: "tag",
  destination_value: "",
  port_ids: [],
  enabled: true,
  logging: false,
  comment: "",
};

const blankPort = { name: "", protocol: "tcp" as DcstPort["protocol"], port_from: 443 as number | null, port_to: 443 as number | null, description: "" };
const blankIPSet = { name: "", description: "", entries: "" };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function syncTimestamp(value: unknown): number | null {
  const record = asRecord(value);
  const raw = record.at ?? record.timestamp ?? record.time ?? record.updated_at;
  if (raw === undefined || raw === null || raw === "") return null;
  const numeric = Number(raw);
  if (Number.isFinite(numeric)) return numeric > 10_000_000_000 ? numeric : numeric * 1000;
  const parsed = new Date(String(raw)).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function relativeTime(value: unknown) {
  const timestamp = syncTimestamp(value);
  if (!timestamp) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return `${days} d ago`;
}

function exactTime(value: unknown) {
  const timestamp = syncTimestamp(value);
  return timestamp ? new Date(timestamp).toLocaleString() : "—";
}

function recordSummary(record: Record<string, unknown>): Array<[string, unknown]> {
  const entries = Object.entries(record).filter(([, value]) => typeof value !== "object").slice(0, 10);
  return entries.length ? entries : [["status", "No structured data"]];
}

function firewallLogToken(raw: string, key: string): string {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return raw.match(new RegExp(`(?:^|\\s)${escaped}=([^\\s]+)`, "i"))?.[1] || "";
}

export function normalizeFirewallLog(row: Record<string, unknown>): Record<string, unknown> {
  const raw = String(row.t || row.msg || row.message || row.raw || JSON.stringify(row));
  const prefixedTime = raw.match(/\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?\b/)?.[0] || "";
  const time = row.time || row.timestamp || row.at || firewallLogToken(raw, "TIME") || prefixedTime;
  const direction = String(row.direction || row.dir || firewallLogToken(raw, "DIRECTION") || firewallLogToken(raw, "DIR") || "").toUpperCase();
  const action = String(row.action || row.policy_action || firewallLogToken(raw, "ACTION") || "").toUpperCase();
  const source = String(row.source || row.src || row.src_ip || firewallLogToken(raw, "SRC") || firewallLogToken(raw, "SOURCE") || "");
  const destination = String(row.destination || row.dst || row.dst_ip || firewallLogToken(raw, "DST") || firewallLogToken(raw, "DESTINATION") || "");
  return { ...row, dcst_time: time, dcst_direction: direction, dcst_action: action, dcst_source: source, dcst_destination: destination, dcst_raw: raw };
}

export function DcstApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [tab, setTab] = useState<DcstTab>("overview");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [utilitiesLoading, setUtilitiesLoading] = useState(false);
  const [synchronizing, setSynchronizing] = useState(false);
  const [overview, setOverview] = useState<Record<string, unknown>>({});
  const [services, setServices] = useState<DcstService[]>([]);
  const [tags, setTags] = useState<DcstTag[]>([]);
  const [ipsets, setIPSets] = useState<DcstIPSet[]>([]);
  const [ports, setPorts] = useState<DcstPort[]>([]);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown>>({});

  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("");
  const [action, setAction] = useState("");
  const [state, setState] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [serviceDraft, setServiceDraft] = useState<DcstServiceInput>(blankService);
  const [serviceEdit, setServiceEdit] = useState("");
  const [serviceDrawerOpen, setServiceDrawerOpen] = useState(false);
  const [serviceErrors, setServiceErrors] = useState<DcstServiceErrors>({});
  const [serviceSaving, setServiceSaving] = useState(false);
  const [detailService, setDetailService] = useState<DcstService | null>(null);
  const [detailPreview, setDetailPreview] = useState<Record<string, unknown> | null>(null);
  const previewRequest = useRef(0);

  const [portDraft, setPortDraft] = useState(blankPort);
  const [portEdit, setPortEdit] = useState("");
  const [portDrawerOpen, setPortDrawerOpen] = useState(false);
  const [portSaving, setPortSaving] = useState(false);
  const [portDetails, setPortDetails] = useState<DcstPort | null>(null);

  const [ipsetDraft, setIPSetDraft] = useState(blankIPSet);
  const [ipsetEdit, setIPSetEdit] = useState("");
  const [ipsetDrawerOpen, setIPSetDrawerOpen] = useState(false);
  const [ipsetSaving, setIPSetSaving] = useState(false);
  const [ipsetDetails, setIPSetDetails] = useState<DcstIPSet | null>(null);
  const [tagDetails, setTagDetails] = useState<DcstTag | null>(null);

  const [confirm, setConfirm] = useState<DcstConfirmAction>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const [logSearch, setLogSearch] = useState("");
  const [logNode, setLogNode] = useState("");
  const [logDirection, setLogDirection] = useState("");
  const [logAction, setLogAction] = useState("");
  const [logSource, setLogSource] = useState("");
  const [logDestination, setLogDestination] = useState("");
  const [logRange, setLogRange] = useState("");
  const [logSnapshotTime, setLogSnapshotTime] = useState(0);

  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);
  const notifyError = useCallback((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"), [t, toast]);
  const success = useCallback((message: string) => toast(message, "ok", "admin"), [toast]);

  const refresh = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    try {
      const [nextOverview, nextServices, nextTags, nextIPSets, nextPorts] = await Promise.all([
        dcstClient.overview(),
        dcstClient.services(),
        dcstClient.tags(),
        dcstClient.ipsets(),
        dcstClient.ports(),
      ]);
      setOverview(nextOverview as unknown as Record<string, unknown>);
      setServices(nextServices);
      setTags(nextTags);
      setIPSets(nextIPSets);
      setPorts(nextPorts);
    } catch (error) {
      notifyError(error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [notifyError]);

  useEffect(() => { void refresh(true); }, [refresh]);

  const loadUtilities = useCallback(async () => {
    setUtilitiesLoading(true);
    try {
      const [nextLogs, nextDiagnostics] = await Promise.all([dcstClient.firewallLogs(), dcstClient.diagnostics()]);
      setLogs(nextLogs);
      setLogSnapshotTime(Date.now());
      setDiagnostics(nextDiagnostics);
    } catch (error) {
      notifyError(error);
    } finally {
      setUtilitiesLoading(false);
    }
  }, [notifyError]);

  const visibleServices = useMemo(() => services.filter((item) => {
    const text = `${item.name} ${item.description} ${item.source_value} ${item.destination_value} ${item.direction} ${item.action}`.toLowerCase();
    return (!search || text.includes(search.toLowerCase()))
      && (!direction || item.direction === direction)
      && (!action || (item.blocked ? "DROP" : item.action) === action)
      && (!state || item.state === state);
  }), [services, search, direction, action, state]);

  const inventoryReady = tags.length > 0 || Boolean(syncTimestamp(overview.last_inventory_sync));
  const lastSyncSource = overview.last_firewall_sync;
  const lastSyncLabel = relativeTime(lastSyncSource);
  const lastSyncExact = exactTime(lastSyncSource);
  const managedObjectCount = services.length + tags.length + ipsets.length + ports.length;

  function openCreateService() {
    setServiceEdit("");
    setServiceDraft(blankService);
    setServiceErrors({});
    setServiceDrawerOpen(true);
  }

  function editService(item: DcstService) {
    setServiceEdit(item.id);
    setServiceDraft({
      name: item.name,
      description: item.description,
      direction: item.direction,
      action: item.action,
      source_type: item.source_type,
      source_value: item.source_value,
      destination_type: item.destination_type,
      destination_value: item.destination_value,
      port_ids: item.port_ids,
      enabled: item.enabled,
      logging: item.logging,
      comment: item.comment,
    });
    setServiceErrors({});
    setServiceDrawerOpen(true);
  }

  function closeServiceDrawer() {
    if (serviceSaving) return;
    setServiceDrawerOpen(false);
    setServiceErrors({});
  }

  function validateService() {
    const errors: DcstServiceErrors = {};
    if (!serviceDraft.name.trim()) errors.name = "Service name is required.";
    if (serviceDraft.source_type !== "any" && !serviceDraft.source_value.trim()) errors.source = "Source object is required.";
    if (serviceDraft.destination_type !== "any" && !serviceDraft.destination_value.trim()) errors.destination = "Destination object is required.";
    if (!serviceDraft.direction) errors.direction = "Direction is required.";
    if (!serviceDraft.action) errors.action = "Action is required.";
    setServiceErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function saveService() {
    if (!validateService()) return;
    setServiceSaving(true);
    try {
      await dcstClient.saveService(serviceDraft, serviceEdit);
      success(serviceEdit ? "Service updated" : "Service created");
      setServiceDrawerOpen(false);
      setServiceEdit("");
      setServiceDraft(blankService);
      await refresh();
    } catch (error) {
      notifyError(error);
    } finally {
      setServiceSaving(false);
    }
  }

  async function serviceAction(item: DcstService, operation: "block" | "unblock" | "enable" | "disable") {
    try {
      await dcstClient.serviceAction(item.id, operation);
      success(`${item.name}: ${operation} completed`);
      await refresh();
    } catch (error) {
      notifyError(error);
    }
  }

  async function bulk(operation: "block" | "unblock" | "enable" | "disable" | "sync") {
    if (!selected.size) return;
    try {
      await dcstClient.bulk(operation, [...selected]);
      success(`Bulk ${operation} completed`);
      setSelected(new Set());
      await refresh();
    } catch (error) {
      notifyError(error);
    }
  }

  function confirmBulkBlock() {
    const ids = [...selected];
    if (!ids.length) return;
    setConfirm({
      title: `Block ${ids.length} communication service${ids.length === 1 ? "" : "s"}?`,
      message: "Blocking these services applies traffic-blocking firewall rules and can interrupt live communication. Confirm only if this disruption is intended.",
      confirmLabel: "Block selected",
      destructive: true,
      run: async () => {
        await dcstClient.bulk("block", ids);
        success("Bulk block completed");
        setSelected(new Set());
        await refresh();
      },
    });
  }

  function viewService(item: DcstService) {
    const requestId = ++previewRequest.current;
    setDetailService(item);
    setDetailPreview(null);
    void dcstClient.previewService(item.id).then((preview) => {
      if (previewRequest.current === requestId) setDetailPreview(preview);
    }).catch((error) => {
      if (previewRequest.current === requestId) notifyError(error);
    });
  }

  function confirmDeleteService(item: DcstService) {
    setConfirm({
      title: "Delete communication service?",
      subject: item.name,
      message: "Deleting this service removes its managed firewall rules immediately. Live traffic may change as soon as deletion succeeds; this does not wait for a later synchronization.",
      confirmLabel: "Delete",
      destructive: true,
      run: async () => { await dcstClient.deleteService(item.id); await refresh(); success("Communication service deleted"); },
    });
  }

  function confirmFirewallSync() {
    setConfirm({
      title: "Synchronize firewall policies?",
      message: "DCST will apply the current desired state to managed Proxmox Firewall objects. External unmanaged rules will be preserved.",
      confirmLabel: "Synchronize",
      run: async () => {
        setSynchronizing(true);
        try {
          await dcstClient.firewallSync(false);
          await refresh();
          success("Firewall synchronized");
        } finally {
          setSynchronizing(false);
        }
      },
    });
  }

  async function runConfirmation() {
    if (!confirm || confirmBusy) return;
    setConfirmBusy(true);
    try {
      await confirm.run();
      setConfirm(null);
    } catch (error) {
      notifyError(error);
    } finally {
      setConfirmBusy(false);
    }
  }

  async function synchronizeInventory() {
    try {
      await dcstClient.syncTags(false);
      await refresh();
      success("DCST inventory synchronized");
    } catch (error) {
      notifyError(error);
    }
  }

  function openCreateIPSet() {
    setIPSetEdit("");
    setIPSetDraft(blankIPSet);
    setIPSetDrawerOpen(true);
  }

  function editIPSet(item: DcstIPSet) {
    setIPSetEdit(item.id);
    setIPSetDraft({ name: item.name, description: item.description, entries: item.entries.map((entry) => entry.address).join("\n") });
    setIPSetDrawerOpen(true);
  }

  async function saveIPSet() {
    setIPSetSaving(true);
    try {
      const entries = ipsetDraft.entries.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean);
      await dcstClient.saveIPSet({ name: ipsetDraft.name, description: ipsetDraft.description, entries }, ipsetEdit);
      success(ipsetEdit ? "IPSet updated" : "IPSet created");
      setIPSetDrawerOpen(false);
      setIPSetEdit("");
      setIPSetDraft(blankIPSet);
      await refresh();
    } catch (error) {
      notifyError(error);
    } finally {
      setIPSetSaving(false);
    }
  }

  function openCreatePort() {
    setPortEdit("");
    setPortDraft(blankPort);
    setPortDrawerOpen(true);
  }

  function editPort(port: DcstPort) {
    setPortEdit(port.id);
    setPortDraft({ name: port.name, protocol: port.protocol, port_from: port.port_from ?? null, port_to: port.port_to ?? null, description: port.description });
    setPortDrawerOpen(true);
  }

  async function savePort() {
    setPortSaving(true);
    try {
      await dcstClient.savePort(portDraft, portEdit);
      success(portEdit ? "Port object updated" : "Port object created");
      setPortDrawerOpen(false);
      setPortEdit("");
      setPortDraft(blankPort);
      await refresh();
    } catch (error) {
      notifyError(error);
    } finally {
      setPortSaving(false);
    }
  }

  const portUsage = useMemo(() => {
    const counts = new Map<string, number>();
    services.forEach((service) => service.port_ids.forEach((portId) => counts.set(portId, (counts.get(portId) || 0) + 1)));
    return counts;
  }, [services]);

  const normalizedLogs = useMemo(() => logs.map(normalizeFirewallLog), [logs]);
  const filteredLogs = useMemo(() => {
    const now = logSnapshotTime;
    const rangeMs = logRange === "15m" ? 15 * 60_000 : logRange === "1h" ? 60 * 60_000 : logRange === "24h" ? 24 * 60 * 60_000 : 0;
    return normalizedLogs.filter((row) => {
      const raw = String(row.dcst_raw || JSON.stringify(row)).toLowerCase();
      const rowNode = String(row.node || "").toLowerCase();
      const rowDirection = String(row.dcst_direction || "").toUpperCase();
      const rowAction = String(row.dcst_action || "").toUpperCase();
      const rowSource = String(row.dcst_source || "").toLowerCase();
      const rowDestination = String(row.dcst_destination || "").toLowerCase();
      const timestamp = syncTimestamp({ time: row.dcst_time });
      return (!logSearch || raw.includes(logSearch.toLowerCase()))
        && (!logNode || rowNode === logNode.toLowerCase())
        && (!logDirection || rowDirection === logDirection)
        && (!logAction || rowAction === logAction)
        && (!logSource || rowSource.includes(logSource.toLowerCase()))
        && (!logDestination || rowDestination.includes(logDestination.toLowerCase()))
        && (!rangeMs || !timestamp || now - timestamp <= rangeMs);
    });
  }, [normalizedLogs, logSearch, logNode, logDirection, logAction, logSource, logDestination, logRange, logSnapshotTime]);

  const logNodes = useMemo(() => [...new Set(normalizedLogs.map((row) => String(row.node || "")).filter(Boolean))].sort(), [normalizedLogs]);

  return <section className="system-app module-app dcst-app">
    <DcstHeader
      managedObjectCount={managedObjectCount}
      lastSyncLabel={lastSyncLabel}
      inventorySynchronized={inventoryReady}
      refreshing={refreshing}
      synchronizing={synchronizing}
      canSync={can("dcst.sync")}
      onRefresh={() => void refresh()}
      onSynchronize={confirmFirewallSync}
    />

    <DcstTabs
      active={tab}
      counts={{ services: services.length, tags: tags.length, ipsets: ipsets.length, ports: ports.length }}
      onChange={(nextTab) => {
        setTab(nextTab);
        if (nextTab === "utilities") void loadUtilities();
      }}
    />

    {tab === "overview" && <DcstOverview overview={overview} services={services} tags={tags} ports={ports} ipsetCount={ipsets.length} />}

    {tab === "services" && <div className="module-content dcst-section">
      <div className="dcst-section-heading">
        <div><h3>Communication Services</h3><p>Control communication between security objects.</p></div>
        {can("dcst.manage_services") && <button className="button-primary" onClick={openCreateService}><Plus /> New Service</button>}
      </div>

      <div className="dcst-policy-toolbar">
        <label className="dcst-search-control"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search services..." aria-label="Search communication services" /></label>
        <label><span>Direction</span><select value={direction} onChange={(event) => setDirection(event.target.value)}><option value="">All</option><option value="IN">IN</option><option value="OUT">OUT</option></select></label>
        <label><span>Action</span><select value={action} onChange={(event) => setAction(event.target.value)}><option value="">All</option><option value="ACCEPT">ACCEPT</option><option value="DROP">DROP</option><option value="REJECT">REJECT</option></select></label>
        <label><span>State</span><select value={state} onChange={(event) => setState(event.target.value)}><option value="">All</option><option value="ACTIVE">ACTIVE</option><option value="BLOCKED">BLOCKED</option><option value="DISABLED">DISABLED</option><option value="PENDING">PENDING</option><option value="ERROR">ERROR</option></select></label>
      </div>

      {!!selected.size && <div className="dcst-bulk-toolbar" role="toolbar" aria-label="Bulk service actions">
        <strong>{selected.size} service{selected.size === 1 ? "" : "s"} selected</strong>
        <div>
          {can("dcst.manage_services") && <><button onClick={() => void bulk("enable")}>Enable</button><button onClick={() => void bulk("disable")}>Disable</button></>}
          {can("dcst.block_traffic") && <><button onClick={confirmBulkBlock}>Block</button><button onClick={() => void bulk("unblock")}>Unblock</button></>}
          {can("dcst.sync") && <button onClick={() => void bulk("sync")}><RefreshCw /> Synchronize</button>}
          <button onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      </div>}

      <DcstServiceTable
        services={visibleServices}
        ports={ports}
        tags={tags}
        ipsets={ipsets}
        selected={selected}
        loading={loading}
        inventoryReady={inventoryReady}
        hasAnyServices={services.length > 0}
        canManage={can("dcst.manage_services")}
        canBlock={can("dcst.block_traffic")}
        canSync={can("dcst.sync")}
        canInventorySync={can("dcst.manage_tags")}
        onToggle={(id, checked) => setSelected((current) => { const next = new Set(current); if (checked) next.add(id); else next.delete(id); return next; })}
        onToggleAll={(checked) => setSelected(checked ? new Set(visibleServices.map((item) => item.id)) : new Set())}
        onView={viewService}
        onEdit={editService}
        onDuplicate={(item) => void dcstClient.cloneService(item.id).then(() => refresh()).then(() => success("Service duplicated")).catch(notifyError)}
        onAction={(item, operation) => void serviceAction(item, operation)}
        onSynchronize={(item) => void dcstClient.syncService(item.id).then(() => refresh()).then(() => success(`${item.name} synchronized`)).catch(notifyError)}
        onDelete={confirmDeleteService}
        onCreate={openCreateService}
        onSynchronizeInventory={() => void synchronizeInventory()}
      />
    </div>}

    {tab === "tags" && <div className="module-content dcst-section">
      <div className="dcst-section-heading">
        <div><h3>Tags</h3><p>Inventory-backed APMID.ENV security groups discovered from managed virtual machines.</p></div>
        {can("dcst.manage_tags") && <button onClick={() => void synchronizeInventory()} disabled={refreshing}><RefreshCw className={refreshing ? "spin" : ""} /> Synchronize inventory</button>}
      </div>
      {!loading && !tags.length ? <DcstEmptyState title="No network objects discovered" description="Synchronize DCST inventory to import APMID.ENV groups from managed virtual machines." actionLabel={can("dcst.manage_tags") ? "Synchronize inventory" : undefined} onAction={can("dcst.manage_tags") ? () => void synchronizeInventory() : undefined} /> : <div className="table-scroll dcst-object-table">
        <table><thead><tr><th>Tag</th><th>APMID</th><th>Environment</th><th>VMs</th><th>IP addresses</th><th>Sync state</th><th>Actions</th></tr></thead>
          <tbody>{tags.map((tag) => <tr key={tag.id}>
            <td><span className="dcst-tag-badge">{tag.name}</span></td><td>{tag.apmid}</td><td>{tag.environment}</td><td>{tag.vm_count} VMs</td>
            <td className="dcst-address-cell">{tag.addresses.slice(0, 2).map((address) => <code key={address}>{address}</code>)}{tag.addresses.length > 2 && <small>+{tag.addresses.length - 2}</small>}</td>
            <td><DcstStatusBadge status={tag.sync_status || "SYNCED"} /></td><td><button className="link-button" onClick={() => setTagDetails(tag)}>View</button></td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>}

    {tab === "ipsets" && <div className="module-content dcst-section">
      <div className="dcst-section-heading"><div><h3>IP Sets</h3><p>Reusable network address objects referenced by communication policies.</p></div>{can("dcst.manage_ipsets") && <button className="button-primary" onClick={openCreateIPSet}><Plus /> Create IP Set</button>}</div>
      {!loading && !ipsets.length ? <DcstEmptyState title="No IP sets" description="Create a reusable address object for security policies." actionLabel={can("dcst.manage_ipsets") ? "+ Create IP Set" : undefined} onAction={can("dcst.manage_ipsets") ? openCreateIPSet : undefined} /> : <div className="table-scroll dcst-object-table">
        <table><thead><tr><th>Name</th><th>Description</th><th>Entries</th><th>Used by</th><th>State</th><th>Actions</th></tr></thead>
          <tbody>{ipsets.map((item) => <tr key={item.id}>
            <td><button className="dcst-service-name" onClick={() => setIPSetDetails(item)}>{item.name}</button><small className="dcst-system-label">{item.type.toUpperCase()}</small></td>
            <td>{item.description || "—"}</td><td>{item.entries.length}</td><td>{item.dependencies?.length || 0} policies</td><td><DcstStatusBadge status={item.sync_status || "SYNCED"} /></td>
            <td><div className="dcst-inline-actions">{can("dcst.sync") && <button aria-label={`Synchronize ${item.name}`} onClick={() => void dcstClient.syncIPSet(item.id).then(() => refresh()).catch(notifyError)}><RefreshCw /></button>}{can("dcst.manage_ipsets") && item.type === "manual" && <><button aria-label={`Edit ${item.name}`} onClick={() => editIPSet(item)}><Pencil /></button><button className="danger" aria-label={`Delete ${item.name}`} onClick={() => setConfirm({ title: "Delete IP Set?", subject: item.name, message: "This object will be removed if it is not referenced by communication services.", confirmLabel: "Delete", destructive: true, run: async () => { await dcstClient.deleteIPSet(item.id); await refresh(); } })}><Trash2 /></button></>}</div></td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>}

    {tab === "ports" && <div className="module-content dcst-section">
      <div className="dcst-section-heading"><div><h3>Port Objects</h3><p>Reusable protocol and port definitions for communication services.</p></div>{can("dcst.manage_ports") && <button className="button-primary" onClick={openCreatePort}><Plus /> Create Port Object</button>}</div>
      {!loading && !ports.length ? <DcstEmptyState title="No port objects" description="Create reusable transport objects such as HTTPS, PostgreSQL or DNS." actionLabel={can("dcst.manage_ports") ? "+ Create Port Object" : undefined} onAction={can("dcst.manage_ports") ? openCreatePort : undefined} /> : <div className="table-scroll dcst-object-table">
        <table><thead><tr><th>Name</th><th>Protocol</th><th>Port / Range</th><th>Used by</th><th>Description</th><th>Actions</th></tr></thead>
          <tbody>{ports.map((port) => <tr key={port.id}>
            <td><button className="dcst-service-name" onClick={() => setPortDetails(port)}>{port.name}</button></td><td><span className="dcst-protocol-badge">{port.protocol.toUpperCase()}</span></td>
            <td><code>{port.port_from ? `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `–${port.port_to}` : ""}` : "—"}</code></td><td>{portUsage.get(port.id) || 0} policies</td><td>{port.description || "—"}</td>
            <td>{can("dcst.manage_ports") && <div className="dcst-inline-actions"><button aria-label={`Edit ${port.name}`} onClick={() => editPort(port)}><Pencil /></button><button className="danger" aria-label={`Delete ${port.name}`} onClick={() => setConfirm({ title: "Delete port object?", subject: port.name, message: "Services using this object will prevent deletion.", confirmLabel: "Delete", destructive: true, run: async () => { await dcstClient.deletePort(port.id); await refresh(); } })}><Trash2 /></button></div>}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>}

    {tab === "utilities" && <div className="module-content dcst-section">
      <div className="dcst-section-heading"><div><h3>Utilities</h3><p>Diagnostics, firewall logs, synchronization and connection status.</p></div><button onClick={() => void loadUtilities()} disabled={utilitiesLoading}><RefreshCw className={utilitiesLoading ? "spin" : ""} /> Refresh</button></div>
      <div className="dcst-utility-grid">
        <article className="data-card dcst-utility-card"><header><Globe /><div><strong>Connection status</strong><small>Proxmox Firewall provider</small></div></header><dl>{recordSummary(asRecord(overview.firewall)).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{String(value)}</dd></div>)}</dl>{can("dcst.sync") && <button onClick={() => void dcstClient.test().then((result) => { setDiagnostics(result); success("Connection test completed"); }).catch(notifyError)}>Test connection</button>}</article>
        <article className="data-card dcst-utility-card"><header><RefreshCw /><div><strong>Synchronization</strong><small>Desired state and drift control</small></div></header><dl><div><dt>Inventory</dt><dd>{exactTime(overview.last_inventory_sync)}</dd></div><div><dt>Firewall</dt><dd>{exactTime(overview.last_firewall_sync)}</dd></div></dl>{can("dcst.sync") && <div className="dcst-inline-actions"><button onClick={() => void dcstClient.firewallSync(true).then((result) => setDiagnostics(result)).catch(notifyError)}>Dry run</button><button onClick={() => void dcstClient.drift().then((result) => setDiagnostics(result)).catch(notifyError)}>Detect drift</button></div>}</article>
        <article className="data-card dcst-utility-card"><header><Wrench /><div><strong>Diagnostics</strong><small>Current DCST diagnostic output</small></div></header><pre>{JSON.stringify(diagnostics, null, 2)}</pre></article>
        <article className="data-card dcst-utility-card"><header><Shield /><div><strong>Firewall state</strong><small>Managed control-plane summary</small></div></header><pre>{JSON.stringify(overview.firewall || {}, null, 2)}</pre></article>
      </div>

      {can("dcst.view_logs") && <article className="data-card dcst-firewall-log-card">
        <header><Activity /><div><strong>Firewall Logs</strong><small>Filter and inspect managed firewall events</small></div></header>
        <div className="dcst-log-filters">
          <label className="dcst-search-control"><Search /><input value={logSearch} onChange={(event) => setLogSearch(event.target.value)} placeholder="Search logs..." aria-label="Search firewall logs" /></label>
          <label><span>Node</span><select value={logNode} onChange={(event) => setLogNode(event.target.value)}><option value="">All</option>{logNodes.map((node) => <option key={node}>{node}</option>)}</select></label>
          <label><span>Direction</span><select value={logDirection} onChange={(event) => setLogDirection(event.target.value)}><option value="">All</option><option>IN</option><option>OUT</option></select></label>
          <label><span>Action</span><select value={logAction} onChange={(event) => setLogAction(event.target.value)}><option value="">All</option><option>ACCEPT</option><option>DROP</option><option>REJECT</option></select></label>
          <label><span>Source</span><input value={logSource} onChange={(event) => setLogSource(event.target.value)} placeholder="IP / object" /></label>
          <label><span>Destination</span><input value={logDestination} onChange={(event) => setLogDestination(event.target.value)} placeholder="IP / object" /></label>
          <label><span>Time range</span><select value={logRange} onChange={(event) => { setLogRange(event.target.value); setLogSnapshotTime(Date.now()); }}><option value="">All</option><option value="15m">15 minutes</option><option value="1h">1 hour</option><option value="24h">24 hours</option></select></label>
        </div>
        <div className="table-scroll dcst-log-table"><table><thead><tr><th>Node</th><th>Time</th><th>Direction</th><th>Action</th><th>Source</th><th>Destination</th><th>Raw message</th></tr></thead>
          <tbody>{filteredLogs.map((row, index) => <tr key={String(row.id || index)}><td>{String(row.node || "—")}</td><td><code>{String(row.dcst_time || "—")}</code></td><td>{String(row.dcst_direction || "—")}</td><td>{String(row.dcst_action || "—")}</td><td><code>{String(row.dcst_source || "—")}</code></td><td><code>{String(row.dcst_destination || "—")}</code></td><td><code>{String(row.dcst_raw || JSON.stringify(row))}</code></td></tr>)}</tbody>
        </table></div>
        {!utilitiesLoading && !filteredLogs.length && <div className="dcst-inline-empty">No firewall logs match the current filters.</div>}
      </article>}
    </div>}

    <DcstServiceDrawer open={serviceDrawerOpen} editId={serviceEdit} draft={serviceDraft} tags={tags} ipsets={ipsets} ports={ports} errors={serviceErrors} saving={serviceSaving} onDraftChange={setServiceDraft} onClose={closeServiceDrawer} onSubmit={() => void saveService()} />
    <DcstServiceDetails service={detailService} preview={detailPreview} ports={ports} tags={tags} ipsets={ipsets} lastSyncLabel={lastSyncExact} onClose={() => { previewRequest.current += 1; setDetailService(null); setDetailPreview(null); }} />
    <DcstIPSetDrawer open={ipsetDrawerOpen} editId={ipsetEdit} draft={ipsetDraft} saving={ipsetSaving} onDraftChange={setIPSetDraft} onClose={() => { if (!ipsetSaving) setIPSetDrawerOpen(false); }} onSubmit={() => void saveIPSet()} />
    <DcstPortDrawer open={portDrawerOpen} editId={portEdit} draft={portDraft} saving={portSaving} onDraftChange={setPortDraft} onClose={() => { if (!portSaving) setPortDrawerOpen(false); }} onSubmit={() => void savePort()} />

    <DcstInfoDrawer title={tagDetails?.name || "Tag"} description="APMID.ENV inventory security object" open={Boolean(tagDetails)} onClose={() => setTagDetails(null)}>
      {tagDetails && <><section className="dcst-details-summary"><div><span>APMID</span><strong>{tagDetails.apmid}</strong></div><div><span>Environment</span><strong>{tagDetails.environment}</strong></div><div><span>Virtual machines</span><strong>{tagDetails.vm_count}</strong></div><div><span>Sync state</span><DcstStatusBadge status={tagDetails.sync_status || "SYNCED"} /></div></section><section className="dcst-form-section"><header><span>01</span><div><strong>Addresses</strong><small>Resolved VM management addresses</small></div></header><div className="dcst-address-list">{tagDetails.addresses.map((address) => <code key={address}>{address}</code>)}</div></section><section className="dcst-form-section"><header><span>02</span><div><strong>Virtual machines</strong><small>Inventory members</small></div></header><div className="table-scroll"><table><thead><tr><th>VM</th><th>IP</th><th>Node</th></tr></thead><tbody>{tagDetails.hosts.map((host) => <tr key={host.id}><td>{host.name}</td><td><code>{host.address}</code></td><td>{host.node || "—"}</td></tr>)}</tbody></table></div></section></>}
    </DcstInfoDrawer>

    <DcstInfoDrawer title={ipsetDetails?.name || "IP Set"} description={ipsetDetails?.description || "Reusable network address object"} open={Boolean(ipsetDetails)} onClose={() => setIPSetDetails(null)}>
      {ipsetDetails && <><section className="dcst-details-summary"><div><span>Type</span><strong>{ipsetDetails.type.toUpperCase()}</strong></div><div><span>Entries</span><strong>{ipsetDetails.entries.length}</strong></div><div><span>Used by</span><strong>{ipsetDetails.dependencies?.length || 0}</strong></div><div><span>State</span><DcstStatusBadge status={ipsetDetails.sync_status || "SYNCED"} /></div></section><section className="dcst-form-section"><header><span>01</span><div><strong>Entries</strong><small>Addresses and CIDR ranges</small></div></header><div className="dcst-address-list">{ipsetDetails.entries.map((entry) => <code key={entry.id}>{entry.address}</code>)}</div></section>{ipsetDetails.dependencies?.length ? <section className="dcst-form-section"><header><span>02</span><div><strong>Used by</strong><small>Communication services referencing this object</small></div></header><div className="dcst-dependency-list">{ipsetDetails.dependencies.map((dependency) => <span key={dependency.id}>{dependency.name}</span>)}</div></section> : null}</>}
    </DcstInfoDrawer>

    <DcstInfoDrawer title={portDetails?.name || "Port Object"} description={portDetails?.description || "Reusable transport object"} open={Boolean(portDetails)} onClose={() => setPortDetails(null)}>
      {portDetails && <><section className="dcst-details-summary"><div><span>Protocol</span><strong>{portDetails.protocol.toUpperCase()}</strong></div><div><span>Port / Range</span><code>{portDetails.port_from ? `${portDetails.port_from}${portDetails.port_to && portDetails.port_to !== portDetails.port_from ? `–${portDetails.port_to}` : ""}` : "—"}</code></div><div><span>Used by</span><strong>{portUsage.get(portDetails.id) || 0} policies</strong></div></section>{portDetails.dependencies?.length ? <section className="dcst-form-section"><header><span>01</span><div><strong>Used by</strong><small>Communication services referencing this object</small></div></header><div className="dcst-dependency-list">{portDetails.dependencies.map((dependency) => <span key={dependency.id}>{dependency.name}</span>)}</div></section> : null}</>}
    </DcstInfoDrawer>

    <DcstConfirmDialog action={confirm} busy={confirmBusy} onCancel={() => { if (!confirmBusy) setConfirm(null); }} onConfirm={() => void runConfirmation()} />
  </section>;
}
