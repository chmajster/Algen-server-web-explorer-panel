import { Activity, Ban, Boxes, CheckCircle2, Copy, Network, Play, Plus, RefreshCw, Search, Shield, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ToastFn, Translate } from "../../app/types";
import { dcstClient, type DcstIPSet, type DcstPort, type DcstService, type DcstServiceInput, type DcstTag } from "../../modules/dcst/api/client";

type Tab = "overview" | "services" | "tags" | "ipsets" | "ports" | "utilities";
type EndpointSide = "source" | "destination";
type ConfirmAction = { title: string; message: string; run: () => Promise<void> } | null;

const blankService: DcstServiceInput = {
  name: "", description: "", direction: "OUT", action: "ACCEPT", source_type: "tag", source_value: "",
  destination_type: "tag", destination_value: "", port_ids: [], enabled: true, logging: false, comment: "",
};

export function DcstApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);
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
  const [portDraft, setPortDraft] = useState({ name: "", protocol: "tcp" as DcstPort["protocol"], port_from: 443 as number | null, port_to: 443 as number | null, description: "" });
  const [portEdit, setPortEdit] = useState("");
  const [ipsetDraft, setIPSetDraft] = useState({ name: "", description: "", entries: "" });
  const [ipsetEdit, setIPSetEdit] = useState("");
  const [confirm, setConfirm] = useState<ConfirmAction>(null);
  const [details, setDetails] = useState<Record<string, unknown> | null>(null);

  const can = (permission: string) => permissions.includes(permission);
  const notifyError = useCallback((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"), [t, toast]);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextOverview, nextServices, nextTags, nextIPSets, nextPorts] = await Promise.all([dcstClient.overview(), dcstClient.services(), dcstClient.tags(), dcstClient.ipsets(), dcstClient.ports()]);
      setOverview(nextOverview as unknown as Record<string, unknown>);
      setServices(nextServices); setTags(nextTags); setIPSets(nextIPSets); setPorts(nextPorts);
    } catch (error) { notifyError(error); }
    finally { setLoading(false); }
  }, [notifyError]);

  useEffect(() => { void refresh(); }, [refresh]);

  const visibleServices = useMemo(() => services.filter((item) => {
    const text = `${item.name} ${item.source_value} ${item.destination_value} ${item.direction} ${item.action}`.toLowerCase();
    return (!search || text.includes(search.toLowerCase())) && (!direction || item.direction === direction) && (!action || item.action === action) && (!state || item.state === state);
  }), [services, search, direction, action, state]);

  const endpointOptions = useMemo(() => [
    ...tags.map((item) => ({ type: "tag", value: item.name, label: `${item.name} · ${item.vm_count} VM` })),
    ...ipsets.map((item) => ({ type: "ipset", value: item.id, label: `${item.name} · IPSet` })),
  ], [tags, ipsets]);

  function success(message: string) { toast(message, "ok", "admin"); }
  function setEndpointType(side: EndpointSide, value: DcstServiceInput["source_type"]) {
    if (side === "source") setServiceDraft((old) => ({ ...old, source_type: value, source_value: "" }));
    else setServiceDraft((old) => ({ ...old, destination_type: value, destination_value: "" }));
  }
  function setEndpointValue(side: EndpointSide, value: string) {
    if (side === "source") setServiceDraft((old) => ({ ...old, source_value: value }));
    else setServiceDraft((old) => ({ ...old, destination_value: value }));
  }
  function toggleSelection(id: string, checked: boolean) {
    setSelected((old) => {
      const next = new Set(old);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }
  async function saveService() {
    try {
      await dcstClient.saveService(serviceDraft, serviceEdit);
      success(serviceEdit ? "Service updated" : "Service created");
      setServiceDraft(blankService); setServiceEdit(""); await refresh();
    } catch (error) { notifyError(error); }
  }
  function editService(item: DcstService) {
    setServiceEdit(item.id);
    setServiceDraft({ name: item.name, description: item.description, direction: item.direction, action: item.action, source_type: item.source_type, source_value: item.source_value, destination_type: item.destination_type, destination_value: item.destination_value, port_ids: item.port_ids, enabled: item.enabled, logging: item.logging, comment: item.comment });
  }
  async function savePort() {
    try {
      await dcstClient.savePort(portDraft, portEdit); success(portEdit ? "Port updated" : "Port created");
      setPortDraft({ name: "", protocol: "tcp", port_from: 443, port_to: 443, description: "" }); setPortEdit(""); await refresh();
    } catch (error) { notifyError(error); }
  }
  async function saveIPSet() {
    try {
      const entries = ipsetDraft.entries.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean);
      await dcstClient.saveIPSet({ name: ipsetDraft.name, description: ipsetDraft.description, entries }, ipsetEdit);
      success(ipsetEdit ? "IPSet updated" : "IPSet created"); setIPSetDraft({ name: "", description: "", entries: "" }); setIPSetEdit(""); await refresh();
    } catch (error) { notifyError(error); }
  }
  async function serviceAction(id: string, operation: "block" | "unblock" | "enable" | "disable") {
    try { await dcstClient.serviceAction(id, operation); success(`Service ${operation} completed`); await refresh(); }
    catch (error) { notifyError(error); }
  }
  async function bulk(operation: "block" | "unblock" | "enable" | "disable" | "sync") {
    if (!selected.size) return;
    try { await dcstClient.bulk(operation, [...selected]); success(`Bulk ${operation} completed`); setSelected(new Set()); await refresh(); }
    catch (error) { notifyError(error); }
  }
  async function loadUtilities() {
    setLoading(true);
    try { const [nextLogs, nextDiagnostics] = await Promise.all([dcstClient.firewallLogs(), dcstClient.diagnostics()]); setLogs(nextLogs); setDiagnostics(nextDiagnostics); }
    catch (error) { notifyError(error); }
    finally { setLoading(false); }
  }

  const endpointEditor = (side: EndpointSide) => {
    const kind = side === "source" ? serviceDraft.source_type : serviceDraft.destination_type;
    const value = side === "source" ? serviceDraft.source_value : serviceDraft.destination_value;
    return <div className="settings-card-stack"><label>{side === "source" ? "Source type" : "Destination type"}<select value={kind} onChange={(event) => setEndpointType(side, event.target.value as DcstServiceInput["source_type"])}><option value="tag">APMID.ENV TAG</option><option value="apmid">APMID.*</option><option value="ipset">IPSet</option><option value="ip">IP address</option><option value="cidr">CIDR</option><option value="any">Any</option></select></label>{kind !== "any" && <label>{side === "source" ? "Source" : "Destination"}{kind === "tag" || kind === "ipset" ? <select value={value} onChange={(event) => setEndpointValue(side, event.target.value)}><option value="">Select...</option>{endpointOptions.filter((option) => option.type === kind).map((option) => <option key={`${option.type}:${option.value}`} value={option.value}>{option.label}</option>)}</select> : kind === "apmid" ? <select value={value} onChange={(event) => setEndpointValue(side, event.target.value)}><option value="">Select...</option>{[...new Set(tags.map((tag) => tag.apmid))].map((apmid) => <option key={apmid}>{apmid}</option>)}</select> : <input value={value} onChange={(event) => setEndpointValue(side, event.target.value)} />}</label>}</div>;
  };

  const tabs: Array<[Tab, string]> = [["overview", "Overview"], ["services", "Services"], ["tags", "TAGS"], ["ipsets", "IPSets"], ["ports", "Ports"], ["utilities", "Utilities"]];
  const recent = (overview.recent_changes as Array<Record<string, unknown>>) || [];

  return <section className="system-app module-app dcst-app">
    <header className="feature-header"><div><h2><Shield /> DATA Communication & Segmentation Tool - DCST</h2><p>Logical network communication and Proxmox Firewall segmentation.</p></div><div className="header-actions"><button onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} /> Refresh</button>{can("dcst.sync") && <button className="button-primary" onClick={() => setConfirm({ title: "Synchronize firewall", message: "Apply the complete DCST desired state to managed Proxmox Firewall objects? External rules will be preserved.", run: async () => { await dcstClient.firewallSync(false); await refresh(); success("Firewall synchronized"); } })}><Play /> Synchronize</button>}</div></header>
    <nav className="module-tabs" aria-label="DCST sections">{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => { setTab(id); if (id === "utilities") void loadUtilities(); }}>{label}</button>)}</nav>

    {tab === "overview" && <div className="module-content"><div className="card-grid">{[["Services", overview.services], ["Active", overview.active_services], ["Blocked", overview.blocked_services], ["Ports", overview.ports], ["IPSets", overview.ipsets], ["TAGS / APMID.ENV", overview.tags], ["Firewall rules", overview.firewall_rules]].map(([label, value]) => <article className="data-card" key={String(label)}><strong>{String(label)}</strong><span className="metric-value">{String(value ?? 0)}</span></article>)}</div><article className="data-card"><header><Activity /><strong>Recent firewall changes</strong></header><div className="table-scroll"><table><thead><tr><th>Timestamp</th><th>User</th><th>Operation</th><th>Object</th><th>Status</th></tr></thead><tbody>{recent.map((row, index) => <tr key={String(row.id || index)}><td>{row.timestamp ? new Date(Number(row.timestamp) * 1000).toLocaleString() : "—"}</td><td>{String(row.user || "")}</td><td>{String(row.operation || "")}</td><td>{String(row.object_type || "")} / {String(row.object_id || "")}</td><td>{String(row.status || "")}</td></tr>)}</tbody></table></div></article></div>}

    {tab === "services" && <div className="module-content"><div className="module-section-toolbar"><div className="search-box"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search Services, Source, Destination..." /></div><select aria-label="Direction" value={direction} onChange={(event) => setDirection(event.target.value)}><option value="">All directions</option><option>IN</option><option>OUT</option></select><select aria-label="Action" value={action} onChange={(event) => setAction(event.target.value)}><option value="">All actions</option><option>ACCEPT</option><option>DROP</option><option>REJECT</option></select><select aria-label="State" value={state} onChange={(event) => setState(event.target.value)}><option value="">All states</option><option>ACTIVE</option><option>BLOCKED</option><option>DISABLED</option><option>PENDING</option><option>ERROR</option></select></div>
      {!!selected.size && <div className="data-actions"><strong>{selected.size} selected</strong>{can("dcst.manage_services") && <><button onClick={() => void bulk("enable")}>Enable</button><button onClick={() => void bulk("disable")}>Disable</button></>}{can("dcst.block_traffic") && <><button className="danger" onClick={() => setConfirm({ title: "Block traffic", message: `Block ${selected.size} selected Services?`, run: async () => { await bulk("block"); } })}><Ban /> Block</button><button onClick={() => void bulk("unblock")}>Unblock</button></>}{can("dcst.sync") && <button onClick={() => void bulk("sync")}><RefreshCw /> Sync</button>}</div>}
      <div className="table-scroll"><table><thead><tr><th><input type="checkbox" aria-label="Select all Services" checked={visibleServices.length > 0 && visibleServices.every((item) => selected.has(item.id))} onChange={(event) => setSelected(event.target.checked ? new Set(visibleServices.map((item) => item.id)) : new Set())} /></th><th>Name</th><th>Source</th><th>Destination</th><th>Ports</th><th>Direction</th><th>Action</th><th>State</th><th>Actions</th></tr></thead><tbody>{visibleServices.map((item) => <tr key={item.id}><td><input type="checkbox" aria-label={`Select ${item.name}`} checked={selected.has(item.id)} onChange={(event) => toggleSelection(item.id, event.target.checked)} /></td><td><button className="link-button" onClick={() => void dcstClient.previewService(item.id).then(setDetails).catch(notifyError)}>{item.name}</button>{item.system_service && <small> system</small>}</td><td>{item.source_value || "Any"}</td><td>{item.destination_value || "Any"}</td><td>{item.port_ids.map((id) => ports.find((port) => port.id === id)?.name || id).join(", ") || "Any"}</td><td>{item.direction}</td><td>{item.blocked ? "DROP" : item.action}</td><td><span className={`status-badge ${item.state.toLowerCase()}`}>{item.state}</span></td><td><div className="data-actions">{can("dcst.manage_services") && !item.system_service && <button onClick={() => editService(item)}>Edit</button>}{can("dcst.block_traffic") && <button onClick={() => void serviceAction(item.id, item.blocked ? "unblock" : "block")}>{item.blocked ? "Unblock" : "Block"}</button>}{can("dcst.manage_services") && !item.system_service && <button title="Clone" onClick={() => void dcstClient.cloneService(item.id).then(refresh).catch(notifyError)}><Copy /></button>}{can("dcst.sync") && <button title="Synchronize" onClick={() => void dcstClient.syncService(item.id).then(refresh).catch(notifyError)}><RefreshCw /></button>}{can("dcst.manage_services") && !item.system_service && <button className="danger" title="Delete" onClick={() => setConfirm({ title: "Delete Service", message: `Delete ${item.name} and its managed Proxmox rules?`, run: async () => { await dcstClient.deleteService(item.id); await refresh(); } })}><Trash2 /></button>}</div></td></tr>)}</tbody></table></div>
      {can("dcst.manage_services") && <article className="data-card"><header><Plus /><strong>{serviceEdit ? "Edit Service" : "Create Service"}</strong></header><div className="form-grid"><label>Name<input value={serviceDraft.name} onChange={(event) => setServiceDraft({ ...serviceDraft, name: event.target.value })} /></label><label>Direction<select value={serviceDraft.direction} onChange={(event) => setServiceDraft({ ...serviceDraft, direction: event.target.value as "IN" | "OUT" })}><option value="IN">IN - Incoming traffic</option><option value="OUT">OUT - Outgoing traffic</option></select></label><label>Action<select value={serviceDraft.action} onChange={(event) => setServiceDraft({ ...serviceDraft, action: event.target.value as "ACCEPT" | "DROP" | "REJECT" })}><option>ACCEPT</option><option>DROP</option><option>REJECT</option></select></label><label>Description<input value={serviceDraft.description} onChange={(event) => setServiceDraft({ ...serviceDraft, description: event.target.value })} /></label>{endpointEditor("source")}{endpointEditor("destination")}</div><fieldset><legend>Ports</legend><div className="checkbox-grid">{ports.map((port) => <label key={port.id}><input type="checkbox" checked={serviceDraft.port_ids.includes(port.id)} onChange={(event) => setServiceDraft({ ...serviceDraft, port_ids: event.target.checked ? [...serviceDraft.port_ids, port.id] : serviceDraft.port_ids.filter((id) => id !== port.id) })} />{port.name} / {port.protocol.toUpperCase()} {port.port_from ? `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `-${port.port_to}` : ""}` : ""}</label>)}</div></fieldset><div className="data-actions"><label><input type="checkbox" checked={serviceDraft.enabled} onChange={(event) => setServiceDraft({ ...serviceDraft, enabled: event.target.checked })} /> Enabled</label><label><input type="checkbox" checked={serviceDraft.logging} onChange={(event) => setServiceDraft({ ...serviceDraft, logging: event.target.checked })} /> Logging</label><button className="button-primary" onClick={() => void saveService()}>{serviceEdit ? "Save" : "Create Service"}</button>{serviceEdit && <button onClick={() => { setServiceDraft(blankService); setServiceEdit(""); }}>Cancel</button>}</div></article>}</div>}

    {tab === "tags" && <div className="module-content"><div className="module-section-toolbar"><p>Dynamic groups generated from canonical Hosts Manager inventory. They are read-only in DCST.</p>{can("dcst.manage_tags") && <button onClick={() => void dcstClient.syncTags(false).then(refresh).catch(notifyError)}><RefreshCw /> Synchronize inventory</button>}</div><div className="card-grid">{tags.map((tag) => <article className="data-card" key={tag.id}><header><Network /><strong>{tag.name}</strong><span className="status-badge">{tag.sync_status}</span></header><p>{tag.vm_count} VM(s) · Proxmox IPSet: {tag.provider_name}</p><div className="table-scroll"><table><thead><tr><th>VM</th><th>IP</th><th>Node</th></tr></thead><tbody>{tag.hosts.map((host) => <tr key={host.id}><td>{host.name}</td><td>{host.address}</td><td>{host.node || "—"}</td></tr>)}</tbody></table></div></article>)}</div></div>}

    {tab === "ipsets" && <div className="module-content"><div className="card-grid">{ipsets.map((item) => <article className="data-card" key={item.id}><header><Boxes /><strong>{item.name}</strong><span className="status-badge">{item.type}</span></header><p>{item.description || "—"}</p><code>{item.entries.map((entry) => entry.address).join(" · ") || "Empty"}</code><small>{item.provider_name} · {item.sync_status}</small>{item.dependencies?.length ? <p>Referenced by: {item.dependencies.map((dependency) => dependency.name).join(", ")}</p> : null}<div className="data-actions">{can("dcst.sync") && <button onClick={() => void dcstClient.syncIPSet(item.id).then(refresh).catch(notifyError)}><RefreshCw /> Sync</button>}{can("dcst.manage_ipsets") && item.type === "manual" && <><button onClick={() => { setIPSetEdit(item.id); setIPSetDraft({ name: item.name, description: item.description, entries: item.entries.map((entry) => entry.address).join("\n") }); }}>Edit</button><button className="danger" onClick={() => setConfirm({ title: "Delete IPSet", message: `Delete ${item.name}?`, run: async () => { await dcstClient.deleteIPSet(item.id); await refresh(); } })}><Trash2 /></button></>}</div></article>)}</div>{can("dcst.manage_ipsets") && <article className="data-card"><header><Plus /><strong>{ipsetEdit ? "Edit IPSet" : "Create manual IPSet"}</strong></header><div className="form-grid"><label>Name<input value={ipsetDraft.name} onChange={(event) => setIPSetDraft({ ...ipsetDraft, name: event.target.value })} /></label><label>Description<input value={ipsetDraft.description} onChange={(event) => setIPSetDraft({ ...ipsetDraft, description: event.target.value })} /></label></div><label>Entries (IP/CIDR, one per line)<textarea rows={6} value={ipsetDraft.entries} onChange={(event) => setIPSetDraft({ ...ipsetDraft, entries: event.target.value })} /></label><div className="data-actions"><button className="button-primary" onClick={() => void saveIPSet()}>{ipsetEdit ? "Save" : "Create"}</button>{ipsetEdit && <button onClick={() => { setIPSetEdit(""); setIPSetDraft({ name: "", description: "", entries: "" }); }}>Cancel</button>}</div></article>}</div>}

    {tab === "ports" && <div className="module-content"><div className="card-grid">{ports.map((port) => <article className="data-card" key={port.id}><header><Network /><strong>{port.name}</strong></header><p>{port.protocol.toUpperCase()} {port.port_from ? `${port.port_from}${port.port_to !== port.port_from ? `-${port.port_to}` : ""}` : ""}</p><small>{port.description || "Reusable Port Object"}</small>{port.dependencies?.length ? <p>Used by: {port.dependencies.map((dependency) => dependency.name).join(", ")}</p> : null}{can("dcst.manage_ports") && <div className="data-actions"><button onClick={() => { setPortEdit(port.id); setPortDraft({ name: port.name, protocol: port.protocol, port_from: port.port_from ?? null, port_to: port.port_to ?? null, description: port.description }); }}>Edit</button><button className="danger" onClick={() => setConfirm({ title: "Delete Port", message: `Delete ${port.name}? Services using it will prevent deletion.`, run: async () => { await dcstClient.deletePort(port.id); await refresh(); } })}><Trash2 /></button></div>}</article>)}</div>{can("dcst.manage_ports") && <article className="data-card"><header><Plus /><strong>{portEdit ? "Edit Port" : "Create Port"}</strong></header><div className="form-grid"><label>Name<input value={portDraft.name} onChange={(event) => setPortDraft({ ...portDraft, name: event.target.value })} /></label><label>Protocol<select value={portDraft.protocol} onChange={(event) => { const protocol = event.target.value as DcstPort["protocol"]; setPortDraft({ ...portDraft, protocol, port_from: protocol === "icmp" ? null : portDraft.port_from ?? 443, port_to: protocol === "icmp" ? null : portDraft.port_to ?? 443 }); }}><option value="tcp">TCP</option><option value="udp">UDP</option><option value="tcp+udp">TCP+UDP</option><option value="icmp">ICMP</option></select></label>{portDraft.protocol !== "icmp" && <><label>Port from<input type="number" min={1} max={65535} value={portDraft.port_from ?? ""} onChange={(event) => setPortDraft({ ...portDraft, port_from: Number(event.target.value) })} /></label><label>Port to<input type="number" min={1} max={65535} value={portDraft.port_to ?? ""} onChange={(event) => setPortDraft({ ...portDraft, port_to: Number(event.target.value) })} /></label></>}<label>Description<input value={portDraft.description} onChange={(event) => setPortDraft({ ...portDraft, description: event.target.value })} /></label></div><div className="data-actions"><button className="button-primary" onClick={() => void savePort()}>{portEdit ? "Save" : "Create"}</button>{portEdit && <button onClick={() => setPortEdit("")}>Cancel</button>}</div></article>}</div>}

    {tab === "utilities" && <div className="module-content"><div className="card-grid"><article className="data-card"><header><Shield /><strong>Proxmox Firewall Status</strong></header><pre>{JSON.stringify(overview.firewall || {}, null, 2)}</pre>{can("dcst.sync") && <div className="data-actions"><button onClick={() => void dcstClient.test().then(setDetails).catch(notifyError)}>Test Proxmox Firewall API</button><button onClick={() => void dcstClient.firewallSync(true).then(setDetails).catch(notifyError)}>Dry Run</button><button onClick={() => void dcstClient.drift().then(setDetails).catch(notifyError)}>Detect Drift</button></div>}</article><article className="data-card"><header><Wrench /><strong>Diagnostics</strong></header><pre>{JSON.stringify(diagnostics, null, 2)}</pre></article></div>{can("dcst.view_logs") && <article className="data-card"><header><Activity /><strong>Firewall Logs</strong><button onClick={() => void loadUtilities()}><RefreshCw /> Refresh</button></header><div className="table-scroll"><table><thead><tr><th>Node</th><th>Time</th><th>Message / raw log</th></tr></thead><tbody>{logs.map((row, index) => <tr key={index}><td>{String(row.node || "")}</td><td>{String(row.time || row.timestamp || "")}</td><td><code>{String(row.t || row.msg || row.message || row.raw || JSON.stringify(row))}</code></td></tr>)}</tbody></table></div></article>}</div>}

    {!loading && ((tab === "services" && !services.length) || (tab === "tags" && !tags.length)) && <div className="empty-state">No DCST objects yet. Synchronize the shared inventory to create APMID.ENV groups.</div>}
    {loading && <div className="loading-state" role="status">Loading DCST...</div>}
    {confirm && <div className="dialog-backdrop" role="presentation"><div className="dialog-card" role="dialog" aria-modal="true" aria-labelledby="dcst-confirm-title"><h3 id="dcst-confirm-title">{confirm.title}</h3><p>{confirm.message}</p><div className="dialog-actions"><button onClick={() => setConfirm(null)}>Cancel</button><button className="button-primary" onClick={() => { const run = confirm.run; setConfirm(null); void run().catch(notifyError); }}><CheckCircle2 /> Confirm</button></div></div></div>}
    {details && <div className="dialog-backdrop" role="presentation"><div className="dialog-card dialog-wide" role="dialog" aria-modal="true" aria-label="DCST details"><header><strong>DCST details / preview</strong><button onClick={() => setDetails(null)}>Close</button></header><pre>{JSON.stringify(details, null, 2)}</pre></div></div>}
  </section>;
}