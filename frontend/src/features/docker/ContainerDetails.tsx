import {
  ArrowLeft,
  Boxes,
  Download,
  FileText,
  Gauge,
  HardDrive,
  ListTree,
  Network,
  RefreshCw,
  Save,
  Settings,
  TerminalSquare,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type DockerContainerSettings, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import {
  DockerTable,
  LoadState,
  errorMessage,
  format,
  StatusPill,
} from "./shared";
import "./container-details-horizontal.css";

export type DetailTab = "overview" | "stats" | "logs" | "processes" | "settings";

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function boolText(value: unknown, t: Translate): string {
  return Boolean(value) ? t("common.yes") : t("common.no");
}

function bytes(value: unknown): string {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const unit = Math.min(units.length - 1, Math.floor(Math.log(amount) / Math.log(1024)));
  const precision = unit > 0 && amount / 1024 ** unit < 10 ? 1 : 0;
  return `${(amount / 1024 ** unit).toFixed(precision)} ${units[unit]}`;
}

function dateTime(value: unknown): string {
  if (!value) return "—";
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function cpuLimit(value: unknown): string {
  const amount = Number(value || 0);
  return Number.isFinite(amount) && amount > 0 ? `${amount / 1_000_000_000} CPU` : "—";
}

function metricValue(key: string, value: unknown): string {
  if (["memory_bytes", "network_input_bytes", "network_output_bytes", "block_read_bytes", "block_write_bytes"].includes(key)) {
    return bytes(value);
  }
  if (key === "cpu_percent" || key === "memory_percent") {
    const amount = Number(value || 0);
    return Number.isFinite(amount) ? `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}%` : "—";
  }
  return format(value);
}

function FieldRow({ label, children, code = false, muted = false }: { label: ReactNode; children: ReactNode; code?: boolean; muted?: boolean }) {
  return (
    <div className={`docker-detail-row${muted ? " muted" : ""}`}>
      <dt>{label}</dt>
      <dd className={code ? "docker-detail-code" : undefined}>{children}</dd>
    </div>
  );
}

function DetailSection({ icon, title, description, children }: { icon: ReactNode; title: ReactNode; description?: ReactNode; children: ReactNode }) {
  return (
    <article className="docker-detail-section">
      <header className="docker-detail-section-header">
        <span className="docker-detail-section-icon" aria-hidden="true">{icon}</span>
        <div>
          <h3>{title}</h3>
          {description && <p>{description}</p>}
        </div>
      </header>
      <dl className="docker-detail-rows">{children}</dl>
    </article>
  );
}

function ChipList({ values, empty = "—", code = false }: { values: string[]; empty?: string; code?: boolean }) {
  if (!values.length) return <span className="docker-detail-empty">{empty}</span>;
  return (
    <span className="docker-detail-chip-list">
      {values.map((value, index) => <span className={code ? "docker-detail-chip code" : "docker-detail-chip"} key={`${value}-${index}`}>{value}</span>)}
    </span>
  );
}

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
        name,
        resource_limits_enabled: limitsEnabled,
        cpu_priority: cpuPriority,
        memory_mb: limitsEnabled ? Number(memory) : null,
        auto_restart: autoRestart,
        portal_enabled: portalEnabled,
        portal_port: portalEnabled ? Number(portalPort) : null,
        portal_protocol: portalProtocol,
        confirmation: target,
      });
      onStarted(result.job);
      onBack();
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="docker-container-settings docker-container-settings-horizontal" onSubmit={(event) => void submit(event)}>
      {value.compose_managed && <p className="docker-notice warning">{t("docker.composeManagedSettingsWarning")}</p>}
      <div className="docker-settings-horizontal-row">
        <label>{t("docker.containerName")}<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
        <label className="check-row"><input type="checkbox" checked={autoRestart} onChange={(event) => setAutoRestart(event.target.checked)} />{t("docker.enableAutoRestart")}</label>
      </div>
      <fieldset>
        <label className="check-row"><input type="checkbox" checked={limitsEnabled} onChange={(event) => setLimitsEnabled(event.target.checked)} />{t("docker.enableResourceLimits")}</label>
        <div className="docker-settings-horizontal-row" aria-disabled={!limitsEnabled}>
          <label>{t("docker.cpuPriority")}<select value={cpuPriority} disabled={!limitsEnabled} onChange={(event) => setCpuPriority(event.target.value as typeof cpuPriority)}>{(["low", "medium", "high"] as const).map((item) => <option key={item} value={item}>{t(`docker.priority.${item}`)}</option>)}</select></label>
          <label>{t("docker.memoryLimit")}<span className="docker-unit-input"><input aria-label={t("docker.memoryLimit")} type="number" min="16" max="1048576" value={memory} disabled={!limitsEnabled} onChange={(event) => setMemory(event.target.value)} required={limitsEnabled} /><span>MB</span></span></label>
        </div>
      </fieldset>
      <fieldset>
        <label className="check-row"><input type="checkbox" checked={portalEnabled} disabled={!portalPorts.length} onChange={(event) => setPortalEnabled(event.target.checked)} />{t("docker.configureWebPortal")}</label>
        {portalEnabled && <div className="docker-settings-horizontal-row">
          <label>{t("docker.containerPort")}<select value={portalPort} onChange={(event) => setPortalPort(event.target.value)} required>{portalPorts.map((item) => <option key={`${item.target}:${item.published}`} value={item.target}>{item.target} → {item.published}</option>)}</select></label>
          <label>{t("docker.portalProtocol")}<select value={portalProtocol} onChange={(event) => setPortalProtocol(event.target.value as typeof portalProtocol)}><option value="http">HTTP</option><option value="https">HTTPS</option></select></label>
        </div>}
        {!portalPorts.length && <small className="field-hint">{t("docker.portalRequiresPublishedPort")}</small>}
        {portalEnabled && selectedBinding && <a href={`${portalProtocol}://${window.location.hostname}:${selectedBinding.published}`} target="_blank" rel="noreferrer">{t("docker.openPanel")}: {portalProtocol}://{window.location.hostname}:{selectedBinding.published}</a>}
      </fieldset>
      <footer><button className="button-primary" type="submit" disabled={saving || !name || limitsEnabled && !memory || portalEnabled && !portalPort}><Save />{saving ? t("status.loading") : t("action.save")}</button></footer>
    </form>
  );
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

