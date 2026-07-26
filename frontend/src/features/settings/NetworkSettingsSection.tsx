import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowUpFromLine, CheckCircle2, ChevronDown, CircleOff,
  Download, Gauge, Globe2, Network, RefreshCw, Route as RouteIcon, Search, ShieldCheck, X, XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import {
  api,
  type DnsConfiguration,
  type DnsTestResult,
  type NetworkInterfaceDetail,
  type NetworkOverview,
  type NetworkRoute,
  type RoutingSnapshot,
} from "../../api";
import type { Translate } from "../../app/types";
import { formatSize } from "../files/utils";

const MAX_SAMPLES = 60;
type NetworkTab = "monitor" | "dns" | "routing";
type History = Record<string, number[]>;
type InterfaceFilter = "all" | "up" | "down" | "errors";
type RouteFamily = "all" | "ipv4" | "ipv6";

function formatRate(value: number | null) {
  return value === null ? "—" : `${formatSize(value)}/s`;
}

function valueOrDash(value: string | number | null | undefined) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function formatSpeed(value: number | null) {
  if (value === null) return "—";
  return value >= 1000 ? `${Number((value / 1000).toFixed(1))} Gb/s` : `${value} Mb/s`;
}

function primaryAddress(network: NetworkInterfaceDetail) {
  const address = network.addresses.find((item) => item.family === "ipv4" && item.scope === "global")
    || network.addresses.find((item) => item.family === "ipv4")
    || network.addresses[0];
  return address ? `${address.address}/${address.prefix_length}` : null;
}

function issueCount(network: NetworkInterfaceDetail) {
  return network.rx_errors + network.tx_errors + network.rx_dropped + network.tx_dropped;
}

