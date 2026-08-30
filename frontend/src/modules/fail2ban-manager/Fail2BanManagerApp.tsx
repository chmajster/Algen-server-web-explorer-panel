import { Ban, FileText, RefreshCw, RotateCcw, Search, Shield, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { confirmDialog } from "../../components/DialogService";
import { Modal } from "../../components/Modal";
import type { ToastFn } from "../../app/types";
import { fail2banManagerClient, type Fail2BanJail, type Fail2BanStatus, type JailConfigInput } from "./api/client";
import "../infrastructure-managers.css";

type Props = { permissions: string[]; language: string; toast: ToastFn };
const emptyConfig = (): JailConfigInput => ({ enabled: true, filter: "", backend: "", port: "", maxretry: null, findtime: "", bantime: "", action: "", confirm: true });

export function Fail2BanManagerApp({ permissions, language, toast }: Props) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    title: "Fail2Ban Manager",
    subtitle: pl ? "Status, jail-e, bany i bezpieczne override konfiguracji." : "Status, jails, bans and safe managed configuration overrides.",
    refresh: pl ? "Odśwież" : "Refresh", restart: pl ? "Restart" : "Restart", reload: "Reload",
    status: pl ? "Status usługi" : "Service status", active: pl ? "aktywna" : "active", inactive: pl ? "nieaktywna" : "inactive",
    jails: pl ? "Aktywne jail-e" : "Active jails", banned: pl ? "Aktualnie zbanowane" : "Currently banned", total: pl ? "Łączne bany" : "Total bans",
    jail: "Jail", state: pl ? "Stan" : "State", current: pl ? "Bany" : "Bans", ips: "IP", actions: pl ? "Akcje" : "Actions",
    enable: pl ? "Włącz" : "Enable", disable: pl ? "Wyłącz" : "Disable", config: pl ? "Konfiguruj" : "Configure", ban: "Ban", unban: "Unban",
    ip: pl ? "Adres IP do zbanowania" : "IP address to ban", logs: "Logs", search: pl ? "Szukaj w logach" : "Search logs",
    save: pl ? "Zapisz i przeładuj" : "Save and reload", close: pl ? "Zamknij" : "Close",
    confirmBan: pl ? "Potwierdzić ban tego adresu IP?" : "Confirm banning this IP address?",
    confirmUnban: pl ? "Potwierdzić usunięcie bana?" : "Confirm unbanning this IP address?",
    confirmRestart: pl ? "Zrestartować usługę Fail2Ban?" : "Restart Fail2Ban service?",
    confirmReload: pl ? "Przeładować konfigurację Fail2Ban?" : "Reload Fail2Ban configuration?",
    noClient: pl ? "fail2ban-client nie jest dostępny na tym serwerze." : "fail2ban-client is not available on this server.",
  };
  const [status, setStatus] = useState<Fail2BanStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [banIp, setBanIp] = useState<Record<string, string>>({});
  const [configJail, setConfigJail] = useState<Fail2BanJail | null>(null);
  const [config, setConfig] = useState<JailConfigInput>(emptyConfig);
  const [logsOpen, setLogsOpen] = useState(false);
  const [logs, setLogs] = useState<Array<{ timestamp: string; message: string }>>([]);
  const [logQuery, setLogQuery] = useState("");
  const canManage = permissions.includes("fail2ban-manager.manage");
  const canBan = permissions.includes("fail2ban-manager.ban");
  const canUnban = permissions.includes("fail2ban-manager.unban");
  const canConfigure = permissions.includes("fail2ban-manager.configure");
  const canLogs = permissions.includes("fail2ban-manager.logs.view");

  const refresh = useCallback(async () => {
    try {
      setStatus(await fail2banManagerClient.dashboard());
    } catch (error) {
      toast(error instanceof Error ? error.message : "Fail2Ban Manager error", "error", "admin", "fail2ban-manager");
    } finally { setLoading(false); }
  }, [toast]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function action(fn: () => Promise<unknown>) {
    try { await fn(); await refresh(); }
    catch (error) { toast(error instanceof Error ? error.message : "Fail2Ban Manager error", "error", "admin", "fail2ban-manager"); }
  }

  async function ban(jail: string) {
    const ip = (banIp[jail] || "").trim();
    if (!ip || !(await confirmDialog(tx.confirmBan, (key) => key))) return;
    await action(() => fail2banManagerClient.ban(jail, ip));
    setBanIp((current) => ({ ...current, [jail]: "" }));
  }
  async function unban(jail: string, ip: string) {
    if (!(await confirmDialog(tx.confirmUnban, (key) => key))) return;
    await action(() => fail2banManagerClient.unban(jail, ip));
  }
  async function openConfig(jail: Fail2BanJail) {
    try {
      const managed = await fail2banManagerClient.config(jail.name);
      const values = emptyConfig();
      values.enabled = jail.enabled;
      for (const line of managed.content.split("\n")) {
        if (!line.includes("=") || line.trim().startsWith("#")) continue;
        const [rawKey, ...rest] = line.split("="); const key = rawKey.trim(); const value = rest.join("=").trim();
        if (key === "enabled") values.enabled = value.toLowerCase() === "true";
        else if (key === "maxretry") values.maxretry = /^\d+$/.test(value) ? Number(value) : null;
        else if (["filter", "backend", "port", "findtime", "bantime", "action"].includes(key)) (values as unknown as Record<string, unknown>)[key] = value;
      }
      setConfig(values); setConfigJail(jail);
    } catch (error) { toast(error instanceof Error ? error.message : "Fail2Ban config error", "error", "admin", "fail2ban-manager"); }
  }
  async function saveConfig(event: React.FormEvent) {
    event.preventDefault(); if (!configJail) return;
    await action(() => fail2banManagerClient.saveConfig(configJail.name, config)); setConfigJail(null);
  }
  async function loadLogs() {
    try { setLogs((await fail2banManagerClient.logs({ query: logQuery, limit: 500 })).items); setLogsOpen(true); }
    catch (error) { toast(error instanceof Error ? error.message : "Fail2Ban logs error", "error", "admin", "fail2ban-manager"); }
  }

  const jails = status?.jails || [];
  return <div className="infra-manager-app">
    <header className="infra-manager-header">
      <div className="infra-manager-title"><Shield /><div><h2>{tx.title}</h2><p>{tx.subtitle}</p></div></div>
      <div className="infra-manager-actions">
        {canLogs && <button type="button" onClick={() => void loadLogs()}><FileText />{tx.logs}</button>}
        {canManage && <button type="button" onClick={async () => { if (await confirmDialog(tx.confirmReload, (key) => key)) void action(fail2banManagerClient.reload); }}><RotateCcw />{tx.reload}</button>}
        {canManage && <button type="button" onClick={async () => { if (await confirmDialog(tx.confirmRestart, (key) => key)) void action(fail2banManagerClient.restart); }}><ShieldCheck />{tx.restart}</button>}
        <button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{tx.refresh}</button>
      </div>
    </header>
    {status && !status.client_available && <div className="infra-manager-warning"><Ban />{tx.noClient}</div>}
    <div className="infra-stat-grid">
      <div className="infra-stat"><strong>{status?.service_active ? tx.active : tx.inactive}</strong><small>{tx.status} · {status?.version || "—"}</small></div>
      <div className="infra-stat"><strong>{status?.active_jails ?? "—"}</strong><small>{tx.jails}</small></div>
      <div className="infra-stat"><strong>{status?.currently_banned ?? "—"}</strong><small>{tx.banned}</small></div>
      <div className="infra-stat"><strong>{status?.total_banned ?? "—"}</strong><small>{tx.total}</small></div>
    </div>
    <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>{tx.jail}</th><th>{tx.state}</th><th>{tx.current}</th><th>{tx.ips}</th><th>{tx.actions}</th></tr></thead><tbody>
      {jails.map((jail) => <tr key={jail.name}><td><strong>{jail.name}</strong></td><td>{jail.status}</td><td>{jail.banned_count} / {jail.total_banned}</td><td><div className="infra-chips">{jail.banned_ips.map((ip) => <span key={ip}>{ip}{canUnban && <button type="button" title={tx.unban} onClick={() => void unban(jail.name, ip)}>×</button>}</span>)}</div></td><td><div className="infra-row-actions">
        {canBan && <><input aria-label={tx.ip} placeholder={tx.ip} value={banIp[jail.name] || ""} onChange={(event) => setBanIp((current) => ({ ...current, [jail.name]: event.target.value }))} /><button type="button" onClick={() => void ban(jail.name)}>{tx.ban}</button></>}
        {canManage && <button type="button" onClick={() => void action(() => fail2banManagerClient.setEnabled(jail.name, !jail.enabled))}>{jail.enabled ? tx.disable : tx.enable}</button>}
        {canConfigure && <button type="button" onClick={() => void openConfig(jail)}>{tx.config}</button>}
      </div></td></tr>)}
      {!loading && jails.length === 0 && <tr><td className="infra-empty" colSpan={5}>—</td></tr>}
    </tbody></table></div>

    {configJail && <Modal title={`${tx.config}: ${configJail.name}`} closeLabel={tx.close} onClose={() => setConfigJail(null)} footer={<button className="button-primary" type="submit" form="fail2ban-config-form">{tx.save}</button>}><form id="fail2ban-config-form" className="infra-form" onSubmit={saveConfig}>
      <label>filter<input value={config.filter} onChange={(event) => setConfig({ ...config, filter: event.target.value })} /></label><label>backend<input value={config.backend} onChange={(event) => setConfig({ ...config, backend: event.target.value })} /></label>
      <label>port<input value={config.port} onChange={(event) => setConfig({ ...config, port: event.target.value })} /></label><label>maxretry<input type="number" min={1} value={config.maxretry ?? ""} onChange={(event) => setConfig({ ...config, maxretry: event.target.value ? Number(event.target.value) : null })} /></label>
      <label>findtime<input value={config.findtime} onChange={(event) => setConfig({ ...config, findtime: event.target.value })} /></label><label>bantime<input value={config.bantime} onChange={(event) => setConfig({ ...config, bantime: event.target.value })} /></label>
      <label className="infra-form-wide">action<input value={config.action} onChange={(event) => setConfig({ ...config, action: event.target.value })} /></label><label><input type="checkbox" checked={config.enabled} onChange={(event) => setConfig({ ...config, enabled: event.target.checked })} /> enabled</label>
    </form></Modal>}

    {logsOpen && <Modal title={tx.logs} closeLabel={tx.close} onClose={() => setLogsOpen(false)}><div className="infra-manager-toolbar"><label className="infra-search"><Search /><input value={logQuery} placeholder={tx.search} onChange={(event) => setLogQuery(event.target.value)} /></label><button type="button" onClick={() => void loadLogs()}>{tx.search}</button></div><div className="infra-log-list">{logs.map((entry, index) => <div className="infra-log-line" key={`${entry.timestamp}-${index}`}><strong>{entry.timestamp}</strong> {entry.message}</div>)}</div></Modal>}
  </div>;
}
