import { Activity, ArrowDown, ArrowUp, Check, Clock, Download, Globe, History, LayoutDashboard, LoaderCircle, LockKeyhole, Plus, Radio, RefreshCw, RotateCcw, Save, Server, Settings, Shield, Trash2, Users, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { ToastFn } from "../../app/types";
import { confirmDialog } from "../../components/DialogService";
import { DataTable } from "../../components/ui/DataTable";
import { ntpManagerClient, type NtpBackup, type NtpClient, type NtpConfiguration, type NtpDiagnostics, type NtpHistory, type NtpMode, type NtpSource, type NtpSourceKind } from "./api/client";
import { NtpOverview } from "./NtpOverview";
import { backendLabel, firewallLabel, formatTimestamp, sourceStateLabel, type NtpSection } from "./presentation";
import "./ntp-manager.css";

type Props = { permissions: string[]; language: string; toast: ToastFn };
const SECTIONS: Array<{ id: NtpSection; label: string; icon: ReactNode; description: string }> = [
  { id: "overview", label: "Przegląd", icon: <LayoutDashboard />, description: "Stan zegara, źródeł czasu i usługi NTP." },
  { id: "sources", label: "Źródła czasu", icon: <Radio />, description: "Serwery i pule NTP, ich dostępność oraz kolejność użycia." },
  { id: "server", label: "Serwer NTP", icon: <Server />, description: "Tryb pracy, dozwolone sieci i udostępnianie czasu w sieci lokalnej." },
  { id: "clients", label: "Klienci", icon: <Users />, description: "Urządzenia korzystające z tego serwera czasu." },
  { id: "timezone", label: "Strefa czasowa", icon: <Globe />, description: "Strefa czasowa systemu operacyjnego." },
  { id: "diagnostics", label: "Diagnostyka", icon: <Activity />, description: "Testy usługi, łączności i jakości synchronizacji." },
  { id: "history", label: "Historia", icon: <History />, description: "Zapisane pomiary synchronizacji, od najnowszych." },
  { id: "config", label: "Konfiguracja", icon: <Settings />, description: "Obsługa usługi NTP i przywracanie kopii konfiguracji." },
];
const errorMessage = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback;
const sourceKey = (source: NtpSource) => source.server;

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="ntp-panel"><div className="ntp-panel-heading"><h3>{title}</h3></div>{children}</section>;
}