function exportJson(filename: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function WarningList({ warnings, t }: { warnings: string[]; t: Translate }) {
  const unique = [...new Set(warnings.map((warning) => warning.trim()).filter(Boolean))];
  if (!unique.length) return null;
  return <div className="network-warning-list" role="status">{unique.map((warning) => <article key={warning}>
    <AlertTriangle aria-hidden="true" />
    <div><strong>{t("network.warningTitle")}</strong><p>{warning}</p></div>
  </article>)}</div>;
}

export function NetworkTrafficChart({ rx, tx, label }: { rx: number[]; tx: number[]; label: string }) {
  const length = Math.max(rx.length, tx.length);
  const safeRx = Array.from({ length }, (_, index) => Number.isFinite(rx[index]) ? Math.max(0, rx[index]) : 0);
  const safeTx = Array.from({ length }, (_, index) => Number.isFinite(tx[index]) ? Math.max(0, tx[index]) : 0);
  const maximum = Math.max(...safeRx, ...safeTx, 1);
  const points = (values: number[]) => values.map((value, index) => `${length <= 1 ? 0 : index * 100 / (length - 1)},${30 - value * 27 / maximum}`).join(" ");
  return <figure className="network-traffic-chart">
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={label}>
      {length > 0 && <><polyline className="rx" points={points(safeRx)} /><polyline className="tx" points={points(safeTx)} /></>}
    </svg>
    <figcaption><span className="rx">RX</span><span className="tx">TX</span></figcaption>
  </figure>;
}

type NetworkTotals = { active: number; inactive: number; download: number; upload: number; issues: number };

export function NetworkSummary({ overview, t }: { overview: NetworkOverview; t: Translate }) {
  const totals = useMemo<NetworkTotals>(() => ({
    active: overview.interfaces.filter((item) => item.state === "up").length,
    inactive: overview.interfaces.filter((item) => item.state !== "up").length,
    download: overview.interfaces.reduce((sum, item) => sum + (item.rx_bytes_per_sec || 0), 0),
    upload: overview.interfaces.reduce((sum, item) => sum + (item.tx_bytes_per_sec || 0), 0),
    issues: overview.interfaces.reduce((sum, item) => sum + issueCount(item), 0),
  }), [overview]);
  const physicalActive = overview.interfaces.some((item) => !item.system && item.state === "up");
  const health = !physicalActive ? "offline" : totals.issues > 0 || overview.warnings.length > 0 ? "warning" : "ok";
  const HealthIcon = health === "ok" ? CheckCircle2 : health === "warning" ? AlertTriangle : CircleOff;
  const cards = [
    { key: "active", icon: Network, value: totals.active, hint: `${t("network.interfacesDown")}: ${totals.inactive}` },
    { key: "download", icon: ArrowDownToLine, value: formatRate(totals.download), hint: t("network.currentTrafficHint") },
    { key: "upload", icon: ArrowUpFromLine, value: formatRate(totals.upload), hint: t("network.currentTrafficHint") },
    { key: "issues", icon: AlertTriangle, value: totals.issues.toLocaleString(), hint: t(totals.issues ? "network.issuesDetected" : "network.noIssues") },
  ];
  return <>
    <section className={`network-health-bar ${health}`} aria-label={t(`network.health.${health}`)}>
      <HealthIcon aria-hidden="true" />
      <div><strong>{t(`network.health.${health}`)}</strong><span>{t("network.activeInterfaceCount").replace("{count}", String(totals.active))}</span></div>
      <time dateTime={new Date(overview.timestamp * 1000).toISOString()}>{t("network.lastUpdated")}: {new Date(overview.timestamp * 1000).toLocaleTimeString()}</time>
    </section>
    <section className="network-summary-grid" aria-label={t("network.summary")}>{cards.map(({ key, icon: Icon, value, hint }) => <article key={key}>
      <Icon aria-hidden="true" /><div><span>{t(`network.summary.${key}`)}</span><strong>{value}</strong><small>{hint}</small></div>
    </article>)}</section>
  </>;
}

export function NetworkInterfaceCard({ network, rx, tx, gateways, dnsServers, t }: {
  network: NetworkInterfaceDetail; rx: number[]; tx: number[]; gateways: string[]; dnsServers: string[]; t: Translate;
}) {
  const [open, setOpen] = useState(false);
  const address = primaryAddress(network);
  const ipv4 = network.addresses.filter((item) => item.family === "ipv4");
  const ipv6 = network.addresses.filter((item) => item.family === "ipv6");
  const issues = issueCount(network);
  const stateLabel = network.system ? t("network.systemInterface") : network.state === "up" ? "UP" : network.state === "down" ? "DOWN" : "UNKNOWN";
  return <article className={`network-interface-card ${network.system ? "system" : network.state}`}>
    <header>
      <div className="network-interface-title"><span><Network aria-hidden="true" /></span><div><h4>{network.name}</h4><p>{address || t("network.noInterfaceAddress")}</p></div></div>
      <span className="network-interface-state"><i aria-hidden="true" />{stateLabel}</span>
    </header>
    <dl className="network-interface-overview">
      <div><dt>{t("network.linkSpeed")}</dt><dd>{formatSpeed(network.speed_mbps)}</dd></div>
      <div><dt>{t("network.download")}</dt><dd>{formatRate(network.rx_bytes_per_sec)}</dd></div>
      <div><dt>{t("network.upload")}</dt><dd>{formatRate(network.tx_bytes_per_sec)}</dd></div>
      <div><dt>{t("network.errorsAndDrops")}</dt><dd className={issues ? "danger" : ""}>{issues.toLocaleString()}</dd></div>
    </dl>
    <NetworkTrafficChart rx={rx} tx={tx} label={`${network.name} ${t("network.trafficHistory")}`} />
    <details className="network-interface-expanded" open={open}>
      <summary aria-expanded={open} onClick={(event) => { event.preventDefault(); setOpen((value) => !value); }}><span>{t(open ? "network.hideDetails" : "network.interfaceDetails")}</span><ChevronDown aria-hidden="true" /></summary>
      <div className="network-interface-sections">
        <section><h5>{t("network.connectionSection")}</h5><dl>
          <div><dt>{t("network.status")}</dt><dd>{network.state.toUpperCase()}</dd></div>
          <div><dt>{t("network.carrier")}</dt><dd>{network.carrier === null ? "—" : t(network.carrier ? "network.connected" : "network.disconnected")}</dd></div>
          <div><dt>{t("network.linkSpeed")}</dt><dd>{formatSpeed(network.speed_mbps)}</dd></div>
          <div><dt>{t("network.duplex")}</dt><dd>{valueOrDash(network.duplex)}</dd></div>
          <div><dt>MTU</dt><dd>{valueOrDash(network.mtu)}</dd></div>
          <div><dt>MAC</dt><dd><code>{valueOrDash(network.mac_address)}</code></dd></div>
        </dl></section>
        <section><h5>{t("network.addressingSection")}</h5><dl>
          <div><dt>IPv4</dt><dd>{ipv4.length ? ipv4.map((item) => <code key={item.address}>{item.address}/{item.prefix_length}</code>) : "—"}</dd></div>
          <div><dt>IPv6</dt><dd>{ipv6.length ? ipv6.map((item) => <code key={item.address}>{item.address}/{item.prefix_length}</code>) : "—"}</dd></div>
          <div><dt>{t("network.gateway")}</dt><dd>{gateways.length ? gateways.map((item) => <code key={item}>{item}</code>) : "—"}</dd></div>
          <div><dt>DNS</dt><dd>{dnsServers.length ? dnsServers.map((item) => <code key={item}>{item}</code>) : "—"}</dd></div>
        </dl></section>
        <section><h5>{t("network.statisticsSection")}</h5><dl>
          <div><dt>{t("network.received")}</dt><dd>{formatSize(network.rx_bytes)}</dd></div>
          <div><dt>{t("network.sent")}</dt><dd>{formatSize(network.tx_bytes)}</dd></div>
          <div><dt>{t("network.packets")} RX / TX</dt><dd>{network.rx_packets.toLocaleString()} / {network.tx_packets.toLocaleString()}</dd></div>
          <div><dt>{t("network.errors")} RX / TX</dt><dd>{network.rx_errors} / {network.tx_errors}</dd></div>
          <div><dt>{t("network.dropped")} RX / TX</dt><dd>{network.rx_dropped} / {network.tx_dropped}</dd></div>
        </dl></section>
        <section className="network-history-section"><h5>{t("network.historySection")}</h5><div>
          <NetworkTrafficChart rx={rx} tx={[]} label={`${network.name} ${t("network.downloadHistory")}`} />
          <NetworkTrafficChart rx={[]} tx={tx} label={`${network.name} ${t("network.uploadHistory")}`} />
        </div></section>
      </div>
    </details>
  </article>;
}

function NetworkMonitor({ t }: { t: Translate }) {
  const [overview, setOverview] = useState<NetworkOverview | null>(null);
  const [dns, setDns] = useState<DnsConfiguration | null>(null);
  const [routing, setRouting] = useState<RoutingSnapshot | null>(null);
  const [history, setHistory] = useState<History>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<InterfaceFilter>("all");
  const [refreshInterval, setRefreshInterval] = useState(2000);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const hasOverview = useRef(false);

  const refreshOverview = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    if (mounted.current) { setLoading(true); setError(""); }
    try {
      const next = await api.networkOverview();
      if (!mounted.current) return;
      hasOverview.current = true;
      setOverview(next);
      setHistory((current) => {
        const updated = { ...current };
        next.interfaces.forEach((item) => {
          updated[`rx:${item.name}`] = [...(updated[`rx:${item.name}`] || []), item.rx_bytes_per_sec || 0].slice(-MAX_SAMPLES);
          updated[`tx:${item.name}`] = [...(updated[`tx:${item.name}`] || []), item.tx_bytes_per_sec || 0].slice(-MAX_SAMPLES);
        });
        return updated;
      });
    } catch (reason) {
      if (mounted.current) setError(hasOverview.current ? t("network.staleData") : reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [t]);

  const refreshContext = useCallback(async () => {
    const [dnsResult, routingResult] = await Promise.allSettled([api.networkDns(), api.networkRouting()]);
    if (!mounted.current) return;
    if (dnsResult.status === "fulfilled") setDns(dnsResult.value);
    if (routingResult.status === "fulfilled") setRouting(routingResult.value);
  }, []);

  useEffect(() => { mounted.current = true; void refreshOverview(); void refreshContext(); return () => { mounted.current = false; }; }, [refreshContext, refreshOverview]);
  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void refreshOverview(); }, refreshInterval);
    return () => window.clearInterval(timer);
  }, [autoRefresh, refreshInterval, refreshOverview]);

  const visibleInterfaces = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (overview?.interfaces || []).filter((item) => {
      const matchesText = !needle || [item.name, item.mac_address || "", ...item.addresses.map((address) => address.address)].some((value) => value.toLowerCase().includes(needle));
      const matchesState = filter === "all" || filter === "errors" && issueCount(item) > 0 || filter === "up" && item.state === "up" || filter === "down" && item.state !== "up";
      return matchesText && matchesState;
    });
  }, [filter, overview, query]);
  const globalDns = dns?.systemd_resolved.global_servers.length ? dns.systemd_resolved.global_servers : dns?.resolv_conf.nameservers || [];

  async function refreshAll() {
    await Promise.all([refreshOverview(), refreshContext()]);
  }

  return <section className="network-diagnostic-panel" aria-labelledby="network-monitor-title" aria-busy={loading}>
    <header><div><h3 id="network-monitor-title">{t("network.monitor")}</h3><p>{t("network.monitorDescription")}</p></div><div className="network-header-actions">
      <button type="button" onClick={() => overview && exportJson(`network-${new Date().toISOString()}.json`, { overview, dns, routing })} disabled={!overview}><Download aria-hidden="true" />{t("network.exportData")}</button>
      <button type="button" onClick={() => void refreshAll()} disabled={loading} aria-busy={loading}><RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />{t("network.refreshNow")}</button>
    </div></header>
    {error && <p className="error-state compact-error" role="alert">{error}</p>}
    <WarningList warnings={overview?.warnings || []} t={t} />
    {!overview && loading && <div className="loading-state">{t("status.loading")}</div>}
    {overview && <>
      <NetworkSummary overview={overview} t={t} />
      <section className="network-refresh-controls" aria-label={t("network.refreshSettings")}>
        <button type="button" role="switch" aria-checked={autoRefresh} onClick={() => setAutoRefresh((value) => !value)}><span aria-hidden="true" /><strong>{t("network.autoRefresh")}</strong><small>{t(autoRefresh ? "network.autoRefreshEnabled" : "network.autoRefreshDisabled")}</small></button>
        {autoRefresh && <label><span>{t("network.refreshFrequency")}</span><select value={refreshInterval} onChange={(event) => setRefreshInterval(Number(event.target.value))}><option value={2000}>2 s</option><option value={5000}>5 s</option><option value={10000}>10 s</option><option value={30000}>30 s</option></select></label>}
        <p aria-live="polite">{t("network.lastUpdated")}: {new Date(overview.timestamp * 1000).toLocaleTimeString()}</p>
      </section>
      <section className="network-toolbar" aria-label={t("network.interfaceFilters")}>
        <label className="network-search"><Search aria-hidden="true" /><span>{t("network.searchInterfaces")}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("network.searchInterfaces")} />{query && <button type="button" aria-label={t("network.clearSearch")} onClick={() => setQuery("")}><X aria-hidden="true" /></button>}</label>
        <label><span>{t("network.filter")}</span><select value={filter} onChange={(event) => setFilter(event.target.value as InterfaceFilter)}><option value="all">{t("network.allInterfaces")}</option><option value="up">{t("network.activeInterfaces")}</option><option value="down">{t("network.inactiveInterfaces")}</option><option value="errors">{t("network.withErrors")}</option></select></label>
        <p aria-live="polite">{t("network.visibleInterfaces").replace("{visible}", String(visibleInterfaces.length)).replace("{total}", String(overview.interfaces.length))}</p>
      </section>
      <div className="network-interface-grid">{visibleInterfaces.map((item) => {
        const gateways = routing?.gateways.filter((gateway) => gateway.device === item.name).map((gateway) => gateway.address) || [];
        const linkDns = dns?.systemd_resolved.links.find((link) => link.interface === item.name)?.servers || [];
        return <NetworkInterfaceCard key={item.name} network={item} rx={history[`rx:${item.name}`] || []} tx={history[`tx:${item.name}`] || []} gateways={gateways} dnsServers={linkDns.length ? linkDns : globalDns} t={t} />;
      })}</div>
    </>}
    {overview && !visibleInterfaces.length && <div className="empty-state">{t("network.noMatchingInterfaces")}</div>}
  </section>;
}

