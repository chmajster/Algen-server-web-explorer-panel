import {
  Boxes,
  Cpu,
  Database,
  HardDrive,
  Network,
  Play,
  RefreshCw,
  ShieldAlert,
  Square,
  Stethoscope,
  Trash2,
} from "lucide-react";
import type { DockerDashboard as Dashboard, DockerEngineAction, ModuleJob } from "../../api";
import type { Translate } from "../../app/types";

export function DockerDashboard({
  data,
  canStart,
  canStop,
  canInstall,
  canUpdate,
  busy,
  t,
  onRefresh,
  onEngineAction,
  canPrune,
  onPrune,
  onDiagnostics,
}: {
  data: Dashboard;
  canStart: boolean;
  canStop: boolean;
  canInstall: boolean;
  canUpdate: boolean;
  busy: boolean;
  t: Translate;
  onRefresh: () => void;
  onEngineAction: (action: DockerEngineAction["action"]) => void;
  canPrune: boolean;
  onPrune: () => void;
  onDiagnostics: () => void;
}) {
  const source = data || ({} as Dashboard);
  const status = source.status || ({
    installed: false,
    update_available: false,
    service_state: "unknown",
    service_enabled: false,
    services: {},
    health: "unknown",
    health_message: "",
    last_action: "",
    last_action_status: "",
    last_error: "",
    metrics: {},
  } as Dashboard["status"]);
  const counts = source.counts || ({} as Dashboard["counts"]);
  const storage: Dashboard["storage"] = Array.isArray(source.storage) ? source.storage : [];
  const security: Dashboard["security"] = Array.isArray(source.security) ? source.security : [];
  const events = Array.isArray(source.events) ? source.events : [];
  const updates = Array.isArray(source.updates) ? source.updates : [];

  const metrics = [
    ["containers", counts.containers || 0, <Boxes />],
    ["running", counts.running || 0, <Cpu />],
    ["stopped", counts.stopped || 0, <Square />],
    ["paused", counts.paused || 0, <Boxes />],
    ["unhealthy", counts.unhealthy || 0, <ShieldAlert />],
    ["images", counts.images || 0, <HardDrive />],
    ["volumes", counts.volumes || 0, <Database />],
    ["networks", counts.networks || 0, <Network />],
  ] as const;

  return (
    <div className="docker-dashboard">
      <section className="docker-engine-card">
        <div>
          <span className={`docker-engine-dot ${status.health || "unknown"}`} />
          <div>
            <h3>{t("docker.engine")}</h3>
            <p>{status.health_message || "—"}</p>
            <small>
              {t("module.version")}: {status.package_version || "—"}
            </small>
            {Boolean(status.metrics?.requires_reboot) && <p className="docker-notice warning">{t("docker.rebootRequired")}</p>}
          </div>
        </div>
        <div className="docker-actions">
          {!status.installed && canInstall && (
            <button className="button-primary" disabled={busy} onClick={() => onEngineAction("install")}>
              <Play />{t("docker.installEngine")}
            </button>
          )}
          {status.installed && status.service_state !== "active" && canStart && (
            <button className="button-primary" disabled={busy} onClick={() => onEngineAction("start")}>
              <Play />{t("module.start")}
            </button>
          )}
          {status.service_state === "active" && canStop && (
            <button disabled={busy} onClick={() => onEngineAction("stop")}>
              <Square />{t("module.stop")}
            </button>
          )}
          {status.installed && status.update_available && canUpdate && (
            <button disabled={busy} onClick={() => onEngineAction("update")}>
              <RefreshCw />{t("docker.engineAction.update")}
            </button>
          )}
          {status.installed && canInstall && (
            <button disabled={busy} onClick={() => onEngineAction("reinstall")}>
              <RefreshCw />{t("docker.engineAction.reinstall")}
            </button>
          )}
          {status.service_state === "active" && canStart && (
            <button disabled={busy} onClick={() => onEngineAction("restart")}>
              <RefreshCw />{t("docker.engineAction.restart")}
            </button>
          )}
          {status.installed && status.service_enabled && canStop && (
            <button disabled={busy} onClick={() => onEngineAction("disable")}>
              {t("docker.engineAction.disable")}
            </button>
          )}
          {status.installed && !status.service_enabled && canStart && (
            <button disabled={busy} onClick={() => onEngineAction("enable")}>
              {t("docker.engineAction.enable")}
            </button>
          )}
          <button onClick={onRefresh}><RefreshCw />{t("action.refresh")}</button>
          <button onClick={onDiagnostics}><Stethoscope />{t("docker.runDiagnostics")}</button>
          {canPrune && <button className="button-danger" onClick={onPrune}><Trash2 />{t("docker.prune")}</button>}
        </div>
      </section>

      <div className="docker-metric-grid">
        {metrics.map(([key, value, icon]) => (
          <article key={key}>
            {icon}
            <span>{t(`docker.metric.${key}`)}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </div>

      <div className="docker-metric-grid">
        <article><Cpu /><span>{t("docker.statsCpu")}</span><strong>{Number(source.usage?.cpu_percent || 0).toFixed(2)}%</strong></article>
        <article><Database /><span>{t("docker.statsMemory")}</span><strong>{Math.round(Number(source.usage?.memory_bytes || 0) / 1024 / 1024)} MiB</strong></article>
      </div>

      <div className="docker-dashboard-grid">
        <section>
          <h3>{t("docker.storage")}</h3>
          {storage.length ? (
            storage.map((row, index) => (
              <dl key={index}>
                {Object.entries(row || {})
                  .slice(0, 5)
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
              </dl>
            ))
          ) : (
            <p>{t("docker.noStorageData")}</p>
          )}
        </section>

        <section>
          <h3><ShieldAlert />{t("docker.security")}</h3>
          {security.length ? (
            security.map((item, index) => (
              <p className={`docker-notice ${item?.level || "warning"}`} key={index}>
                {String(item?.message || "—")}
              </p>
            ))
          ) : (
            <p>{t("docker.noSecurityWarnings")}</p>
          )}
        </section>
      </div>

      <div className="docker-dashboard-grid">
        <section>
          <h3>{t("docker.recentEvents")}</h3>
          {events.length
            ? events.slice(0, 10).map((event, index) => <p key={index}>{String(event?.Action || event?.action || event?.status || "—")}</p>)
            : <p>{t("docker.noEvents")}</p>}
        </section>
        <section>
          <h3>{t("docker.availableUpdates")}</h3>
          {updates.length
            ? updates.map((update, index) => <p key={index}>{String(update?.component || "Docker")}: {update?.available_update ? t("common.yes") : t("common.no")}</p>)
            : <p>—</p>}
        </section>
      </div>
    </div>
  );
}

export type JobHandler = (job: ModuleJob) => void;
