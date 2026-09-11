import { Clock, Download, Plus, RefreshCw, RotateCcw, Save, Shield, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ToastFn } from "../../app/types";
import { confirmDialog } from "../../components/DialogService";
import {
  ntpManagerClient,
  type NtpAllowedNetwork,
  type NtpBackup,
  type NtpClient,
  type NtpConfiguration,
  type NtpDiagnostics,
  type NtpHistory,
  type NtpMode,
  type NtpSource,
  type NtpSourceKind,
} from "./api/client";
import "../infrastructure-managers.css";

type Props = {
  permissions: string[];
  language: string;
  toast: ToastFn;
};

type Tab = "overview" | "sources" | "server" | "clients" | "timezone" | "diagnostics" | "history" | "config";

const TAB_LABELS: Array<[Tab, string]> = [
  ["overview", "Przegląd"],
  ["sources", "Źródła czasu"],
  ["server", "Serwer NTP"],
  ["clients", "Klienci"],
  ["timezone", "Strefa czasowa"],
  ["diagnostics", "Diagnostyka"],
  ["history", "Historia"],
  ["config", "Konfiguracja"],
];

function roleLabel(mode?: NtpMode) {
  if (mode === "client") return "Client";
  if (mode === "server") return "Server";
  if (mode === "client_server") return "Client + Server";
  return "Disabled";
}

function stateLabel(state?: string) {
  return ({
    selected: "Synchronizacja",
    candidate: "Dostępny",
    outlier: "Nieużywany",
    unreachable: "Niedostępny",
    falseticker: "Błędny",
    jittery: "Niestabilny",
  } as Record<string, string>)[state || ""] || state || "Skonfigurowany";
}