export function DnsDiagnostics({ t }: { t: Translate }) {
  const [configuration, setConfiguration] = useState<DnsConfiguration | null>(null);
  const [hostname, setHostname] = useState("example.com");
  const [result, setResult] = useState<DnsTestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");
  const hasConfiguration = useRef(false);
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setConfiguration(await api.networkDns()); hasConfiguration.current = true; }
    catch (reason) { setError(hasConfiguration.current ? t("network.staleData") : reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void refresh(); }, [refresh]);
  async function test(event: React.FormEvent) {
    event.preventDefault(); setTesting(true); setError(""); setResult(null);
    try { setResult(await api.testNetworkDns(hostname.trim())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setTesting(false); }
  }
  const servers = configuration?.systemd_resolved.global_servers.length ? configuration.systemd_resolved.global_servers : configuration?.resolv_conf.nameservers || [];
  const domains = configuration?.systemd_resolved.global_domains?.length ? configuration.systemd_resolved.global_domains : configuration?.resolv_conf.search || [];
  const mode = configuration?.systemd_resolved.available ? "systemd-resolved" : configuration?.resolv_conf.mode || "—";
  const successfulServers = result?.servers.filter((server) => server.success) || [];
  const resultState = result?.success ? "success" : successfulServers.length ? "partial" : "error";
  const latency = successfulServers.length ? successfulServers.reduce((sum, server) => sum + (server.latency_ms || 0), 0) / successfulServers.length : null;
  return <section className="network-diagnostic-panel" aria-labelledby="network-dns-title" aria-busy={loading}>
    <header><div><h3 id="network-dns-title">DNS</h3><p>{t("network.dnsDescription")}</p></div><button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />{t("network.refreshNow")}</button></header>
    {error && <p className="error-state compact-error" role="alert">{error}</p>}
    <form className="network-dns-test" onSubmit={(event) => void test(event)}>
      <div><h4>{t("network.dnsTestTitle")}</h4><p>{t("network.dnsTestSummary")}</p></div>
      <label>{t("network.domainToTest")}<input value={hostname} required minLength={1} maxLength={253} spellCheck={false} autoCapitalize="none" placeholder="example.com" onChange={(event) => setHostname(event.target.value)} /></label>
      <button className="button-primary" type="submit" disabled={testing}>{testing ? t("status.loading") : t("network.runDnsTest")}</button>
    </form>
    {result && <section className={`network-dns-result ${resultState}`} aria-live="polite">
      <header>{resultState === "success" ? <CheckCircle2 aria-hidden="true" /> : resultState === "partial" ? <AlertTriangle aria-hidden="true" /> : <XCircle aria-hidden="true" />}<div><strong>{t(`network.dnsResult.${resultState}`)}</strong><span>{result.hostname}</span></div></header>
      <dl className="network-dns-result-summary"><div><dt>{t("network.latency")}</dt><dd>{latency === null ? "—" : `${latency.toFixed(2)} ms`}</dd></div><div><dt>{t("network.ipAddresses")}</dt><dd>{result.addresses.join(", ") || "—"}</dd></div></dl>
      <details><summary>{t("network.dnsServerDetails")} ({result.servers.length})</summary><div className="monitor-table-wrap"><table><thead><tr><th>{t("network.dnsServer")}</th><th>{t("network.status")}</th><th>{t("network.latency")}</th><th>RCODE</th><th>{t("network.ipAddresses")}</th></tr></thead><tbody>{result.servers.length ? result.servers.map((server) => <tr key={server.server}><td data-label={t("network.dnsServer")}><code>{server.server}</code></td><td data-label={t("network.status")}>{server.success ? t("status.ready") : server.error || t("status.error")}</td><td data-label={t("network.latency")}>{server.latency_ms === null ? "—" : `${server.latency_ms.toFixed(2)} ms`}</td><td data-label="RCODE">{server.rcode || "—"}</td><td data-label={t("network.ipAddresses")}>{server.addresses.join(", ") || "—"}</td></tr>) : <tr><td colSpan={5}>{t("network.noDnsServers")}</td></tr>}</tbody></table></div></details>
    </section>}
    <WarningList warnings={configuration?.warnings || []} t={t} />
    {configuration && <section className="network-dns-configuration">
      <h4>{t("network.dnsConfigurationSummary")}</h4>
      <dl><div><dt>{t("network.dnsServers")}</dt><dd>{servers.join(", ") || "—"}</dd></div><div><dt>{t("network.searchDomains")}</dt><dd>{domains.join(", ") || "—"}</dd></div><div><dt>{t("network.mode")}</dt><dd>{mode}</dd></div></dl>
      <details><summary>{t("network.dnsConfigurationDetails")}</summary><div className="network-dns-detail-grid">
        <section><h5>/etc/resolv.conf</h5><dl><div><dt>{t("network.path")}</dt><dd><code>{configuration.resolv_conf.path}</code></dd></div><div><dt>{t("network.symlinkTarget")}</dt><dd><code>{valueOrDash(configuration.resolv_conf.symlink_target)}</code></dd></div><div><dt>{t("network.options")}</dt><dd>{configuration.resolv_conf.options.join(", ") || "—"}</dd></div></dl></section>
        <section><h5>systemd-resolved</h5>{configuration.systemd_resolved.available ? <dl><div><dt>{t("network.globalDns")}</dt><dd>{configuration.systemd_resolved.global_servers.join(", ") || "—"}</dd></div>{configuration.systemd_resolved.links.map((link) => <div key={link.interface}><dt>{link.interface}</dt><dd>{link.servers.join(", ") || "—"}{link.domains.length ? ` · ${link.domains.join(", ")}` : ""}</dd></div>)}</dl> : <p>{t("network.systemdUnavailable")}</p>}</section>
      </div></details>
    </section>}
  </section>;
}

