import { Activity, Globe, RefreshCw, Shield, Wrench } from "lucide-react";
import { Card, PageSection, SearchInput, Select } from "../../../components/ui";
import { asRecord, exactTime, recordSummary, type FirewallLogFilters } from "../domain/firewallLog";

export function UtilitiesPage({ overview, loading, diagnostics, filters, nodes, logs, canSync, canViewLogs, onFilter, onRefresh, onTest, onDryRun, onDrift }: {
  overview: Record<string, unknown>; loading: boolean; diagnostics: Record<string, unknown>; filters: FirewallLogFilters; nodes: string[]; logs: Array<Record<string, unknown>>; canSync: boolean; canViewLogs: boolean;
  onFilter: <K extends keyof FirewallLogFilters>(key: K, value: FirewallLogFilters[K]) => void; onRefresh: () => void; onTest: () => void; onDryRun: () => void; onDrift: () => void;
}) {
  return <PageSection className="module-content dcst-section" title="Utilities" description="Diagnostics, firewall logs, synchronization and connection status." actions={<button onClick={onRefresh} disabled={loading}><RefreshCw className={loading ? "spin" : ""} /> Refresh</button>}>
    <div className="dcst-utility-grid">
      <Card className="data-card dcst-utility-card"><header><Globe /><div><strong>Connection status</strong><small>Proxmox Firewall provider</small></div></header><dl>{recordSummary(asRecord(overview.firewall)).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{String(value)}</dd></div>)}</dl>{canSync ? <button onClick={onTest}>Test connection</button> : null}</Card>
      <Card className="data-card dcst-utility-card"><header><RefreshCw /><div><strong>Synchronization</strong><small>Desired state and drift control</small></div></header><dl><div><dt>Inventory</dt><dd>{exactTime(overview.last_inventory_sync)}</dd></div><div><dt>Firewall</dt><dd>{exactTime(overview.last_firewall_sync)}</dd></div></dl>{canSync ? <div className="dcst-inline-actions"><button onClick={onDryRun}>Dry run</button><button onClick={onDrift}>Detect drift</button></div> : null}</Card>
      <Card className="data-card dcst-utility-card"><header><Wrench /><div><strong>Diagnostics</strong><small>Current DCST diagnostic output</small></div></header><pre>{JSON.stringify(diagnostics, null, 2)}</pre></Card>
      <Card className="data-card dcst-utility-card"><header><Shield /><div><strong>Firewall state</strong><small>Managed control-plane summary</small></div></header><pre>{JSON.stringify(overview.firewall || {}, null, 2)}</pre></Card>
    </div>
    {canViewLogs ? <Card className="data-card dcst-firewall-log-card"><header><Activity /><div><strong>Firewall Logs</strong><small>Filter and inspect managed firewall events</small></div></header>
      <div className="dcst-log-filters">
        <SearchInput value={filters.search} onChange={(event) => onFilter("search", event.target.value)} placeholder="Search logs..." aria-label="Search firewall logs" />
        <Select label="Node" value={filters.node} onChange={(event) => onFilter("node", event.target.value)}><option value="">All</option>{nodes.map((node) => <option key={node}>{node}</option>)}</Select>
        <Select label="Direction" value={filters.direction} onChange={(event) => onFilter("direction", event.target.value)}><option value="">All</option><option>IN</option><option>OUT</option></Select>
        <Select label="Action" value={filters.action} onChange={(event) => onFilter("action", event.target.value)}><option value="">All</option><option>ACCEPT</option><option>DROP</option><option>REJECT</option></Select>
        <label><span>Source</span><input value={filters.source} onChange={(event) => onFilter("source", event.target.value)} placeholder="IP / object" /></label>
        <label><span>Destination</span><input value={filters.destination} onChange={(event) => onFilter("destination", event.target.value)} placeholder="IP / object" /></label>
        <Select label="Time range" value={filters.range} onChange={(event) => onFilter("range", event.target.value)}><option value="">All</option><option value="15m">15 minutes</option><option value="1h">1 hour</option><option value="24h">24 hours</option></Select>
      </div>
      <div className="table-scroll dcst-log-table"><table><thead><tr><th>Node</th><th>Time</th><th>Direction</th><th>Action</th><th>Source</th><th>Destination</th><th>Raw message</th></tr></thead><tbody>{logs.map((row, index) => <tr key={String(row.id || index)}><td>{String(row.node || "—")}</td><td><code>{String(row.dcst_time || "—")}</code></td><td>{String(row.dcst_direction || "—")}</td><td>{String(row.dcst_action || "—")}</td><td><code>{String(row.dcst_source || "—")}</code></td><td><code>{String(row.dcst_destination || "—")}</code></td><td><code>{String(row.dcst_raw || JSON.stringify(row))}</code></td></tr>)}</tbody></table></div>
      {!loading && !logs.length ? <div className="dcst-inline-empty">No firewall logs match the current filters.</div> : null}
    </Card> : null}
  </PageSection>;
}