export function NtpManagerApp({ permissions, toast }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const [diagnostics, setDiagnostics] = useState<NtpDiagnostics | null>(null);
  const [configuration, setConfiguration] = useState<NtpConfiguration | null>(null);
  const [draft, setDraft] = useState<NtpConfiguration | null>(null);
  const [sources, setSources] = useState<NtpSource[]>([]);
  const [clients, setClients] = useState<NtpClient[]>([]);
  const [history, setHistory] = useState<NtpHistory[]>([]);
  const [backups, setBackups] = useState<NtpBackup[]>([]);
  const [timezones, setTimezones] = useState<string[]>([]);
  const [timezoneSearch, setTimezoneSearch] = useState("");
  const [server, setServer] = useState("");
  const [sourceKind, setSourceKind] = useState<NtpSourceKind>("server");
  const [preferSource, setPreferSource] = useState(false);
  const [network, setNetwork] = useState("");
  const [networkDescription, setNetworkDescription] = useState("");
  const [testResult, setTestResult] = useState("");
  const [loading, setLoading] = useState(true);

  const canManage = permissions.includes("ntp.manage");
  const canSync = permissions.includes("ntp.sync") || permissions.includes("ntp.resync");
  const canService = permissions.includes("ntp.service.control") || permissions.includes("ntp.manage");
  const canFirewall = permissions.includes("ntp.firewall.manage");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextDiagnostics, nextConfig, nextClients, nextHistory, nextBackups] = await Promise.all([
        ntpManagerClient.dashboard(),
        ntpManagerClient.config(),
        ntpManagerClient.clients().catch(() => ({ items: [], total: 0 })),
        ntpManagerClient.history().catch(() => ({ items: [], total: 0 })),
        ntpManagerClient.backups().catch(() => ({ items: [] })),
      ]);
      setDiagnostics(nextDiagnostics);
      setSources(nextDiagnostics.sources);
      setConfiguration(nextConfig);
      setDraft(nextConfig);
      setClients(nextClients.items);
      setHistory(nextHistory.items);
      setBackups(nextBackups.items);
    } catch (error) {
      toast(error instanceof Error ? error.message : "NTP error", "error", "admin", "ntp-manager");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (tab !== "timezone") return;
    const handle = window.setTimeout(() => {
      void ntpManagerClient.timezones(timezoneSearch).then((result) => setTimezones(result.items)).catch(() => setTimezones([]));
    }, 180);
    return () => window.clearTimeout(handle);
  }, [tab, timezoneSearch]);

  async function runAction(action: () => Promise<unknown>, success?: string) {
    try {
      await action();
      if (success) toast(success, "ok", "admin", "ntp-manager");
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "NTP action failed", "error", "admin", "ntp-manager");
    }
  }

  async function addServer() {
    const value = server.trim();
    if (!value) return;
    await runAction(() => ntpManagerClient.add(value, sourceKind, preferSource), "Dodano źródło NTP");
    setServer("");
    setPreferSource(false);
  }

  async function testServer(value: string) {
    try {
      const result = await ntpManagerClient.test(value);
      setTestResult(
        result.ok
          ? `${value}: OK, stratum ${result.stratum}, offset ${result.offset_ms} ms, delay ${result.delay_ms} ms`
          : `${value}: ${result.status}`,
      );
    } catch (error) {
      setTestResult(error instanceof Error ? error.message : "Test NTP failed");
    }
  }

  function addNetwork() {
    const cidr = network.trim();
    if (!draft || !cidr) return;
    if (draft.allowed_networks.some((item) => item.cidr === cidr)) return;
    const item: NtpAllowedNetwork = { cidr, description: networkDescription.trim(), enabled: true };
    setDraft({ ...draft, allowed_networks: [...draft.allowed_networks, item] });
    setNetwork("");
    setNetworkDescription("");
  }

  async function saveConfiguration() {
    if (!draft) return;
    if (!(await confirmDialog("Zapisać konfigurację NTP i zrestartować usługę?", (key) => key))) return;
    const payload = {
      mode: draft.mode,
      sources: draft.sources.map((item) => ({
        server: item.server,
        kind: item.kind || "server",
        prefer: Boolean(item.prefer),
        enabled: item.enabled !== false,
        confirm: false,
      })),
      allowed_networks: draft.allowed_networks,
      local_time_when_unsynced: draft.local_time_when_unsynced,
      local_stratum: draft.local_stratum,
    };
    await runAction(() => ntpManagerClient.saveConfig(payload), "Konfiguracja NTP została zapisana");
  }

  const selectedSource = useMemo(() => sources.find((source) => source.selected), [sources]);

  return (
    <div className="infra-manager-app">
      <header className="infra-manager-header">
        <div className="infra-manager-title">
          <Clock />
          <div>
            <h2>NTP Manager</h2>
            <p>Synchronizacja czasu, klient i serwer NTP, chrony, strefa czasowa, firewall i diagnostyka.</p>
          </div>
        </div>
        <div className="infra-manager-actions">
          {canSync && (
            <button
              type="button"
              onClick={async () => {
                if (await confirmDialog("Wymusić synchronizację? Czas systemowy może zmienić się skokowo i wpłynąć na logi, bazy danych oraz Kerberos.", (key) => key)) {
                  void runAction(ntpManagerClient.sync, "Uruchomiono synchronizację czasu");
                }
              }}
            >
              <RotateCcw /> Synchronizuj teraz
            </button>
          )}
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={loading ? "spin" : ""} /> Odśwież
          </button>
        </div>
      </header>

      <div className="infra-manager-toolbar">
        {TAB_LABELS.map(([id, label]) => (
          <button key={id} type="button" className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === "overview" && (
        <>
          <div className="infra-stat-grid">
            <div className="infra-stat"><strong>{diagnostics?.synchronized ? "OK" : "Brak synchronizacji"}</strong><small>Synchronizacja</small></div>
            <div className="infra-stat"><strong>{roleLabel(diagnostics?.role)}</strong><small>Tryb</small></div>
            <div className="infra-stat"><strong>{diagnostics?.backend || "none"}</strong><small>Backend</small></div>
            <div className="infra-stat"><strong>{selectedSource?.server || diagnostics?.source || "—"}</strong><small>Źródło czasu</small></div>
            <div className="infra-stat"><strong>{diagnostics?.stratum ?? "—"}</strong><small>Stratum</small></div>
            <div className="infra-stat"><strong>{diagnostics?.offset || "—"}</strong><small>Offset</small></div>
            <div className="infra-stat"><strong>{diagnostics?.timezone || "—"}</strong><small>Strefa czasowa</small></div>
            <div className="infra-stat"><strong>{diagnostics?.service_state || "—"}</strong><small>{diagnostics?.service || "Usługa"}</small></div>
            <div className="infra-stat"><strong>{diagnostics?.summary.source_count ?? 0}</strong><small>Źródła</small></div>
            <div className="infra-stat"><strong>{diagnostics?.summary.client_count ?? 0}</strong><small>Klienci</small></div>
            <div className="infra-stat"><strong>{diagnostics?.firewall?.status || "unknown"}</strong><small>UDP/123</small></div>
            <div className="infra-stat"><strong>{diagnostics?.health || "—"}</strong><small>Stan</small></div>
          </div>
          {configuration?.unmanaged_config_detected && (
            <div className="infra-manager-toolbar"><strong>Wykryto istniejącą konfigurację NTP.</strong><span>WebNAS nie przejmuje jej automatycznie; zarządza wyłącznie własnym blokiem/plikiem.</span></div>
          )}
          {diagnostics?.warnings.length ? <div className="infra-manager-toolbar"><span>{diagnostics.warnings.join("; ")}</span></div> : null}
        </>
      )}

      {tab === "sources" && (
        <>
          {canManage && (
            <div className="infra-manager-toolbar">
              <input aria-label="NTP server" placeholder="time.cloudflare.com" value={server} onChange={(event) => setServer(event.target.value)} />
              <select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as NtpSourceKind)}>
                <option value="server">server</option><option value="pool">pool</option>
              </select>
              <label><input type="checkbox" checked={preferSource} onChange={(event) => setPreferSource(event.target.checked)} /> Preferowane</label>
              <button type="button" onClick={() => void addServer()} disabled={!server.trim()}><Plus /> Dodaj</button>
            </div>
          )}
          {testResult && <div className="infra-manager-toolbar"><span>{testResult}</span></div>}
          <div className="infra-table-wrap">
            <table className="infra-table"><thead><tr><th>Serwer</th><th>Status</th><th>Typ</th><th>Stratum</th><th>Poll</th><th>Reach</th><th>Last RX</th><th>Offset</th><th>Akcje</th></tr></thead>
              <tbody>{sources.map((source) => (
                <tr key={`${source.server}-${source.kind || source.mode || "source"}`}>
                  <td>{source.server}</td><td>{stateLabel(source.state)}</td><td>{source.kind || source.mode || "server"}</td><td>{source.stratum ?? "—"}</td><td>{source.poll ?? "—"}</td><td>{source.reach ?? "—"}</td><td>{source.last_rx || "—"}</td><td>{source.offset || "—"}</td>
                  <td><div className="infra-row-actions"><button type="button" onClick={() => void testServer(source.server)}>Test</button>{canManage && <button type="button" onClick={async () => { if (await confirmDialog(`Usunąć ${source.server}?`, (key) => key)) void runAction(() => ntpManagerClient.remove(source.server)); }}><Trash2 /> Usuń</button>}</div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}

      {tab === "server" && draft && (
        <>
          <div className="infra-manager-toolbar">
            <label>Tryb NTP <select disabled={!canManage} value={draft.mode} onChange={(event) => setDraft({ ...draft, mode: event.target.value as NtpMode })}>
              <option value="disabled">Wyłączony</option><option value="client">Klient NTP</option><option value="server">Serwer NTP</option><option value="client_server">Klient + Serwer NTP</option>
            </select></label>
            <span>Tryb Client + Server jest zalecany dla typowego serwera LAN.</span>
          </div>
          <div className="infra-manager-toolbar">
            <input placeholder="192.168.10.0/24" value={network} onChange={(event) => setNetwork(event.target.value)} disabled={!canManage} />
            <input placeholder="Opis, np. VLAN Servers" value={networkDescription} onChange={(event) => setNetworkDescription(event.target.value)} disabled={!canManage} />
            {canManage && <button type="button" onClick={addNetwork}><Plus /> Dodaj sieć</button>}
          </div>
          <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>Sieć</th><th>Opis</th><th>Aktywna</th><th>Akcja</th></tr></thead><tbody>
            {draft.allowed_networks.map((item, index) => <tr key={item.cidr}><td>{item.cidr}</td><td>{item.description || "—"}</td><td><input type="checkbox" checked={item.enabled} disabled={!canManage} onChange={(event) => setDraft({ ...draft, allowed_networks: draft.allowed_networks.map((row, rowIndex) => rowIndex === index ? { ...row, enabled: event.target.checked } : row) })} /></td><td>{canManage && <button type="button" onClick={() => setDraft({ ...draft, allowed_networks: draft.allowed_networks.filter((_, rowIndex) => rowIndex !== index) })}><Trash2 /> Usuń</button>}</td></tr>)}
          </tbody></table></div>
          <div className="infra-manager-toolbar">
            <label><input type="checkbox" checked={draft.local_time_when_unsynced} disabled={!canManage} onChange={(event) => setDraft({ ...draft, local_time_when_unsynced: event.target.checked })} /> Udostępniaj lokalny czas, gdy upstream jest niedostępny</label>
            <label>Local stratum <input type="number" min={1} max={15} value={draft.local_stratum} disabled={!canManage || !draft.local_time_when_unsynced} onChange={(event) => setDraft({ ...draft, local_stratum: Number(event.target.value) })} /></label>
            <span>Ta opcja może udostępniać czas mimo braku synchronizacji z wiarygodnym źródłem.</span>
          </div>
          <div className="infra-manager-toolbar"><Shield /><span>UDP/123: {diagnostics?.firewall?.status || "unknown"} ({diagnostics?.firewall?.backend || "none"})</span>{canFirewall && diagnostics?.firewall?.status !== "open" && <button type="button" onClick={async () => { if (await confirmDialog("Otworzyć UDP/123 w wykrytym firewallu?", (key) => key)) void runAction(ntpManagerClient.openFirewall); }}>Otwórz UDP/123</button>}</div>
          {canManage && <div className="infra-manager-toolbar"><button type="button" onClick={() => void saveConfiguration()}><Save /> Zapisz konfigurację serwera</button></div>}
        </>
      )}

      {tab === "clients" && (
        <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>IP</th><th>Hostname</th><th>Zapytania NTP</th><th>Dropped</th><th>Ostatnia aktywność</th></tr></thead><tbody>
          {clients.map((client) => <tr key={client.address}><td>{client.address}</td><td>{client.hostname || "—"}</td><td>{client.ntp_requests}</td><td>{client.dropped}</td><td>{client.last_activity || "—"}</td></tr>)}
        </tbody></table></div>
      )}

      {tab === "timezone" && (
        <>
          <div className="infra-manager-toolbar"><strong>Aktualna: {diagnostics?.timezone || "—"}</strong><input placeholder="Szukaj strefy czasowej" value={timezoneSearch} onChange={(event) => setTimezoneSearch(event.target.value)} /></div>
          <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>Strefa czasowa</th><th>Akcja</th></tr></thead><tbody>
            {timezones.map((timezone) => <tr key={timezone}><td>{timezone}</td><td>{canManage && <button type="button" disabled={timezone === diagnostics?.timezone} onClick={async () => { if (await confirmDialog(`Ustawić strefę ${timezone}?`, (key) => key)) void runAction(() => ntpManagerClient.setTimezone(timezone)); }}>Ustaw</button>}</td></tr>)}
          </tbody></table></div>
        </>
      )}

      {tab === "diagnostics" && (
        <DiagnosticsPanel initial={diagnostics} toast={toast} />
      )}

      {tab === "history" && (
        <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>Czas</th><th>Źródło</th><th>Stratum</th><th>Offset</th><th>Synchronizacja</th></tr></thead><tbody>
          {[...history].reverse().map((item) => <tr key={`${item.timestamp}-${item.server}`}><td>{new Date(item.timestamp * 1000).toLocaleString()}</td><td>{item.server || "—"}</td><td>{item.stratum ?? "—"}</td><td>{item.offset || "—"}</td><td>{item.synchronized ? "OK" : "Nie"}</td></tr>)}
        </tbody></table></div>
      )}

      {tab === "config" && draft && (
        <>
          <div className="infra-manager-toolbar"><span>Plik zarządzany przez WebNAS: <code>{draft.managed_path || "—"}</code></span></div>
          <div className="infra-manager-toolbar">
            {canService && <><button type="button" onClick={() => void runAction(() => ntpManagerClient.service("start"))}>Start</button><button type="button" onClick={() => void runAction(() => ntpManagerClient.service("stop"))}>Stop</button><button type="button" onClick={() => void runAction(() => ntpManagerClient.service("restart"))}>Restart NTP</button></>}
            {canManage && draft.backend !== "chrony" && <button type="button" onClick={async () => { if (await confirmDialog("Zainstalować Chrony przez systemowy package manager?", (key) => key)) void runAction(ntpManagerClient.installChrony); }}><Download /> Zainstaluj Chrony</button>}
          </div>
          <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>Backup</th><th>Data</th><th>Użytkownik</th><th>Zmiana</th><th>Plik</th><th>Akcja</th></tr></thead><tbody>
            {backups.map((backup) => <tr key={backup.id}><td>{backup.id}</td><td>{new Date(backup.timestamp * 1000).toLocaleString()}</td><td>{backup.actor}</td><td>{backup.change}</td><td>{backup.path}</td><td>{canManage && <button type="button" onClick={async () => { if (await confirmDialog(`Przywrócić backup ${backup.id}?`, (key) => key)) void runAction(() => ntpManagerClient.restoreBackup(backup.id)); }}>Przywróć</button>}</td></tr>)}
          </tbody></table></div>
        </>
      )}
    </div>
  );
}

function DiagnosticsPanel({ initial, toast }: { initial: NtpDiagnostics | null; toast: ToastFn }) {
  const [data, setData] = useState<NtpDiagnostics | null>(initial);
  const [details, setDetails] = useState(false);

  useEffect(() => { setData(initial); }, [initial]);

  async function reload() {
    try { setData(await ntpManagerClient.diagnostics()); }
    catch (error) { toast(error instanceof Error ? error.message : "Diagnostics failed", "error", "admin", "ntp-manager"); }
  }

  return <>
    <div className="infra-manager-toolbar"><button type="button" onClick={() => void reload()}><RefreshCw /> Uruchom diagnostykę</button><button type="button" onClick={() => setDetails((value) => !value)}>{details ? "Ukryj szczegóły" : "Pokaż szczegóły"}</button></div>
    <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>Test</th><th>Status</th><th>Szczegóły</th></tr></thead><tbody>
      {(data?.checks || []).map((check) => <tr key={check.code}><td>{check.code}</td><td>{check.status}</td><td>{check.detail}</td></tr>)}
    </tbody></table></div>
    {details && <div className="infra-table-wrap"><table className="infra-table"><tbody>{Object.entries(data?.metrics || {}).map(([key, value]) => <tr key={key}><th>{key}</th><td>{String(value ?? "—")}</td></tr>)}</tbody></table></div>}
  </>;
}
