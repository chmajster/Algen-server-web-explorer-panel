import {
  ArrowLeft,
  Download,
  FileText,
  Gauge,
  ListTree,
  RefreshCw,
  TerminalSquare,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api";
import type { Translate } from "../../app/types";
import {
  DockerTable,
  LoadState,
  errorMessage,
  format,
  StatusPill,
} from "./shared";

type DetailTab = "overview" | "stats" | "logs" | "processes";

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
  t,
  onBack,
}: {
  target: string;
  t: Translate;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("overview");
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
      </LoadState>
    </section>
  );
}
