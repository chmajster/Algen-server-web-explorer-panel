import { Activity, Archive, FileCog, FileText, Info, LayoutDashboard, Server, Stethoscope } from "lucide-react";
import type { ModuleStatus } from "../../../api";
import type { Translate } from "../../../app/types";

export type ModuleSection = "overview" | "configuration" | "service" | "logs" | "diagnostics" | "backups" | "info" | "shares" | "users" | "sessions";

const icons: Record<ModuleSection, React.ReactNode> = { overview: <LayoutDashboard />, configuration: <FileCog />, service: <Server />, logs: <FileText />, diagnostics: <Stethoscope />, backups: <Archive />, info: <Info />, shares: <Activity />, users: <Activity />, sessions: <Activity /> };

export function ModuleStatusBadge({ status, t }: { status: ModuleStatus; t: Translate }) {
  return <span className={`module-status-badge ${status.health}`}><i aria-hidden="true" />{t(`module.health.${status.health}`)}</span>;
}

export function ModuleHeader({ name, status, activeJob, t, actions }: { name: string; status: ModuleStatus; activeJob?: { operation: string; progress: number } | null; t: Translate; actions?: React.ReactNode }) {
  return <header className="module-header"><div><div className="module-title-line"><h2>{name}</h2><ModuleStatusBadge status={status} t={t} /></div><p>{status.health_message}</p><div className="module-header-meta"><span>{t("module.version")}: {status.package_version || "—"}</span><span>{t("module.serviceState")}: {status.service_state}</span>{activeJob && <span>{t("module.activeJob")}: {t(`module.operation.${activeJob.operation}`)} · {activeJob.progress}%</span>}</div></div><div className="module-quick-actions">{actions}</div></header>;
}

export function ModuleAppShell({ name, status, activeJob, section, sections, t, actions, onSection, children }: { name: string; status: ModuleStatus; activeJob?: { operation: string; progress: number } | null; section: ModuleSection; sections: ModuleSection[]; t: Translate; actions?: React.ReactNode; onSection: (section: ModuleSection) => void; children: React.ReactNode }) {
  return <section className="module-app"><ModuleHeader name={name} status={status} activeJob={activeJob} t={t} actions={actions} /><div className="module-layout"><nav className="module-navigation" aria-label={t("module.sections")}>{sections.map((item) => <button key={item} type="button" className={section === item ? "active" : ""} aria-current={section === item ? "page" : undefined} onClick={() => onSection(item)}>{icons[item]}<span>{t(`module.section.${item}`)}</span></button>)}</nav><main className="module-content">{children}</main></div></section>;
}

export function ModuleHealthCard({ title, value, detail, tone = "neutral" }: { title: string; value: React.ReactNode; detail?: string; tone?: "neutral" | "success" | "warning" | "danger" }) {
  return <article className={`module-health-card ${tone}`}><span>{title}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}