function isDefaultRoute(route: NetworkRoute) {
  return ["default", "0.0.0.0/0", "::/0"].includes(route.destination);
}

export function RoutingTable({ t }: { t: Translate }) {
  const [data, setData] = useState<RoutingSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState<RouteFamily>("all");
  const hasData = useRef(false);
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await api.networkRouting()); hasData.current = true; }
    catch (reason) { setError(hasData.current ? t("network.staleData") : reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void refresh(); }, [refresh]);
  const routes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data?.routes || []).filter((route) => family === "all" || route.family === family).filter((route) => !needle || [route.destination, route.gateway || "", route.device || "", route.table, route.protocol || "", route.preferred_source || ""].some((value) => value.toLowerCase().includes(needle)));
  }, [data, family, query]);
  return <section className="network-diagnostic-panel" aria-labelledby="network-routing-title" aria-busy={loading}>
    <header><div><h3 id="network-routing-title">{t("network.routing")}</h3><p>{t("network.routingDescription")}</p></div><button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />{t("network.refreshNow")}</button></header>
    <div className="network-read-only"><ShieldCheck aria-hidden="true" /><span><strong>{t("network.readOnly")}</strong>{t("network.readOnlyHint")}</span></div>
    {error && <p className="error-state compact-error" role="alert">{error}</p>}
    <WarningList warnings={data?.warnings || []} t={t} />
    {data && <>
      <section className="network-routing-section"><h4>{t("network.activeGateways")}</h4><div className="network-gateway-grid">{data.gateways.length ? data.gateways.map((gateway, index) => <article key={`${gateway.family}:${gateway.address}:${gateway.device}:${index}`}><Globe2 aria-hidden="true" /><div><strong>{gateway.address}</strong><span>{gateway.family.toUpperCase()} · {gateway.device || "—"}</span><small>{t("network.table")}: {gateway.table} · {t("network.metric")}: {valueOrDash(gateway.metric)}</small></div><b>{t("network.defaultGateway")}</b></article>) : <div className="empty-state">{t("network.noGateways")}</div>}</div></section>
      <section className="network-routing-section"><div className="network-routing-heading"><div><h4>{t("network.routes")}</h4><p>{t("network.visibleRoutes").replace("{visible}", String(routes.length)).replace("{total}", String(data.routes.length))}</p></div><div>
        <label className="network-search"><Search aria-hidden="true" /><span>{t("network.searchRoutes")}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("network.searchRoutes")} /></label>
        <label><span>{t("network.family")}</span><select aria-label={t("network.family")} value={family} onChange={(event) => setFamily(event.target.value as RouteFamily)}><option value="all">IPv4 + IPv6</option><option value="ipv4">IPv4</option><option value="ipv6">IPv6</option></select></label>
        <button type="button" onClick={() => exportJson(`routing-${new Date().toISOString()}.json`, data)}><Download aria-hidden="true" />{t("network.exportData")}</button>
      </div></div>
      <div className="network-routes-desktop monitor-table-wrap"><table><thead><tr><th>{t("network.family")}</th><th>{t("network.destination")}</th><th>{t("network.gateway")}</th><th>{t("network.interface")}</th><th>{t("network.table")}</th><th>{t("network.metric")}</th><th>{t("network.protocol")}</th><th>{t("network.source")}</th></tr></thead><tbody>{routes.length ? routes.map((route, index) => <tr className={isDefaultRoute(route) ? "default" : ""} key={`${route.family}:${route.table}:${route.destination}:${index}`}><td>{route.family.toUpperCase()}</td><td><code>{route.destination}</code></td><td><code>{valueOrDash(route.gateway)}</code></td><td>{valueOrDash(route.device)}</td><td>{route.table}</td><td>{valueOrDash(route.metric)}</td><td>{valueOrDash(route.protocol)}</td><td><code>{valueOrDash(route.preferred_source)}</code></td></tr>) : <tr><td colSpan={8}>{t("network.noRoutes")}</td></tr>}</tbody></table></div>
      <div className="network-route-cards">{routes.length ? routes.map((route, index) => <article className={isDefaultRoute(route) ? "default" : ""} key={`${route.family}:${route.table}:${route.destination}:${index}`}><header><strong>{route.destination}</strong><span>{route.family.toUpperCase()}</span></header><dl><div><dt>{t("network.gateway")}</dt><dd>{valueOrDash(route.gateway)}</dd></div><div><dt>{t("network.interface")}</dt><dd>{valueOrDash(route.device)}</dd></div><div><dt>{t("network.table")}</dt><dd>{route.table}</dd></div><div><dt>{t("network.metric")}</dt><dd>{valueOrDash(route.metric)}</dd></div><div><dt>{t("network.protocol")}</dt><dd>{valueOrDash(route.protocol)}</dd></div><div><dt>{t("network.source")}</dt><dd>{valueOrDash(route.preferred_source)}</dd></div></dl></article>) : <div className="empty-state">{t("network.noRoutes")}</div>}</div>
      </section>
      <details className="network-routing-rules"><summary>{t("network.routingAdvancedRules").replace("{count}", String(data.rules.length))}</summary><div className="monitor-table-wrap"><table><thead><tr><th>{t("network.priority")}</th><th>{t("network.family")}</th><th>{t("network.from")}</th><th>{t("network.to")}</th><th>{t("network.table")}</th><th>{t("network.action")}</th><th>fwmark</th><th>IIF / OIF</th></tr></thead><tbody>{data.rules.length ? data.rules.map((rule, index) => <tr key={`${rule.family}:${rule.priority}:${index}`}><td>{valueOrDash(rule.priority)}</td><td>{rule.family.toUpperCase()}</td><td><code>{rule.from}</code></td><td><code>{rule.to}</code></td><td>{valueOrDash(rule.table)}</td><td>{rule.action}</td><td>{valueOrDash(rule.fwmark)}</td><td>{rule.input_interface || "—"} / {rule.output_interface || "—"}</td></tr>) : <tr><td colSpan={8}>{t("network.noRules")}</td></tr>}</tbody></table></div></details>
    </>}
  </section>;
}

