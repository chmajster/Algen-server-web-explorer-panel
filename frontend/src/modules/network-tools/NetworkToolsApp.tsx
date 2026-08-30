import { useState } from "react";
import { Network, Play } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { networkToolsClient } from "./api/client";
import "../security-tools.css";

type Tab = "ping" | "traceroute" | "dns" | "port" | "http" | "routes" | "connections";

function Result({ value, empty }: { value: unknown; empty: string }) { return <pre>{value ? JSON.stringify(value, null, 2) : empty}</pre>; }

export function NetworkToolsApp({ permissions, language, toast }: { permissions: readonly string[]; language: string; toast: ToastFn }) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    eyebrow: pl ? "Diagnostyka" : "Diagnostics",
    title: "Network Tools",
    subtitle: pl ? "Typowane narzędzia diagnostyki sieci z dozwolonymi poleceniami, limitami czasu i wyjścia, bez terminala WWW." : "Typed network diagnostics with fixed command allowlists, timeouts, output limits and no web terminal.",
    sections: pl ? "Sekcje Network Tools" : "Network Tools sections",
    portTest: pl ? "Test portu" : "Port Test",
    httpTest: "HTTP Test",
    routes: pl ? "Trasy" : "Routes",
    connections: pl ? "Połączenia" : "Connections",
    noPermission: pl ? "Nie masz uprawnień do uruchomienia tej diagnostyki." : "You do not have permission to run this diagnostic.",
    target: pl ? "Cel" : "Target",
    hostname: pl ? "Nazwa hosta lub IP" : "Hostname or IP",
    port: "Port",
    recordType: pl ? "Typ rekordu DNS" : "DNS record type",
    dnsServer: pl ? "Serwer DNS" : "DNS server",
    dnsServerOptional: pl ? "IP serwera DNS (opcjonalnie)" : "DNS server IP (optional)",
    run: pl ? "Uruchom" : "Run",
    empty: pl ? "Uruchom diagnostykę, aby zobaczyć wyniki." : "Run a diagnostic to see results.",
  };
  const [tab, setTab] = useState<Tab>("ping");
  const [target, setTarget] = useState("example.com");
  const [port, setPort] = useState(443);
  const [recordType, setRecordType] = useState("A");
  const [dnsServer, setDnsServer] = useState("");
  const [url, setUrl] = useState("https://example.com/");
  const [result, setResult] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const can = (permission: string) => permissions.includes(permission);
  async function run(callback: () => Promise<unknown>) { setLoading(true); try { setResult(await callback()); } catch (error) { toast(String(error), "error"); } finally { setLoading(false); } }
  async function loadTab(next: Tab) { setTab(next); setResult(null); if (next === "routes" && can("network_tools.routes")) await run(networkToolsClient.routes); if (next === "connections" && can("network_tools.connections")) await run(networkToolsClient.connections); }
  const permission = { ping: "network_tools.ping", traceroute: "network_tools.traceroute", dns: "network_tools.dns", port: "network_tools.port_test", http: "network_tools.http_test", routes: "network_tools.routes", connections: "network_tools.connections" }[tab];
  const execute = () => {
    if (!can(permission)) return;
    if (tab === "ping") void run(() => networkToolsClient.ping(target));
    else if (tab === "traceroute") void run(() => networkToolsClient.traceroute(target));
    else if (tab === "dns") void run(() => networkToolsClient.dns(target, recordType, dnsServer));
    else if (tab === "port") void run(() => networkToolsClient.portTest(target, port));
    else if (tab === "http") void run(() => networkToolsClient.httpTest(url));
  };
  const tabLabel = (item: Tab) => item === "port" ? tx.portTest : item === "http" ? tx.httpTest : item === "routes" ? tx.routes : item === "connections" ? tx.connections : item === "dns" ? "DNS" : item === "ping" ? "Ping" : "Traceroute";
  return <section className="security-tool-app">
    <header className="security-tool-header"><div><span className="security-tool-eyebrow">{tx.eyebrow}</span><h2><Network /> {tx.title}</h2><p>{tx.subtitle}</p></div></header>
    <nav className="security-tabs" aria-label={tx.sections}>{(["ping", "traceroute", "dns", "port", "http", "routes", "connections"] as Tab[]).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => void loadTab(item)}>{tabLabel(item)}</button>)}</nav>
    <div className="security-panel">
      {!can(permission) && <p>{tx.noPermission}</p>}
      {can(permission) && !["routes", "connections"].includes(tab) && <div className="security-form-grid">
        {tab !== "http" && <input aria-label={tx.target} value={target} onChange={(event) => setTarget(event.target.value)} placeholder={tx.hostname} />}
        {tab === "port" && <input aria-label={tx.port} type="number" min={1} max={65535} value={port} onChange={(event) => setPort(Number(event.target.value))} />}
        {tab === "dns" && <><select aria-label={tx.recordType} value={recordType} onChange={(event) => setRecordType(event.target.value)}>{["A", "AAAA", "CNAME", "MX", "TXT", "NS", "PTR"].map((type) => <option key={type}>{type}</option>)}</select><input aria-label={tx.dnsServer} value={dnsServer} onChange={(event) => setDnsServer(event.target.value)} placeholder={tx.dnsServerOptional} /></>}
        {tab === "http" && <input aria-label="URL" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/" />}
        <button className="security-action" disabled={loading} onClick={execute}><Play /> {tx.run}</button>
      </div>}
      <Result value={result} empty={tx.empty} />
    </div>
  </section>;
}
