import {
  ArrowLeft,
  Download,
  FileText,
  Gauge,
  ListTree,
  RefreshCw,
  Save,
  Settings,
  TerminalSquare,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, type DockerContainerSettings, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import {
  DockerTable,
  LoadState,
  errorMessage,
  format,
  StatusPill,
} from "./shared";

export type DetailTab = "overview" | "stats" | "logs" | "processes" | "settings";

function ContainerSettingsEditor({ target, value, t, toast, onStarted, onBack }: { target: string; value: DockerContainerSettings; t: Translate; toast: ToastFn; onStarted: (job: ModuleJob) => void; onBack: () => void }) {
  const [name, setName] = useState(value.name);
  const [limitsEnabled, setLimitsEnabled] = useState(value.resource_limits_enabled);
  const [cpuPriority, setCpuPriority] = useState(value.cpu_priority);
  const [memory, setMemory] = useState(String(value.memory_mb || 4096));
  const [autoRestart, setAutoRestart] = useState(value.auto_restart);
  const [portalEnabled, setPortalEnabled] = useState(value.portal_enabled);
  const [portalPort, setPortalPort] = useState(String(value.portal_port || value.available_ports.find((item) => item.protocol === "tcp")?.target || ""));
  const [portalProtocol, setPortalProtocol] = useState(value.portal_protocol);
  const [saving, setSaving] = useState(false);
  const portalPorts = value.available_ports.filter((item) => item.protocol === "tcp");
  const selectedBinding = portalPorts.find((item) => item.target === Number(portalPort));
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const result = await api.updateDockerContainerSettings(target, {
        name, resource_limits_enabled: limitsEnabled, cpu_priority: cpuPriority,
        memory_mb: limitsEnabled ? Number(memory) : null, auto_restart: autoRestart,
        portal_enabled: portalEnabled, portal_port: portalEnabled ? Number(portalPort) : null,
        portal_protocol: portalProtocol, confirmation: target,
      });
      onStarted(result.job);
      onBack();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }
  return <form className="docker-container-settings" onSubmit={(event) => void submit(event)}>
    {value.compose_managed && <p className="docker-notice warning">{t("docker.composeManagedSettingsWarning")}</p>}
    <label>{t("docker.containerName")}<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
    <fieldset>
      <label className="check-row"><input type="checkbox" checked={limitsEnabled} onChange={(event) => setLimitsEnabled(event.target.checked)} />{t("docker.enableResourceLimits")}</label>
      <div className="docker-settings-fields" aria-disabled={!limitsEnabled}>
        <label>{t("docker.cpuPriority")}<select value={cpuPriority} disabled={!limitsEnabled} onChange={(event) => setCpuPriority(event.target.value as typeof cpuPriority)}>{(["low", "medium", "high"] as const).map((item) => <option key={item} value={item}>{t(`docker.priority.${item}`)}</option>)}</select></label>
        <label>{t("docker.memoryLimit")}<span className="docker-unit-input"><input aria-label={t("docker.memoryLimit")} type="number" min="16" max="1048576" value={memory} disabled={!limitsEnabled} onChange={(event) => setMemory(event.target.value)} required={limitsEnabled} /><span>MB</span></span></label>
      </div>
    </fieldset>
    <label className="check-row"><input type="checkbox" checked={autoRestart} onChange={(event) => setAutoRestart(event.target.checked)} />{t("docker.enableAutoRestart")}</label>
    <fieldset>
      <label className="check-row"><input type="checkbox" checked={portalEnabled} disabled={!portalPorts.length} onChange={(event) => setPortalEnabled(event.target.checked)} />{t("docker.configureWebPortal")}</label>
      {portalEnabled && <div className="docker-settings-fields">
        <label>{t("docker.containerPort")}<select value={portalPort} onChange={(event) => setPortalPort(event.target.value)} required>{portalPorts.map((item) => <option key={`${item.target}:${item.published}`} value={item.target}>{item.target} → {item.published}</option>)}</select></label>
        <label>{t("docker.portalProtocol")}<select value={portalProtocol} onChange={(event) => setPortalProtocol(event.target.value as typeof portalProtocol)}><option value="http">HTTP</option><option value="https">HTTPS</option></select></label>
      </div>}
      {!portalPorts.length && <small className="field-hint">{t("docker.portalRequiresPublishedPort")}</small>}
      {portalEnabled && selectedBinding && <a href={`${portalProtocol}://${window.location.hostname}:${selectedBinding.published}`} target="_blank" rel="noreferrer">{t("docker.openPanel")}: {portalProtocol}://{window.location.hostname}:{selectedBinding.published}</a>}
    </fieldset>
    <footer><button className="button-primary" type="submit" disabled={saving || !name || limitsEnabled && !memory || portalEnabled && !portalPort}><Save />{saving ? t("status.loading") : t("action.save")}</button></footer>
  </form>;
}

function Sparkline({ values }: { values: number[] }) {
  const samples = values.slice(-60);
  const maximum = Math.max(...samples, 1);
  const points = samples
    .map((value, index) => {
      const x = samples.length === 1 ? 0 : (index / (samples.length - 1)) * 100;
      return `${x},${31 - (Math.max(0, value) / maximum) * 29}`;
    })
    .join(" ");
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
export function ContainerDetails({
  target,
  initialTab = "overview",
  t,
  onBack,
  permissions,
  toast,
  onJob,
}: {
  target: string;
  initialTab?: DetailTab;
  t: Translate;
  onBack: () => void;
  permissions: string[];
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
}) {
  const [tab, setTab] = useState<DetailTab>(initialTab);
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [extra, setExtra] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const [logLevel, setLogLevel] = useState("");
  const [logSince, setLogSince] = useState("");
  const [liveLogs, setLiveLogs] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const detail = await api.dockerContainer(target);
      setData(detail);
      if (tab === "stats") setExtra(await api.dockerContainerStats(target));
      else if (tab === "logs")
        setExtra(await api.dockerContainerLogs(target, { tail: 500, search: logSearch, level: logLevel, since: logSince }));
      else if (tab === "processes")
        setExtra(await api.dockerContainerProcesses(target));
      else if (tab === "settings")
        setExtra(await api.dockerContainerSettings(target));
      else setExtra(null);
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [logLevel, logSearch, logSince, tab, t, target]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (tab !== "stats") return;
    const timer = window.setInterval(() => {
      void api
        .dockerContainerStats(target)
        .then(setExtra)
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [tab, target]);
  useEffect(() => {
    if (tab !== "logs" || loading || error || !liveLogs) return;
    const source = new EventSource(
      `/api/modules/docker/containers/${encodeURIComponent(target)}/logs/stream?tail=0`,
    );
    source.onmessage = (event) => {
      try {
        const value = JSON.parse(event.data) as { line?: string };
        if (typeof value.line !== "string") return;
        setExtra((current: unknown) => {
          const lines = [
            ...((current as { lines?: string[] } | null)?.lines || []),
            value.line,
          ];
          return { lines: lines.slice(-5000), total: lines.length, truncated: lines.length > 5000 };
        });
      } catch {
        // Ignore malformed third-party container output events.
      }
    };
    source.addEventListener("end", () => source.close());
    source.onerror = () => source.close();
    return () => source.close();
  }, [error, liveLogs, loading, tab, target]);
  function exportLogs() {
    const content = ((extra as { lines?: string[] } | null)?.lines || []).join("\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${target}-logs.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  const tabs: Array<[DetailTab, ReactNode]> = [
    ["overview", <ListTree />],
    ["stats", <Gauge />],
    ["logs", <FileText />],
    ["processes", <TerminalSquare />],
    ...(permissions.includes("docker.create_container") ? [["settings" as DetailTab, <Settings />] as [DetailTab, ReactNode]] : []),
  ];
  return (
    <section className="docker-details">
      <header className="docker-section-toolbar">
        <button onClick={onBack}>
          <ArrowLeft />
          {t("action.back")}
        </button>
        <div>
          <h2>{String(data?.name || target)}</h2>
          {Boolean(data?.state) && (
            <StatusPill
              value={String(
                (data?.state as Record<string, unknown> | undefined)?.Status ||
                  "unknown",
              )}
              t={t}
            />
          )}
        </div>
        <button onClick={() => void load()}>
          <RefreshCw />
          {t("action.refresh")}
        </button>
      </header>
      <nav className="docker-detail-tabs">
        {tabs.map(([name, icon]) => (
          <button
            className={tab === name ? "active" : ""}
            key={name}
            onClick={() => setTab(name)}
          >
            {icon}
            {t(`docker.detail.${name}`)}
          </button>
        ))}
      </nav>
      <LoadState
        loading={loading}
        error={error}
        retry={() => void load()}
        t={t}
      >
        {tab === "overview" && data && (
          <div className="docker-inspect-grid">
            {Object.entries(data).map(([key, value]) => (
              <article key={key}>
                <span>{t(`docker.field.${key}`)}</span>
                <strong>{format(value)}</strong>
              </article>
            ))}
          </div>
        )}
        {tab === "stats" && extra !== null && (
          <>
            <div className="docker-stats-charts">
              {[
                ["cpu_percent", "docker.statsCpu"],
                ["memory_bytes", "docker.statsMemory"],
                ["network_input_bytes", "docker.statsNetworkInput"],
                ["network_output_bytes", "docker.statsNetworkOutput"],
              ].map(([key, label]) => {
                const history = (
                  extra as { history?: Array<Record<string, unknown>> }
                ).history || [];
                const values = history.map((item) => Number(item[key]) || 0);
                return (
                  <article key={key}>
                    <span>{t(label)}</span>
                    <strong>{format(values[values.length - 1])}</strong>
                    <Sparkline values={values} />
                  </article>
                );
              })}
            </div>
            <div className="docker-inspect-grid">
            {Object.entries(
              (extra as { current?: Record<string, unknown> }).current || {},
            ).map(([key, value]) => (
              <article key={key}>
                <span>{t(`docker.field.${key}`)}</span>
                <strong>{format(value)}</strong>
              </article>
            ))}
            </div>
          </>
        )}
        {tab === "logs" && extra !== null && (
          <>
            <div className="docker-section-toolbar">
              <input aria-label={t("action.search")} placeholder={t("action.search")} value={logSearch} onChange={(event) => setLogSearch(event.target.value)} />
              <input aria-label={t("docker.logLevel")} placeholder={t("docker.logLevel")} value={logLevel} onChange={(event) => setLogLevel(event.target.value)} />
              <input aria-label={t("docker.logSince")} placeholder="30m" value={logSince} onChange={(event) => setLogSince(event.target.value)} />
              <label className="check-row"><input type="checkbox" checked={liveLogs} onChange={(event) => setLiveLogs(event.target.checked)} />{t("docker.liveLogs")}</label>
              <button onClick={exportLogs}><Download />{t("action.download")}</button>
            </div>
            <pre className="docker-log-view">
              {(extra as { lines: string[] }).lines.join("\n")}
            </pre>
          </>
        )}
        {tab === "processes" && extra !== null && (
          <DockerTable
            items={(extra as { items: Array<Record<string, unknown>> }).items}
            columns={["PID", "PPID", "USER", "STAT", "ELAPSED", "COMMAND"].map(
              (key) => ({ key, label: key }),
            )}
            empty={t("docker.noProcesses")}
          />
        )}
        {tab === "settings" && extra !== null && <ContainerSettingsEditor target={target} value={extra as DockerContainerSettings} t={t} toast={toast} onStarted={onJob} onBack={onBack} />}
      </LoadState>
    </section>
  );
}
