import { useState } from "react";
import { Network, Play } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { networkToolsClient, type DiagnosticResult } from "./api/client";
import "../security-tools.css";

type Tab = "ping" | "traceroute" | "dns" | "port" | "http" | "routes" | "connections";

function Result({ value }: { value: unknown }) { return <pre>{value ? JSON.stringify(value, null, 2) : "Run a diagnostic to see results."}</pre>; }

export function NetworkToolsApp({ permissions, toast }: { permissions: readonly string[]; toast: ToastFn }) {
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
  return <section className="security-tool-app">
    <header className="security-tool-header"><div><span className="security-tool-eyebrow">Diagnostics</span><h2><Network /> Network Tools</h2><p>Typed network diagnostics with fixed command allowlists, timeouts, output limits and no web terminal.</p></div></header>
    <nav className="security-tabs" aria-label="Network Tools sections">{(["ping", "traceroute", "dns", "port", "http", "routes", "connections"] as Tab[]).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => void loadTab(item)}>{item === "port" ? "Port Test" : item === "http" ? "HTTP Test" : item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
    <div className="security-panel">
      {!can(permission) && <p>You do not have permission to run this diagnostic.</p>}
      {can(permission) && !["routes", "connections"].includes(tab) && <div className="security-form-grid">
        {tab !== "http" && <input aria-label="Target" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Hostname or IP" />}
        {tab === "port" && <input aria-label="Port" type="number" min={1} max={65535} value={port} onChange={(event) => setPort(Number(event.target.value))} />}
        {tab === "dns" && <><select aria-label="DNS record type" value={recordType} onChange={(event) => setRecordType(event.target.value)}>{["A", "AAAA", "CNAME", "MX", "TXT", "NS", "PTR"].map((type) => <option key={type}>{type}</option>)}</select><input aria-label="DNS server" value={dnsServer} onChange={(event) => setDnsServer(event.target.value)} placeholder="DNS server IP (optional)" /></>}
        {tab === "http" && <input aria-label="URL" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/" />}
        <button className="security-action" disabled={loading} onClick={execute}><Play /> Run</button>
      </div>}
      <Result value={result} />
    </div>
  </section>;
}
