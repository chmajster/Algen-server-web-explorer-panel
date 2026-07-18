import { Activity, CheckCircle2, Globe2, RefreshCw, Route as RouteIcon, ShieldCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import {
  api,
  type DnsConfiguration,
  type DnsTestResult,
  type NetworkOverview,
  type RoutingSnapshot,
} from "../../api";
import type { Translate } from "../../app/types";
import { formatSize } from "../files/utils";

const MAX_SAMPLES = 60;
type NetworkTab = "monitor" | "dns" | "routing";
type History = Record<string, number[]>;

function formatRate(value: number | null) {
  return value === null ? "—" : `${formatSize(value)}/s`;
}

function valueOrDash(value: string | number | null | undefined) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function Sparkline({ values, label }: { values: number[]; label: string }) {
  const maximum = Math.max(...values, 1);
  const points = values.map((value, index) => `${values.length === 1 ? 0 : index * 100 / (values.length - 1)},${30 - value * 27 / maximum}`).join(" ");
  return <svg className="monitor-sparkline" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={label}><polyline points={points} /></svg>;
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return <div className="network-warning-list" role="status">{warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>;
}

function NetworkMonitor({ t }: { t: Translate }) {
  const [overview, setOverview] = useState<NetworkOverview | null>(null);
  const [dns, setDns] = useState<DnsConfiguration | null>(null);
  const [routing, setRouting] = useState<RoutingSnapshot | null>(null);
  const [history, setHistory] = useState<History>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const inFlight = useRef(false);

  const refreshOverview = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    if (mounted.current) { setLoading(true); setError(""); }
    try {
      const next = await api.networkOverview();
      if (!mounted.current) return;
      setOverview(next);
      setHistory((current) => {
        const updated = { ...current };
        for (const network of next.interfaces) {
          updated[`rx:${network.name}`] = [...(updated[`rx:${network.name}`] || []), network.rx_bytes_per_sec || 0].slice(-MAX_SAMPLES);
          updated[`tx:${network.name}`] = [...(updated[`tx:${network.name}`] || []), network.tx_bytes_per_sec || 0].slice(-MAX_SAMPLES);
        }
        return updated;
      });
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : t("error.generic"));
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

  useEffect(() => {
    mounted.current = true;
    void refreshOverview();
    void refreshContext();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshOverview();
    }, 2000);
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, [refreshContext, refreshOverview]);

  async function refreshAll() {
    await Promise.all([refreshOverview(), refreshContext()]);
  }

  const globalDns = dns?.systemd_resolved.global_servers.length
    ? dns.systemd_resolved.global_servers
    : dns?.resolv_conf.nameservers || [];

  return <section className="network-diagnostic-panel" aria-labelledby="network-monitor-title">
    <header><div><h3 id="network-monitor-title">{t("network.monitor")}</h3><p>{t("network.monitorDescription")}</p></div><button type="button" onClick={() => void refreshAll()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></header>
    {error && <p className="error-state compact-error" role="alert">{error}</p>}
    <Warnings warnings={overview?.warnings || []} />
    {!overview && loading && <div className="loading-state">{t("status.loading")}</div>}
    {overview && <div className="monitor-network-grid network-interface-grid">{overview.interfaces.map((network) => {
      const gateways = routing?.gateways.filter((gateway) => gateway.device === network.name).map((gateway) => gateway.address) || [];
      const linkDns = dns?.systemd_resolved.links.find((link) => link.interface === network.name)?.servers || [];
      const dnsServers = linkDns.length ? linkDns : globalDns;
      return <article key={network.name}>
        <header><div><strong>{network.name}</strong><small>{network.mac_address || (network.system ? t("network.systemInterface") : "—")}</small></div><span className={`monitor-state ${network.state === "up" ? "up" : network.state === "down" ? "down" : ""}`}>{network.state}</span></header>
        <dl className="network-interface-details">
          <div><dt>{t("network.linkSpeed")}</dt><dd>{network.speed_mbps === null ? "—" : `${network.speed_mbps} Mb/s${network.duplex ? ` · ${network.duplex}` : ""}`}</dd></div>
          <div><dt>{t("network.carrier")}</dt><dd>{network.carrier === null ? "—" : network.carrier ? t("network.connected") : t("network.disconnected")}</dd></div>
          <div><dt>MTU</dt><dd>{valueOrDash(network.mtu)}</dd></div>
          <div><dt>{t("network.ipAddresses")}</dt><dd>{network.addresses.length ? network.addresses.map((address) => <code key={`${address.family}:${address.address}`}>{address.address}/{address.prefix_length}</code>) : "—"}</dd></div>
          <div><dt>{t("network.gateway")}</dt><dd>{gateways.length ? gateways.map((gateway) => <code key={gateway}>{gateway}</code>) : "—"}</dd></div>
          <div><dt>DNS</dt><dd>{dnsServers.length ? dnsServers.map((server) => <code key={server}>{server}</code>) : "—"}</dd></div>
        </dl>
        <div className="monitor-pairs">
          <span>{t("network.received")} <strong>{formatSize(network.rx_bytes)}</strong></span><span>{t("network.sent")} <strong>{formatSize(network.tx_bytes)}</strong></span>
          <span>{t("network.download")} <strong>{formatRate(network.rx_bytes_per_sec)}</strong></span><span>{t("network.upload")} <strong>{formatRate(network.tx_bytes_per_sec)}</strong></span>
          <span>{t("network.packets")} RX <strong>{network.rx_packets.toLocaleString()}</strong></span><span>{t("network.packets")} TX <strong>{network.tx_packets.toLocaleString()}</strong></span>
          <span>{t("network.errors")} RX/TX <strong>{network.rx_errors} / {network.tx_errors}</strong></span><span>{t("network.dropped")} RX/TX <strong>{network.rx_dropped} / {network.tx_dropped}</strong></span>
        </div>
        <div className="monitor-network-history"><div><Sparkline values={history[`rx:${network.name}`] || []} label={`${network.name} ${t("network.downloadHistory")}`} /><small>{t("network.downloadHistory")}</small></div><div><Sparkline values={history[`tx:${network.name}`] || []} label={`${network.name} ${t("network.uploadHistory")}`} /><small>{t("network.uploadHistory")}</small></div></div>
      </article>;
    })}</div>}
    {overview && !overview.interfaces.length && <div className="empty-state">{t("network.noInterfaces")}</div>}
  </section>;
}

function DnsDiagnostics({ t }: { t: Translate }) {
  const [configuration, setConfiguration] = useState<DnsConfiguration | null>(null);
  const [hostname, setHostname] = useState("example.com");
  const [result, setResult] = useState<DnsTestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setConfiguration(await api.networkDns()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setLoading(false); }
  }, [t]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function test(event: React.FormEvent) {
    event.preventDefault();
    setTesting(true); setError(""); setResult(null);
    try { setResult(await api.testNetworkDns(hostname.trim())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setTesting(false); }
  }

  return <section className="network-diagnostic-panel" aria-labelledby="network-dns-title">
    <header><div><h3 id="network-dns-title">DNS</h3><p>{t("network.dnsDescription")}</p></div><button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></header>
    {error && <p className="error-state compact-error" role="alert">{error}</p>}
    <Warnings warnings={configuration?.warnings || []} />
    {configuration && <div className="network-dns-grid">
      <article className="network-info-card"><h4>/etc/resolv.conf</h4><dl>
        <div><dt>{t("network.mode")}</dt><dd>{configuration.resolv_conf.mode}</dd></div>
        <div><dt>{t("network.path")}</dt><dd><code>{configuration.resolv_conf.path}</code></dd></div>
        <div><dt>{t("network.symlinkTarget")}</dt><dd>{configuration.resolv_conf.symlink_target ? <code>{configuration.resolv_conf.symlink_target}</code> : "—"}</dd></div>
        <div><dt>{t("network.dnsServers")}</dt><dd>{configuration.resolv_conf.nameservers.join(", ") || "—"}</dd></div>
        <div><dt>{t("network.searchDomains")}</dt><dd>{configuration.resolv_conf.search.join(", ") || "—"}</dd></div>
        <div><dt>{t("network.options")}</dt><dd>{configuration.resolv_conf.options.join(", ") || "—"}</dd></div>
      </dl></article>
      <article className="network-info-card"><h4>systemd-resolved</h4>{configuration.systemd_resolved.available ? <dl>
        <div><dt>{t("network.globalDns")}</dt><dd>{configuration.systemd_resolved.global_servers.join(", ") || "—"}</dd></div>
        <div><dt>{t("network.searchDomains")}</dt><dd>{configuration.systemd_resolved.global_domains?.join(", ") || "—"}</dd></div>
        {configuration.systemd_resolved.links.map((link) => <div key={link.interface}><dt>{link.interface}</dt><dd>{link.servers.join(", ") || "—"}{link.domains.length ? ` · ${link.domains.join(", ")}` : ""}</dd></div>)}
      </dl> : <p className="network-muted">{t("network.systemdUnavailable")}</p>}</article>
    </div>}
    <form className="network-dns-test" onSubmit={(event) => void test(event)}>
      <label>{t("network.domainToTest")}<input value={hostname} required minLength={1} maxLength={253} spellCheck={false} autoCapitalize="none" placeholder="example.com" onChange={(event) => setHostname(event.target.value)} /></label>
      <button className="button-primary" type="submit" disabled={testing}>{testing ? t("status.loading") : t("network.runDnsTest")}</button>
    </form>
    {result && <section className={`network-dns-result ${result.success ? "success" : "error"}`} aria-live="polite">
      <header>{result.success ? <CheckCircle2 /> : <XCircle />}<div><strong>{result.success ? t("network.resolutionSucceeded") : t("network.resolutionFailed")}</strong><small>{result.hostname}{result.addresses.length ? ` · ${result.addresses.join(", ")}` : ""}</small></div></header>
      <div className="monitor-table-wrap"><table><thead><tr><th>{t("network.dnsServer")}</th><th>{t("network.status")}</th><th>{t("network.latency")}</th><th>RCODE</th><th>{t("network.ipAddresses")}</th></tr></thead><tbody>{result.servers.length ? result.servers.map((server) => <tr key={server.server}><td><code>{server.server}</code></td><td>{server.success ? t("status.ready") : server.error || t("status.error")}</td><td>{server.latency_ms === null ? "—" : `${server.latency_ms.toFixed(2)} ms`}</td><td>{server.rcode || "—"}</td><td>{server.addresses.join(", ") || "—"}</td></tr>) : <tr><td colSpan={5} className="monitor-empty-cell">{t("network.noDnsServers")}</td></tr>}</tbody></table></div>
    </section>}
  </section>;
}

function RoutingTable({ t }: { t: Translate }) {
  const [data, setData] = useState<RoutingSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await api.networkRouting()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void refresh(); }, [refresh]);

  return <section className="network-diagnostic-panel" aria-labelledby="network-routing-title">
    <header><div><h3 id="network-routing-title">{t("network.routing")}</h3><p>{t("network.routingDescription")}</p></div><button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></header>
    <div className="network-read-only"><ShieldCheck /> <span><strong>{t("network.readOnly")}</strong>{t("network.readOnlyHint")}</span></div>
    {error && <p className="error-state compact-error" role="alert">{error}</p>}
    <Warnings warnings={data?.warnings || []} />
    {data && <>
      <section className="network-routing-section"><h4>{t("network.activeGateways")}</h4><div className="network-gateway-grid">{data.gateways.length ? data.gateways.map((gateway, index) => <article key={`${gateway.family}:${gateway.address}:${gateway.device}:${index}`}><strong>{gateway.address}</strong><span>{gateway.family.toUpperCase()} · {gateway.device || "—"}</span><small>{t("network.table")}: {gateway.table} · {t("network.metric")}: {valueOrDash(gateway.metric)}</small></article>) : <div className="empty-state">{t("network.noGateways")}</div>}</div></section>
      <section className="network-routing-section"><h4>{t("network.routes")} ({data.routes.length})</h4><div className="monitor-table-wrap"><table><thead><tr><th>{t("network.family")}</th><th>{t("network.destination")}</th><th>{t("network.gateway")}</th><th>{t("network.interface")}</th><th>{t("network.table")}</th><th>{t("network.metric")}</th><th>{t("network.protocol")}</th><th>{t("network.source")}</th></tr></thead><tbody>{data.routes.length ? data.routes.map((route, index) => <tr key={`${route.family}:${route.table}:${route.destination}:${index}`}><td>{route.family.toUpperCase()}</td><td><code>{route.destination}</code></td><td>{valueOrDash(route.gateway)}</td><td>{valueOrDash(route.device)}</td><td>{route.table}</td><td>{valueOrDash(route.metric)}</td><td>{valueOrDash(route.protocol)}</td><td>{valueOrDash(route.preferred_source)}</td></tr>) : <tr><td colSpan={8} className="monitor-empty-cell">{t("network.noRoutes")}</td></tr>}</tbody></table></div></section>
      <section className="network-routing-section"><h4>{t("network.rules")} ({data.rules.length})</h4><div className="monitor-table-wrap"><table><thead><tr><th>{t("network.priority")}</th><th>{t("network.family")}</th><th>{t("network.from")}</th><th>{t("network.to")}</th><th>{t("network.table")}</th><th>{t("network.action")}</th><th>fwmark</th><th>IIF / OIF</th></tr></thead><tbody>{data.rules.length ? data.rules.map((rule, index) => <tr key={`${rule.family}:${rule.priority}:${index}`}><td>{valueOrDash(rule.priority)}</td><td>{rule.family.toUpperCase()}</td><td><code>{rule.from}</code></td><td><code>{rule.to}</code></td><td>{valueOrDash(rule.table)}</td><td>{rule.action}</td><td>{valueOrDash(rule.fwmark)}</td><td>{rule.input_interface || "—"} / {rule.output_interface || "—"}</td></tr>) : <tr><td colSpan={8} className="monitor-empty-cell">{t("network.noRules")}</td></tr>}</tbody></table></div></section>
    </>}
  </section>;
}

export function NetworkSettingsSection({ isAdmin, t }: { isAdmin: boolean; t: Translate }) {
  const [tab, setTab] = useState<NetworkTab>("monitor");
  const tabs: Array<{ id: NetworkTab; icon: ReactNode; label: string }> = [
    { id: "monitor", icon: <Activity />, label: t("network.monitor") },
    { id: "dns", icon: <Globe2 />, label: "DNS" },
    { id: "routing", icon: <RouteIcon />, label: t("network.routing") },
  ];
  if (!isAdmin) return null;
  return <div className="network-settings">
    <nav className="network-settings-tabs" role="tablist" aria-label={t("settings.category.network")}>{tabs.map((item) => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.icon}<span>{item.label}</span></button>)}</nav>
    {tab === "monitor" && <NetworkMonitor t={t} />}
    {tab === "dns" && <DnsDiagnostics t={t} />}
    {tab === "routing" && <RoutingTable t={t} />}
  </div>;
}