function Overview({ data, t }: { data: UnknownRecord; t: Translate }) {
  const state = record(data.state);
  const health = record(data.health);
  const limits = record(data.limits);
  const networks = Object.entries(record(data.networks));
  const mounts = list(data.mounts).map(record);
  const labels = Object.entries(record(data.labels));
  const environmentKeys = list(data.environment_keys).map(String).filter(Boolean);
  const ports = Object.entries(record(data.ports)).flatMap(([containerPort, rawBindings]) => {
    const bindings = list(rawBindings);
    if (!bindings.length) return [{ containerPort, host: "—" }];
    return bindings.map((rawBinding) => {
      const binding = record(rawBinding);
      const hostPort = text(binding.HostPort);
      const hostIp = text(binding.HostIp) === "—" ? "0.0.0.0" : text(binding.HostIp);
      return { containerPort, host: hostPort === "—" ? "—" : `${hostIp}:${hostPort}` };
    });
  });

  const stateFlags = [
    state.Running ? t("docker.state.running") : "",
    state.Paused ? t("docker.state.paused") : "",
    state.Restarting ? t("docker.state.restarting") : "",
    state.Dead ? t("docker.state.dead") : "",
  ].filter(Boolean);

  return (
    <div className="docker-horizontal-overview">
      <DetailSection icon={<ListTree />} title={t("docker.detail.overview")}>
        <FieldRow label={t("docker.field.id")} code>{text(data.id)}</FieldRow>
        <FieldRow label={t("docker.field.image")}>{text(data.image)}</FieldRow>
        <FieldRow label={t("docker.field.image_id")} code>{text(data.image_id)}</FieldRow>
        <FieldRow label={t("docker.field.platform")}>{text(data.platform)}</FieldRow>
        <FieldRow label={t("docker.field.created")}>{dateTime(data.created)}</FieldRow>
      </DetailSection>

      <DetailSection icon={<Gauge />} title={t("docker.field.status")}>
        <FieldRow label={t("docker.field.status")}><StatusPill value={text(state.Status) === "—" ? "unknown" : text(state.Status)} t={t} /></FieldRow>
        <FieldRow label={t("docker.field.health")}>
          <span className={`docker-detail-health health-${text(health.Status).toLowerCase()}`}>{text(health.Status)}</span>
        </FieldRow>
        <FieldRow label={t("docker.field.restart_policy")}>{text(data.restart_policy)}</FieldRow>
        <FieldRow label={t("docker.field.state")}><ChipList values={stateFlags} /></FieldRow>
        <FieldRow label={t("docker.field.exitCode")}>{text(state.ExitCode)}</FieldRow>
        <FieldRow label={t("docker.field.startedAt")}>{dateTime(state.StartedAt)}</FieldRow>
        <FieldRow label={t("docker.field.finishedAt")}>{dateTime(state.FinishedAt)}</FieldRow>
        {Object.keys(health).length > 0 && <FieldRow label={t("docker.field.healthcheck")} code>{format(health)}</FieldRow>}
      </DetailSection>

      <DetailSection icon={<Network />} title={t("docker.field.networks")}>
        <FieldRow label={t("docker.field.networks")}>
          {networks.length ? <span className="docker-detail-stack">
            {networks.map(([name, rawNetwork]) => {
              const network = record(rawNetwork);
              const aliases = list(network.Aliases).map(String).filter(Boolean);
              return <span className="docker-detail-network-line" key={name}>
                <strong>{name}</strong>
                <span>IP: {text(network.IPAddress)}</span>
                <span>GW: {text(network.Gateway)}</span>
                <span>MAC: {text(network.MacAddress)}</span>
                {aliases.length > 0 && <ChipList values={aliases} code />}
              </span>;
            })}
          </span> : <span className="docker-detail-empty">—</span>}
        </FieldRow>
        <FieldRow label={t("docker.field.ports")}>
          {ports.length ? <span className="docker-detail-stack">
            {ports.map((port, index) => <span className="docker-detail-port-line" key={`${port.containerPort}-${port.host}-${index}`}><code>{port.host}</code><span aria-hidden="true">→</span><code>{port.containerPort}</code></span>)}
          </span> : <span className="docker-detail-empty">—</span>}
        </FieldRow>
      </DetailSection>

      <DetailSection icon={<HardDrive />} title={t("docker.field.mounts")}>
        <FieldRow label={t("docker.field.mounts")}>
          {mounts.length ? <span className="docker-detail-stack">
            {mounts.map((mount, index) => {
              const kind = text(mount.Type).toLowerCase();
              const source = kind === "volume" ? text(mount.Name) : kind === "tmpfs" ? "tmpfs" : text(mount.Source);
              return <span className="docker-detail-mount-line" key={`${source}-${text(mount.Destination)}-${index}`}>
                <span className="docker-detail-kind">{kind}</span>
                <code>{source}</code>
                <span aria-hidden="true">→</span>
                <code>{text(mount.Destination)}</code>
                <span className={mount.RW === false ? "docker-detail-access read-only" : "docker-detail-access"}>{mount.RW === false ? "RO" : "RW"}</span>
              </span>;
            })}
          </span> : <span className="docker-detail-empty">—</span>}
        </FieldRow>
      </DetailSection>

      <DetailSection icon={<Gauge />} title={t("docker.field.limits")}>
        <FieldRow label={t("docker.statsCpu")}>{cpuLimit(limits.nano_cpus)}</FieldRow>
        <FieldRow label={t("docker.statsMemory")}>{bytes(limits.memory)}</FieldRow>
        <FieldRow label={t("docker.field.memorySwapMb")}>{bytes(limits.memory_swap)}</FieldRow>
        <FieldRow label={t("docker.field.pids")}>{text(limits.pids)}</FieldRow>
      </DetailSection>

      <DetailSection icon={<Settings />} title={t("docker.detail.settings")}>
        <FieldRow label={t("docker.field.read_only")}>{boolText(data.read_only, t)}</FieldRow>
        <FieldRow label={t("docker.field.environment_keys")}><ChipList values={environmentKeys} code /></FieldRow>
        <FieldRow label={t("docker.field.labels")}>
          {labels.length ? <span className="docker-detail-stack docker-detail-labels">
            {labels.map(([key, value]) => <span className="docker-detail-key-value" key={key}><code>{key}</code><span>=</span><code>{text(value)}</code></span>)}
          </span> : <span className="docker-detail-empty">—</span>}
        </FieldRow>
      </DetailSection>
    </div>
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
  const [data, setData] = useState<UnknownRecord | null>(null);
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
      else if (tab === "logs") setExtra(await api.dockerContainerLogs(target, { tail: 500, search: logSearch, level: logLevel, since: logSince }));
      else if (tab === "processes") setExtra(await api.dockerContainerProcesses(target));
      else if (tab === "settings") setExtra(await api.dockerContainerSettings(target));
      else setExtra(null);
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [logLevel, logSearch, logSince, tab, t, target]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (tab !== "stats") return;
    const timer = window.setInterval(() => {
      void api.dockerContainerStats(target).then(setExtra).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [tab, target]);

  useEffect(() => {
    if (tab !== "logs" || loading || error || !liveLogs) return;
    const source = new EventSource(`/api/modules/docker/containers/${encodeURIComponent(target)}/logs/stream?tail=0`);
    source.onmessage = (event) => {
      try {
        const value = JSON.parse(event.data) as { line?: string };
        if (typeof value.line !== "string") return;
        setExtra((current: unknown) => {
          const lines = [...((current as { lines?: string[] } | null)?.lines || []), value.line];
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

  const state = record(data?.state);
  const health = record(data?.health);
  const networks = Object.keys(record(data?.networks));
  const portCount = Object.keys(record(data?.ports)).length;
  const mountCount = list(data?.mounts).length;
  const stateStatus = text(state.Status) === "—" ? "unknown" : text(state.Status);
  const healthStatus = text(health.Status);
  const headerMetrics = useMemo(() => [
    { label: t("docker.field.image"), value: text(data?.image), code: false },
    { label: t("docker.field.networks"), value: networks.length ? networks.join(", ") : "—", code: false },
    { label: t("docker.field.ports"), value: String(portCount), code: false },
    { label: t("docker.field.mounts"), value: String(mountCount), code: false },
  ], [data?.image, mountCount, networks, portCount, t]);

  return (
    <section className="docker-details docker-details-modern">
      <header className="docker-detail-topbar">
        <button onClick={onBack}><ArrowLeft />{t("action.back")}</button>
        <button onClick={() => void load()}><RefreshCw />{t("action.refresh")}</button>
      </header>

      <div className="docker-detail-hero">
        <div className="docker-detail-title">
          <span className="docker-detail-container-icon"><Boxes /></span>
          <div>
            <span>{t("docker.container")}</span>
            <h2>{String(data?.name || target)}</h2>
            <code>{String(data?.id || target)}</code>
          </div>
        </div>
        <div className="docker-detail-statuses">
          {Boolean(data?.state) && <StatusPill value={stateStatus} t={t} />}
          {healthStatus !== "—" && <span className={`docker-detail-health health-${healthStatus.toLowerCase()}`}>{healthStatus}</span>}
        </div>
        <div className="docker-detail-kpis">
          {headerMetrics.map((item) => <div key={item.label}><span>{item.label}</span><strong className={item.code ? "docker-detail-code" : undefined}>{item.value}</strong></div>)}
        </div>
      </div>

      <nav className="docker-detail-tabs" aria-label={t("docker.details")}>
        {tabs.map(([name, icon]) => (
          <button className={tab === name ? "active" : ""} key={name} onClick={() => setTab(name)}>
            {icon}{t(`docker.detail.${name}`)}
          </button>
        ))}
      </nav>

      <div className="docker-detail-content">
        <LoadState loading={loading} error={error} retry={() => void load()} t={t}>
          {tab === "overview" && data && <Overview data={data} t={t} />}

          {tab === "stats" && extra !== null && (
            <div className="docker-detail-stats-view">
              <div className="docker-detail-stat-strip">
                {[
                  ["cpu_percent", "docker.statsCpu"],
                  ["memory_bytes", "docker.statsMemory"],
                  ["network_input_bytes", "docker.statsNetworkInput"],
                  ["network_output_bytes", "docker.statsNetworkOutput"],
                ].map(([key, label]) => {
                  const history = (extra as { history?: Array<UnknownRecord> }).history || [];
                  const values = history.map((item) => Number(item[key]) || 0);
                  return (
                    <article key={key}>
                      <span>{t(label)}</span>
                      <strong>{metricValue(key, values[values.length - 1])}</strong>
                      <Sparkline values={values} />
                    </article>
                  );
                })}
              </div>
              <DetailSection icon={<Gauge />} title={t("docker.detail.stats")}>
                {Object.entries((extra as { current?: UnknownRecord }).current || {}).map(([key, value]) => (
                  <FieldRow label={t(`docker.field.${key}`)} key={key}>{metricValue(key, value)}</FieldRow>
                ))}
              </DetailSection>
            </div>
          )}

          {tab === "logs" && extra !== null && (
            <div className="docker-detail-log-view">
              <div className="docker-detail-log-toolbar">
                <input aria-label={t("action.search")} placeholder={t("action.search")} value={logSearch} onChange={(event) => setLogSearch(event.target.value)} />
                <input aria-label={t("docker.logLevel")} placeholder={t("docker.logLevel")} value={logLevel} onChange={(event) => setLogLevel(event.target.value)} />
                <input aria-label={t("docker.logSince")} placeholder="30m" value={logSince} onChange={(event) => setLogSince(event.target.value)} />
                <label className="check-row"><input type="checkbox" checked={liveLogs} onChange={(event) => setLiveLogs(event.target.checked)} />{t("docker.liveLogs")}</label>
                <button onClick={exportLogs}><Download />{t("action.download")}</button>
              </div>
              <pre className="docker-log-view">{(extra as { lines: string[] }).lines.join("\n")}</pre>
            </div>
          )}

          {tab === "processes" && extra !== null && (
            <DockerTable
              items={(extra as { items: Array<UnknownRecord> }).items}
              columns={["PID", "PPID", "USER", "STAT", "ELAPSED", "COMMAND"].map((key) => ({ key, label: key }))}
              empty={t("docker.noProcesses")}
            />
          )}

          {tab === "settings" && extra !== null && (
            <ContainerSettingsEditor target={target} value={extra as DockerContainerSettings} t={t} toast={toast} onStarted={onJob} onBack={onBack} />
          )}
        </LoadState>
      </div>
    </section>
  );
}
