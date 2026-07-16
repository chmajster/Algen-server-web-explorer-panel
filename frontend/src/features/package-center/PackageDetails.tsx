import { ExternalLink } from "lucide-react";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import type { ModuleSummary } from "../../api";
import type { PackageAction } from "./types";
import { getPackageActions, getPackageInstalledVersion, getPackageUiStatus, normalizeServiceState, packageActionLabelKey } from "./packageState";

function List({ values }: { values: string[] }) {
  return values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <span>—</span>;
}

export function PackageDetails({ item, t, onClose, onAction, onConfigure }: {
  item: ModuleSummary;
  t: Translate;
  onClose: () => void;
  onAction: (action: PackageAction) => void;
  onConfigure?: () => void;
}) {
  const status = getPackageUiStatus(item);
  const busy = Boolean(item.active_job && ["queued", "running", "waiting_for_confirmation"].includes(item.active_job.status));
  const actions = getPackageActions(item, { advanced: true }).filter((action) => !["open", "configure"].includes(action) || onConfigure);
  const logs = item.jobs.flatMap((job) => job.log_tail).slice(-50);

  function run(action: (typeof actions)[number]) {
    if (action === "open" || action === "configure") onConfigure?.();
    else onAction(action);
  }

  return <Modal wide title={item.manifest.name} closeLabel={t("action.close")} onClose={onClose} footer={<>
    <button type="button" onClick={onClose}>{t("action.close")}</button>
    {actions.map((action, index) => <button type="button" disabled={busy} className={action === "uninstall" ? "button-danger" : index === 0 && action !== "stop" ? "button-primary" : ""} onClick={() => run(action)} key={action}>{t(packageActionLabelKey(action))}</button>)}
  </>}>
    <div className="package-details">
      <header>
        <div><span className={`package-status ui-status-${status}`}>{t(`package.status.${status}`)}</span><h3>{item.manifest.description}</h3><p>{item.manifest.long_description}</p></div>
        {item.manifest.homepage && <a href={item.manifest.homepage} target="_blank" rel="noreferrer">{t("package.homepage")}<ExternalLink /></a>}
      </header>
      <div className="package-detail-grid">
        <section><h4>{t("package.versionInfo")}</h4><dl><dt>{t("package.installedVersion")}</dt><dd>{getPackageInstalledVersion(item)}</dd><dt>{t("package.availableVersion")}</dt><dd>{item.state.available_version}</dd><dt>{t("package.license")}</dt><dd>{item.manifest.license}</dd><dt>{t("package.maintainer")}</dt><dd>{item.manifest.maintainer}</dd></dl></section>
        <section><h4>{t("package.services")}</h4>{item.state.installed ? <dl>{Object.entries(item.services).map(([name, service]) => <div key={name}><dt>{name}</dt><dd>{t(`package.service.${normalizeServiceState(service)}`)}</dd></div>)}</dl> : <span>{t("package.service.not_applicable")}</span>}<h4>{t("package.ports")}</h4><List values={item.manifest.ports} /></section>
        <section><h4>{t("package.dependencies")}</h4><List values={item.manifest.dependencies} /><h4>{t("package.permissions")}</h4><List values={item.manifest.permissions} /></section>
        <section><h4>{t("package.paths")}</h4><List values={[...item.manifest.config_paths, ...item.manifest.data_paths]} /><h4>{t("package.supportedSystems")}</h4><List values={item.manifest.supported_distributions} /></section>
        <section className="package-detail-wide"><h4>{t("package.changelog")}</h4><List values={item.manifest.changelog} /></section>
        <section className="package-detail-wide"><h4>{t("package.recentOperations")}</h4>{item.jobs.length ? item.jobs.slice(0, 5).map((job) => <div className="package-operation" key={job.id}><strong>{job.action}</strong><span>{t(`task.${job.status}`)} · {job.progress}%</span><small>{job.error || job.current_step}</small></div>) : <span>—</span>}</section>
        <section className="package-detail-wide"><h4>{t("package.logs")}</h4>{logs.length ? <pre className="package-detail-logs">{logs.map((entry) => `[${entry.stream}] ${entry.line}`).join("\n")}</pre> : <span>{t("package.noLogs")}</span>}</section>
      </div>
    </div>
  </Modal>;
}