export function NtpManagerApp({ permissions, language, toast }: Props) {
  const [tab, setTab] = useState<NtpSection>("overview");
  const [diagnostics, setDiagnostics] = useState<NtpDiagnostics | null>(null);
  const [configuration, setConfiguration] = useState<NtpConfiguration | null>(null);
  const [draft, setDraft] = useState<NtpConfiguration | null>(null);
  const [sources, setSources] = useState<NtpSource[]>([]);
  const [clients, setClients] = useState<NtpClient[]>([]);
  const [history, setHistory] = useState<NtpHistory[]>([]);
  const [backups, setBackups] = useState<NtpBackup[]>([]);
  const [timezones, setTimezones] = useState<string[]>([]);
  const [timezoneSearch, setTimezoneSearch] = useState("");
  const [timezoneLoading, setTimezoneLoading] = useState(false);
  const [timezoneError, setTimezoneError] = useState("");
  const [server, setServer] = useState("");
  const [sourceKind, setSourceKind] = useState<NtpSourceKind>("server");
  const [preferSource, setPreferSource] = useState(false);
  const [editingSource, setEditingSource] = useState<string | null>(null);
  const [sourceDraft, setSourceDraft] = useState<NtpSource | null>(null);
  const [network, setNetwork] = useState("");
  const [networkDescription, setNetworkDescription] = useState("");
  const [testResult, setTestResult] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const actionRunning = useRef(false);
  const refreshId = useRef(0);
  const contentRef = useRef<HTMLDivElement>(null);

  const canManage = permissions.includes("ntp.manage");
  const canSync = permissions.includes("ntp.sync") || permissions.includes("ntp.resync");
  const canService = permissions.includes("ntp.service.control") || canManage;
  const canFirewall = permissions.includes("ntp.firewall.manage");
  const section = SECTIONS.find((item) => item.id === tab)!;

  const refresh = useCallback(async () => {
    const id = ++refreshId.current;
    setLoading(true);
    setLoadError("");
    try {
      const [nextDiagnostics, nextConfig, extra] = await Promise.all([
        ntpManagerClient.dashboard(), ntpManagerClient.config(),
        Promise.allSettled([ntpManagerClient.clients(), ntpManagerClient.history(), ntpManagerClient.backups()]),
      ]);
      if (id !== refreshId.current) return;
      const managedKeys = new Set(nextConfig.sources.map(sourceKey));
      const mergedSources = nextConfig.sources.map((configured) => ({ ...nextDiagnostics.sources.find((item) => item.server === configured.server), ...configured }));
      mergedSources.push(...nextDiagnostics.sources.filter((item) => !managedKeys.has(sourceKey(item))));
      setDiagnostics(nextDiagnostics);
      setSources(mergedSources);
      setConfiguration(nextConfig);
      // Status refreshes and source edits must not silently discard the server form.
      setDraft((current) => dirtyRef.current && current ? { ...nextConfig, mode: current.mode, allowed_networks: current.allowed_networks, local_time_when_unsynced: current.local_time_when_unsynced, local_stratum: current.local_stratum } : nextConfig);
      setClients(extra[0].status === "fulfilled" ? extra[0].value.items : []);
      setHistory(extra[1].status === "fulfilled" ? extra[1].value.items : []);
      setBackups(extra[2].status === "fulfilled" ? extra[2].value.items : []);
      setUnavailable(extra.flatMap((result, index) => result.status === "rejected" ? [["clients", "history", "config"][index]] : []));
    } catch (error) {
      if (id !== refreshId.current) return;
      const message = errorMessage(error, "Nie udało się pobrać danych NTP");
      setLoadError(message);
      toast(message, "error", "admin", "ntp-manager");
    } finally {
      if (id === refreshId.current) setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
    return () => { refreshId.current += 1; };
  }, [refresh]);

  useEffect(() => {
    if (tab !== "timezone") return;
    let active = true;
    setTimezoneLoading(true);
    setTimezoneError("");
    const handle = window.setTimeout(() => {
      void ntpManagerClient.timezones(timezoneSearch).then((result) => {
        if (active) setTimezones(result.items);
      }).catch((error: unknown) => {
        if (active) { setTimezones([]); setTimezoneError(errorMessage(error, "Nie udało się pobrać stref czasowych")); }
      }).finally(() => { if (active) setTimezoneLoading(false); });
    }, 180);
    return () => { active = false; window.clearTimeout(handle); };
  }, [tab, timezoneSearch]);

  function selectSection(next: NtpSection) {
    setTab(next);
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }

  function editConfiguration(next: NtpConfiguration) {
    dirtyRef.current = true;
    setDirty(true);
    setDraft(next);
  }

  async function runAction(action: () => Promise<unknown>, success?: string, resetDraft = false) {
    if (actionRunning.current) return false;
    actionRunning.current = true;
    setBusy(true);
    try {
      await action();
      if (resetDraft) { dirtyRef.current = false; setDirty(false); }
      if (success) toast(success, "ok", "admin", "ntp-manager");
      await refresh();
      return true;
    } catch (error) {
      toast(errorMessage(error, "Nie udało się wykonać operacji NTP"), "error", "admin", "ntp-manager");
      return false;
    } finally {
      actionRunning.current = false;
      setBusy(false);
    }
  }

  async function confirmedAction(message: string, action: () => Promise<unknown>, success?: string) {
    if (await confirmDialog(message, (key) => key)) await runAction(action, success);
  }

  async function addServer() {
    const value = server.trim();
    if (!value) return;
    if (await runAction(() => ntpManagerClient.add(value, sourceKind, preferSource), "Dodano źródło NTP")) {
      setServer(""); setPreferSource(false);
    }
  }

  async function testServer(value: string) {
    if (actionRunning.current) return;
    actionRunning.current = true;
    setBusy(true);
    try {
      const result = await ntpManagerClient.test(value);
      setTestResult(result.ok ? `${value}: OK, stratum ${result.stratum ?? "—"}, offset ${result.offset_ms ?? "—"} ms, delay ${result.delay_ms} ms` : `${value}: ${result.status}`);
    } catch (error) { setTestResult(errorMessage(error, "Test NTP nie powiódł się")); }
    finally { actionRunning.current = false; setBusy(false); }
  }

  async function saveSourceEdit() {
    if (!editingSource || !sourceDraft) return;
    const original = configuration?.sources.find((item) => sourceKey(item) === editingSource);
    if (!original) return;
    if (await runAction(() => ntpManagerClient.update(original.server, sourceDraft), "Zaktualizowano źródło NTP")) {
      setEditingSource(null); setSourceDraft(null);
    }
  }

  async function toggleSource(source: NtpSource) {
    const configured = configuration?.sources.find((item) => sourceKey(item) === sourceKey(source));
    if (configured) await runAction(() => ntpManagerClient.update(configured.server, { ...configured, enabled: configured.enabled === false }), "Zmieniono stan źródła NTP");
  }

  async function moveSource(source: NtpSource, delta: -1 | 1) {
    if (!configuration) return;
    const ordered = [...configuration.sources];
    const index = ordered.findIndex((item) => sourceKey(item) === sourceKey(source));
    const nextIndex = index + delta;
    if (index < 0 || nextIndex < 0 || nextIndex >= ordered.length) return;
    const [item] = ordered.splice(index, 1);
    ordered.splice(nextIndex, 0, item);
    await runAction(() => ntpManagerClient.replaceSources(ordered), "Zmieniono kolejność źródeł NTP");
  }

  function addNetwork() {
    const cidr = network.trim();
    if (!draft || !cidr || draft.allowed_networks.some((item) => item.cidr === cidr)) return;
    editConfiguration({ ...draft, allowed_networks: [...draft.allowed_networks, { cidr, description: networkDescription.trim(), enabled: true }] });
    setNetwork(""); setNetworkDescription("");
  }

  async function saveConfiguration() {
    if (!draft || !(await confirmDialog("Zapisać konfigurację NTP i zrestartować usługę?", (key) => key))) return;
    const payload = {
      mode: draft.mode,
      sources: draft.sources.map((item) => ({ server: item.server, kind: item.kind || "server", prefer: Boolean(item.prefer), enabled: item.enabled !== false, confirm: false })),
      allowed_networks: draft.allowed_networks,
      local_time_when_unsynced: draft.local_time_when_unsynced,
      local_stratum: draft.local_stratum,
    };
    await runAction(() => ntpManagerClient.saveConfig(payload), "Konfiguracja NTP została zapisana", true);
  }

  function sourceEditor(source: NtpSource) {
    if (editingSource !== sourceKey(source) || !sourceDraft) return <div className="ntp-source-cell"><strong>{source.server}</strong><div className="ntp-tags"><span>{source.kind || "server"}</span>{source.prefer && <span>Preferowane</span>}{source.enabled === false && <span>Wyłączone</span>}</div></div>;
    return <div className="ntp-source-editor">
      <label>Adres<input aria-label="Edytuj serwer NTP" value={sourceDraft.server} onChange={(event) => setSourceDraft({ ...sourceDraft, server: event.target.value })} /></label>
      <label>Typ<select aria-label="Edytuj typ źródła NTP" value={sourceDraft.kind || "server"} onChange={(event) => setSourceDraft({ ...sourceDraft, kind: event.target.value as NtpSourceKind })}><option value="server">Serwer</option><option value="pool">Pula</option></select></label>
      <label className="ntp-check"><input type="checkbox" checked={sourceDraft.enabled !== false} onChange={(event) => setSourceDraft({ ...sourceDraft, enabled: event.target.checked })} />Włączone</label>
      <label className="ntp-check"><input type="checkbox" checked={Boolean(sourceDraft.prefer)} onChange={(event) => setSourceDraft({ ...sourceDraft, prefer: event.target.checked })} />Preferowane</label>
    </div>;
  }

  function sourceActions(source: NtpSource) {
    const index = configuration?.sources.findIndex((item) => sourceKey(item) === sourceKey(source)) ?? -1;
    const editing = editingSource === sourceKey(source);
    return <div className="ntp-row-actions">
      <button type="button" onClick={() => void testServer(source.server)}>Test</button>
      {canManage && index >= 0 && (editing ? <>
        <button type="button" disabled={!sourceDraft?.server.trim()} onClick={() => void saveSourceEdit()}><Check aria-hidden="true" />Zapisz</button>
        <button type="button" onClick={() => { setEditingSource(null); setSourceDraft(null); }}><X aria-hidden="true" />Anuluj</button>
      </> : <>
        <button type="button" onClick={() => { setEditingSource(sourceKey(source)); setSourceDraft({ ...source, kind: source.kind || "server", enabled: source.enabled !== false }); }}>Edytuj</button>
        <button type="button" onClick={() => void toggleSource(source)}>{source.enabled === false ? "Włącz" : "Wyłącz"}</button>
        <button type="button" aria-label={`Przesuń ${source.server} w górę`} disabled={index <= 0} onClick={() => void moveSource(source, -1)}><ArrowUp aria-hidden="true" /></button>
        <button type="button" aria-label={`Przesuń ${source.server} w dół`} disabled={index >= (configuration?.sources.length ?? 0) - 1} onClick={() => void moveSource(source, 1)}><ArrowDown aria-hidden="true" /></button>
        <button type="button" className="ntp-danger" onClick={() => void confirmedAction(`Usunąć ${source.server}?`, () => ntpManagerClient.remove(source.server))}><Trash2 aria-hidden="true" />Usuń</button>
      </>)}
      {index < 0 && <span className="ntp-muted">Tylko odczyt</span>}
    </div>;
  }

  return <section className="ntp-manager-app" aria-label="NTP Manager">
    <header className="ntp-header">
      <div className="ntp-brand"><div className="ntp-brand-icon"><Clock aria-hidden="true" /></div><div><span className="ntp-eyebrow">System i sieć</span><h2>NTP Manager</h2><p>Synchronizacja czasu i serwer NTP</p></div></div>
      <div className="ntp-header-actions">
        {canSync && <button type="button" className="ntp-primary" disabled={loading || busy || !diagnostics?.available || diagnostics.role === "disabled"} onClick={() => void confirmedAction("Wymusić synchronizację? Czas systemowy może zmienić się skokowo i wpłynąć na logi, bazy danych oraz Kerberos.", ntpManagerClient.sync, "Uruchomiono synchronizację czasu")}><RotateCcw aria-hidden="true" />Synchronizuj teraz</button>}
        <button type="button" disabled={loading || busy} onClick={() => void refresh()}><RefreshCw className={loading ? "ntp-spin" : ""} aria-hidden="true" />Odśwież</button>
      </div>
    </header>
    <div className="ntp-layout">
      <nav className="ntp-navigation" aria-label="Sekcje NTP Manager">
        <span className="ntp-navigation-label">Zarządzanie czasem</span>
        {SECTIONS.map((item) => <button key={item.id} type="button" aria-current={tab === item.id ? "page" : undefined} onClick={() => selectSection(item.id)}><span aria-hidden="true">{item.icon}</span><span>{item.label}</span>{item.id === "sources" && diagnostics && <span className="ntp-navigation-count">{sources.length}</span>}</button>)}
        {!canManage && <div className="ntp-readonly"><LockKeyhole aria-hidden="true" /><span>Konfiguracja tylko do odczytu</span></div>}
      </nav>
      <div className="ntp-content" ref={contentRef}>
        {tab !== "overview" && <div className="ntp-section-heading"><h2>{section.label}</h2><p>{section.description}</p></div>}
        {loadError && <div className="ntp-notice ntp-tone-warning" role="alert"><Activity aria-hidden="true" /><div><strong>Nie udało się odświeżyć danych</strong><p>{loadError}</p>{diagnostics && <p>Wyświetlane są dane z poprzedniego odczytu.</p>}<button type="button" onClick={() => void refresh()} disabled={loading || busy}>Spróbuj ponownie</button></div></div>}
        {!diagnostics && loading && <div className="ntp-loading" role="status"><LoaderCircle className="ntp-spin" aria-hidden="true" /><strong>Wczytywanie stanu NTP…</strong><span>Pobieranie konfiguracji i danych synchronizacji</span></div>}
        {diagnostics && <>
          {busy && <div className="ntp-operation-status" role="status"><LoaderCircle className="ntp-spin" aria-hidden="true" />Trwa wykonywanie operacji…</div>}
          {loading && !busy && <div className="ntp-operation-status" role="status">Odświeżanie danych…</div>}
          <fieldset className="ntp-operation-scope" disabled={loading || busy} aria-label="Operacje NTP">
            {tab === "overview" && <NtpOverview data={diagnostics} configuration={configuration} sources={sources} language={language} onSection={selectSection} />}
            {tab === "sources" && <>
              {canManage && <Panel title="Dodaj źródło czasu"><form className="ntp-source-form" onSubmit={(event) => { event.preventDefault(); void addServer(); }}>
                <label>Adres źródła<input aria-label="Adres źródła NTP" placeholder="time.cloudflare.com" value={server} onChange={(event) => setServer(event.target.value)} /></label>
                <label>Typ<select aria-label="Typ nowego źródła NTP" value={sourceKind} onChange={(event) => setSourceKind(event.target.value as NtpSourceKind)}><option value="server">Serwer</option><option value="pool">Pula serwerów</option></select></label>
                <label className="ntp-check"><input type="checkbox" checked={preferSource} onChange={(event) => setPreferSource(event.target.checked)} />Preferowane</label>
                <button type="submit" className="ntp-primary" disabled={!server.trim()}><Plus aria-hidden="true" />Dodaj źródło</button>
              </form></Panel>}
              {testResult && <div className="ntp-notice" role="status"><Activity aria-hidden="true" /><span>{testResult}</span></div>}
              <DataTable rows={sources} getRowId={(source) => `${source.server}-${source.kind || source.mode || "source"}`} ariaLabel="Źródła czasu NTP" emptyTitle="Brak źródeł czasu" emptyDescription="Nie ma jeszcze skonfigurowanych ani wykrytych źródeł NTP." actionsLabel="Akcje" actions={sourceActions} columns={[
                { key: "server", header: "Źródło", render: sourceEditor },
                { key: "state", header: "Stan", render: (source) => <><span className={`ntp-badge ${source.selected ? "ntp-tone-success" : ""}`}>{source.enabled === false ? "Wyłączone" : sourceStateLabel(source.state)}</span>{!configuration?.sources.some((item) => sourceKey(item) === sourceKey(source)) && <small className="ntp-muted">Konfiguracja zewnętrzna</small>}</> },
                { key: "stratum", header: "Stratum", render: (source) => source.stratum ?? "—" },
                { key: "poll", header: "Poll / Reach", render: (source) => `${source.poll ?? "—"} / ${source.reach ?? "—"}` },
                { key: "last", header: "Ostatni odbiór", render: (source) => source.last_rx || "—" },
                { key: "offset", header: "Offset", render: (source) => source.offset || "—" },
              ]} />
            </>}
            {tab === "server" && draft && <>
              <Panel title="Tryb pracy"><div className="ntp-form-grid"><label>Tryb NTP<select disabled={!canManage} value={draft.mode} onChange={(event) => editConfiguration({ ...draft, mode: event.target.value as NtpMode })}><option value="disabled">Wyłączony</option><option value="client">Klient NTP</option><option value="server">Serwer NTP</option><option value="client_server">Klient + serwer NTP</option></select></label><p className="ntp-field-help">Tryb klient + serwer pobiera czas ze źródeł zewnętrznych i udostępnia go urządzeniom w sieci lokalnej.</p></div></Panel>
              <Panel title="Dozwolone sieci">
                {canManage && <form className="ntp-network-form" onSubmit={(event) => { event.preventDefault(); addNetwork(); }}><label>Sieć CIDR<input placeholder="192.168.10.0/24" value={network} onChange={(event) => setNetwork(event.target.value)} /></label><label>Opis sieci<input placeholder="np. VLAN Servers" value={networkDescription} onChange={(event) => setNetworkDescription(event.target.value)} /></label><button type="submit" disabled={!network.trim()}><Plus aria-hidden="true" />Dodaj sieć</button></form>}
                <DataTable rows={draft.allowed_networks} getRowId={(item) => item.cidr} ariaLabel="Dozwolone sieci NTP" emptyTitle="Brak dozwolonych sieci" emptyDescription="Dodaj sieci, którym serwer ma udostępniać czas." actionsLabel="Akcje" columns={[
                  { key: "cidr", header: "Sieć", render: (item) => <code>{item.cidr}</code> }, { key: "description", header: "Opis", render: (item) => item.description || "—" },
                  { key: "enabled", header: "Aktywna", render: (item) => <input type="checkbox" aria-label={`Aktywna sieć ${item.cidr}`} checked={item.enabled} disabled={!canManage} onChange={(event) => editConfiguration({ ...draft, allowed_networks: draft.allowed_networks.map((row) => row.cidr === item.cidr ? { ...row, enabled: event.target.checked } : row) })} /> },
                ]} actions={canManage ? (item) => <button type="button" className="ntp-danger" onClick={() => editConfiguration({ ...draft, allowed_networks: draft.allowed_networks.filter((row) => row.cidr !== item.cidr) })}><Trash2 aria-hidden="true" />Usuń</button> : undefined} />
              </Panel>
              <Panel title="Zachowanie przy braku synchronizacji"><div className="ntp-form-grid"><label className="ntp-check"><input type="checkbox" checked={draft.local_time_when_unsynced} disabled={!canManage} onChange={(event) => editConfiguration({ ...draft, local_time_when_unsynced: event.target.checked })} />Udostępniaj lokalny czas, gdy źródła są niedostępne</label><label>Lokalny stratum<input type="number" min={1} max={15} value={draft.local_stratum} disabled={!canManage || !draft.local_time_when_unsynced} onChange={(event) => editConfiguration({ ...draft, local_stratum: Number(event.target.value) })} /></label></div><p className="ntp-field-help">Ta opcja może udostępniać czas mimo braku synchronizacji z wiarygodnym źródłem.</p></Panel>
              <div className="ntp-notice"><Shield aria-hidden="true" /><div><strong>Zapora sieciowa · UDP/123</strong><p>{firewallLabel(diagnostics.firewall?.status)} · {backendLabel(diagnostics.firewall?.backend)}</p>{canFirewall && diagnostics.firewall?.status !== "open" && <button type="button" onClick={() => void confirmedAction("Otworzyć UDP/123 w wykrytym firewallu?", ntpManagerClient.openFirewall)}>Otwórz UDP/123</button>}</div></div>
              {canManage && <div className="ntp-save-bar"><span>{dirty ? "Masz niezapisane zmiany" : "Konfiguracja jest aktualna"}</span><div className="ntp-row-actions">{dirty && <button type="button" onClick={() => { setDraft(configuration); dirtyRef.current = false; setDirty(false); }}>Cofnij zmiany</button>}<button type="button" className="ntp-primary" onClick={() => void saveConfiguration()}><Save aria-hidden="true" />Zapisz konfigurację serwera</button></div></div>}
            </>}
            {tab === "clients" && <DataTable rows={clients} getRowId={(client) => client.address} ariaLabel="Klienci NTP" emptyTitle={unavailable.includes("clients") ? "Nie udało się pobrać klientów" : "Brak klientów NTP"} emptyDescription={unavailable.includes("clients") ? "Użyj Odśwież, aby ponowić odczyt." : "Klienci pojawią się po wysłaniu zapytań do tego serwera."} columns={[
              { key: "ip", header: "Adres IP", render: (client) => <code>{client.address}</code> }, { key: "host", header: "Nazwa hosta", render: (client) => client.hostname || "—" }, { key: "requests", header: "Zapytania NTP", render: (client) => client.ntp_requests }, { key: "dropped", header: "Odrzucone", render: (client) => client.dropped }, { key: "last", header: "Ostatnia aktywność", render: (client) => client.last_activity || "—" },
            ]} />}
            {tab === "timezone" && <>
              <Panel title="Strefa systemowa"><div className="ntp-form-grid"><div className="ntp-current-timezone"><Globe aria-hidden="true" /><span>Aktualna strefa<strong>{diagnostics.timezone || "Brak danych"}</strong></span></div><label>Szukaj strefy czasowej<input type="search" placeholder="np. Europe/Warsaw" value={timezoneSearch} onChange={(event) => setTimezoneSearch(event.target.value)} /></label></div></Panel>
              {timezoneError && <div className="ntp-notice ntp-tone-warning" role="alert">{timezoneError}</div>}
              <DataTable rows={timezones} getRowId={(timezone) => timezone} ariaLabel="Strefy czasowe" loading={timezoneLoading} loadingLabel="Wczytywanie stref…" emptyTitle={timezoneError ? "Lista stref jest niedostępna" : "Nie znaleziono stref czasowych"} actionsLabel="Akcje" columns={[{ key: "timezone", header: "Strefa czasowa", render: (timezone) => timezone }]} actions={canManage ? (timezone) => <button type="button" disabled={timezone === diagnostics.timezone} onClick={() => void confirmedAction(`Ustawić strefę ${timezone}?`, () => ntpManagerClient.setTimezone(timezone))}>{timezone === diagnostics.timezone ? "Aktualna" : "Ustaw"}</button> : undefined} />
            </>}
            {tab === "diagnostics" && <DiagnosticsPanel initial={diagnostics} toast={toast} />}
            {tab === "history" && <DataTable rows={[...history].reverse()} getRowId={(item) => `${item.timestamp}-${item.server}`} ariaLabel="Historia synchronizacji" emptyTitle={unavailable.includes("history") ? "Nie udało się pobrać historii" : "Brak pomiarów w historii"} emptyDescription={unavailable.includes("history") ? "Użyj Odśwież, aby ponowić odczyt." : "Historia zostanie uzupełniona po zebraniu pomiarów."} columns={[
              { key: "time", header: "Czas", render: (item) => formatTimestamp(item.timestamp, language) }, { key: "source", header: "Źródło", render: (item) => item.server || "—" }, { key: "stratum", header: "Stratum", render: (item) => item.stratum ?? "—" }, { key: "offset", header: "Offset", render: (item) => item.offset || "—" }, { key: "sync", header: "Synchronizacja", render: (item) => <span className={`ntp-badge ${item.synchronized ? "ntp-tone-success" : "ntp-tone-warning"}`}>{item.synchronized ? "Zsynchronizowany" : "Brak synchronizacji"}</span> },
            ]} />}
            {tab === "config" && draft && <>
              <Panel title="Usługa NTP"><dl className="ntp-details"><div><dt>Oprogramowanie</dt><dd>{backendLabel(draft.backend)}</dd></div><div><dt>Plik zarządzany przez WebNAS</dt><dd><code>{draft.managed_path || "Brak pliku"}</code></dd></div></dl><div className="ntp-row-actions">
                {canService && <><button type="button" disabled={!diagnostics.available} onClick={() => void runAction(() => ntpManagerClient.service("start"))}>Start</button><button type="button" disabled={!diagnostics.available} onClick={() => void confirmedAction("Zatrzymać usługę NTP? Synchronizacja i udostępnianie czasu zostaną przerwane.", () => ntpManagerClient.service("stop"))}>Stop</button><button type="button" disabled={!diagnostics.available} onClick={() => void confirmedAction("Zrestartować usługę NTP?", () => ntpManagerClient.service("restart"))}><RefreshCw aria-hidden="true" />Restart NTP</button></>}
                {canManage && draft.backend !== "chrony" && <button type="button" className="ntp-primary" onClick={() => void confirmedAction("Zainstalować Chrony przez systemowy menedżer pakietów?", ntpManagerClient.installChrony)}><Download aria-hidden="true" />Zainstaluj Chrony</button>}
              </div></Panel>
              <Panel title="Kopie konfiguracji"><DataTable rows={backups} getRowId={(backup) => backup.id} ariaLabel="Kopie konfiguracji NTP" emptyTitle={unavailable.includes("config") ? "Nie udało się pobrać kopii" : "Brak kopii konfiguracji"} emptyDescription={unavailable.includes("config") ? "Użyj Odśwież, aby ponowić odczyt." : "Tutaj pojawią się kopie tworzone przy zmianach konfiguracji."} actionsLabel="Akcje" columns={[
                { key: "id", header: "Kopia", render: (backup) => <code>{backup.id}</code> }, { key: "date", header: "Data", render: (backup) => formatTimestamp(backup.timestamp, language) }, { key: "actor", header: "Użytkownik", render: (backup) => backup.actor }, { key: "change", header: "Zmiana", render: (backup) => backup.change }, { key: "path", header: "Plik", render: (backup) => <code>{backup.path}</code> },
              ]} actions={canManage ? (backup) => <button type="button" onClick={() => void confirmedAction(`Przywrócić kopię ${backup.id}?`, () => ntpManagerClient.restoreBackup(backup.id))}><RotateCcw aria-hidden="true" />Przywróć</button> : undefined} /></Panel>
            </>}
          </fieldset>
        </>}
      </div>
    </div>
  </section>;
}

function DiagnosticsPanel({ initial, toast }: { initial: NtpDiagnostics; toast: ToastFn }) {
  const [data, setData] = useState(initial);
  const [details, setDetails] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setData(initial); }, [initial]);
  async function reload() {
    setLoading(true); setError("");
    try { setData(await ntpManagerClient.diagnostics()); }
    catch (failure) { const message = errorMessage(failure, "Diagnostyka nie powiodła się"); setError(message); toast(message, "error", "admin", "ntp-manager"); }
    finally { setLoading(false); }
  }
  return <>
    <div className="ntp-row-actions"><button type="button" className="ntp-primary" disabled={loading} onClick={() => void reload()}><RefreshCw className={loading ? "ntp-spin" : ""} aria-hidden="true" />Uruchom diagnostykę</button><button type="button" aria-expanded={details} onClick={() => setDetails((value) => !value)}>{details ? "Ukryj szczegóły" : "Pokaż szczegóły"}</button></div>
    {error && <div className="ntp-notice ntp-tone-warning" role="alert">{error}</div>}
    <DataTable rows={data.checks || []} getRowId={(check) => check.code} ariaLabel="Testy diagnostyczne NTP" loading={loading} loadingLabel="Diagnostyka w toku…" emptyTitle="Brak wyników diagnostyki" emptyDescription="Uruchom diagnostykę, aby sprawdzić usługę NTP." columns={[
      { key: "test", header: "Test", render: (check) => check.code }, { key: "status", header: "Stan", render: (check) => <span className={`ntp-badge ${check.status === "PASS" ? "ntp-tone-success" : "ntp-tone-warning"}`}>{{ PASS: "Poprawny", WARNING: "Ostrzeżenie", FAIL: "Błąd" }[check.status]}</span> }, { key: "detail", header: "Szczegóły", render: (check) => check.detail },
    ]} />
    {details && <Panel title="Parametry diagnostyczne"><dl className="ntp-details">{Object.entries(data.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? "—")}</dd></div>)}</dl></Panel>}
  </>;
}