export function NetworkSettingsSection({ isAdmin, t }: { isAdmin: boolean; t: Translate }) {
  const [tab, setTab] = useState<NetworkTab>("monitor");
  const tabs: Array<{ id: NetworkTab; icon: ReactNode; label: string }> = [
    { id: "monitor", icon: <Activity aria-hidden="true" />, label: t("network.monitor") },
    { id: "dns", icon: <Globe2 aria-hidden="true" />, label: "DNS" },
    { id: "routing", icon: <RouteIcon aria-hidden="true" />, label: t("network.routing") },
  ];
  if (!isAdmin) return null;
  function keyboard(event: KeyboardEvent<HTMLElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = tabs.findIndex((item) => item.id === tab);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : event.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
    setTab(tabs[next].id);
    requestAnimationFrame(() => document.getElementById(`network-tab-${tabs[next].id}`)?.focus());
  }
  return <section className="network-settings" aria-labelledby="network-settings-title">
    <header className="network-settings-page-header"><span><Gauge aria-hidden="true" /></span><div><h2 id="network-settings-title">{t("settings.category.network")}</h2><p>{t("network.settingsDescription")}</p></div></header>
    <nav className="network-settings-tabs" role="tablist" aria-label={t("settings.category.network")} onKeyDown={keyboard}>{tabs.map((item) => <button id={`network-tab-${item.id}`} key={item.id} type="button" role="tab" aria-selected={tab === item.id} aria-controls={`network-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.icon}<span>{item.label}</span></button>)}</nav>
    <div id={`network-panel-${tab}`} role="tabpanel" aria-labelledby={`network-tab-${tab}`}>
      {tab === "monitor" && <NetworkMonitor t={t} />}
      {tab === "dns" && <DnsDiagnostics t={t} />}
      {tab === "routing" && <RoutingTable t={t} />}
    </div>
  </section>;
}
