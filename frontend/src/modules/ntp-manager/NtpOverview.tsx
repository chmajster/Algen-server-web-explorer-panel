import { Activity, ArrowRight, CheckCircle2, Clock, Globe, Radio, Server, Shield, Users } from "lucide-react";
import { ModuleHealthCard } from "../../features/modules/common/ModuleAppShell";
import type { NtpConfiguration, NtpDiagnostics, NtpSource } from "./api/client";
import { backendLabel, firewallLabel, formatTimestamp, modeLabel, serviceLabel, sourceStateLabel, syncPresentation, type NtpSection } from "./presentation";

type Props = {
  data: NtpDiagnostics;
  configuration: NtpConfiguration | null;
  sources: NtpSource[];
  language: string;
  onSection: (section: NtpSection) => void;
};

export function NtpOverview({ data, configuration, sources, language, onSection }: Props) {
  const sync = syncPresentation(data);
  const selected = sources.find((source) => source.selected);
  const sourceName = selected?.server || data.source || "Nie wybrano";
  const synchronized = data.synchronized && data.available && data.role !== "disabled";
  return <div className="ntp-overview">
    <section className={`ntp-sync-card ntp-tone-${sync.tone}`} aria-label="Stan synchronizacji">
      <div className="ntp-sync-icon" aria-hidden="true">{synchronized ? <CheckCircle2 /> : <Clock />}</div>
      <div className="ntp-sync-copy">
        <span className="ntp-eyebrow">Synchronizacja czasu</span>
        <h3>{sync.title}</h3>
        <p>{sync.detail}</p>
        <button type="button" className="ntp-text-action" onClick={() => onSection(sync.target)}>{sync.action}<ArrowRight aria-hidden="true" /></button>
      </div>
      <span className="ntp-badge">{backendLabel(data.backend)}</span>
    </section>

    <div className="ntp-metrics">
      <ModuleHealthCard title="Źródło czasu" value={sourceName} detail={selected?.kind === "pool" ? "Pula serwerów NTP" : "Aktywne źródło synchronizacji"} />
      <ModuleHealthCard title="Odchylenie zegara" value={data.offset || "—"} detail="Różnica względem źródła czasu" />
      <ModuleHealthCard title="Stratum" value={data.stratum ?? "—"} detail="Poziom w hierarchii NTP" />
      <ModuleHealthCard title="Strefa czasowa" value={data.timezone || "Nie ustawiono"} detail="Strefa systemu operacyjnego" />
    </div>

    <div className="ntp-overview-columns">
      <section className="ntp-panel">
        <div className="ntp-panel-heading"><h3><Server aria-hidden="true" />Usługa i sieć</h3></div>
        <dl className="ntp-details">
          <div><dt>Tryb pracy</dt><dd>{modeLabel(data.role)}</dd></div>
          <div><dt>Oprogramowanie</dt><dd>{backendLabel(data.backend)}</dd></div>
          <div><dt>Usługa systemowa</dt><dd>{data.service || "Brak usługi"}</dd></div>
          <div><dt>Stan usługi</dt><dd><span className={`ntp-badge ${["active", "running"].includes(data.service_state) ? "ntp-tone-success" : ""}`}>{serviceLabel(data.service_state)}</span></dd></div>
          <div><dt><Shield aria-hidden="true" />Port UDP/123</dt><dd><span className={`ntp-badge ${data.firewall?.status === "blocked" ? "ntp-tone-warning" : ""}`}>{firewallLabel(data.firewall?.status)}</span></dd></div>
        </dl>
        <button type="button" className="ntp-text-action" onClick={() => onSection("config")}>Ustawienia usługi<ArrowRight aria-hidden="true" /></button>
      </section>

      <section className="ntp-panel">
        <div className="ntp-panel-heading"><h3><Radio aria-hidden="true" />Źródła i klienci</h3><span className="ntp-badge">Źródła: {sources.length}</span></div>
        {sources.length ? <ul className="ntp-source-list">
          {sources.slice(0, 3).map((source) => <li key={`${source.server}-${source.kind || source.mode || "source"}`}>
            <span><strong>{source.server}</strong><small>{source.enabled === false ? "Wyłączone" : sourceStateLabel(source.state)}</small></span>
            {source.selected && <CheckCircle2 className="ntp-source-selected" aria-label="Wybrane źródło" />}
          </li>)}
        </ul> : <div className="ntp-empty-inline"><Globe aria-hidden="true" /><strong>Brak źródeł czasu</strong><p>Dodaj serwer lub pulę NTP w sekcji Źródła czasu.</p></div>}
        <div className="ntp-inventory-footer">
          <button type="button" className="ntp-text-action" onClick={() => onSection("sources")}>Wszystkie źródła<ArrowRight aria-hidden="true" /></button>
          <button type="button" className="ntp-text-action" onClick={() => onSection("clients")}><Users aria-hidden="true" />Klienci: {data.summary.client_count ?? "—"}</button>
        </div>
      </section>
    </div>
    {configuration?.unmanaged_config_detected && <div className="ntp-notice"><Shield aria-hidden="true" /><div><strong>Wykryto konfigurację spoza WebNAS</strong><p>WebNAS zarządza wyłącznie własnym blokiem lub plikiem. Istniejąca konfiguracja nie jest przejmowana automatycznie.</p></div></div>}
    {data.warnings.length > 0 && <div className="ntp-notice ntp-tone-warning"><Activity aria-hidden="true" /><div><strong>Uwagi diagnostyczne</strong><ul>{data.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul></div></div>}
    <div className="ntp-snapshot"><Clock aria-hidden="true" /><span>Ostatni odczyt: {formatTimestamp(data.collected_at, language)}. Dane są odświeżane ręcznie.</span></div>
  </div>;
}
