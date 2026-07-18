import { Archive, CalendarClock, FileCog, FileText, Folder, GitBranch, Info, KeyRound, LayoutDashboard, Network, PlaySquare, Radio, ScrollText, Server, Stethoscope, Users, Workflow } from "lucide-react";
import type { ModuleStatus } from "../../../api";
import type { Translate } from "../../../app/types";

export type ModuleSection = "overview" | "configuration" | "service" | "logs" | "diagnostics" | "backups" | "info" | "shares" | "users" | "sessions" | "hosts" | "inventory" | "discovery" | "credentials" | "projects" | "playbooks" | "templates" | "jobs" | "schedules" | "facts";

const icons: Record<ModuleSection, React.ReactNode> = { overview: <LayoutDashboard />, configuration: <FileCog />, service: <Server />, logs: <FileText />, diagnostics: <Stethoscope />, backups: <Archive />, info: <Info />, shares: <Folder />, users: <Users />, sessions: <Radio />, hosts: <Server />, inventory: <Workflow />, discovery: <Network />, credentials: <KeyRound />, projects: <GitBranch />, playbooks: <ScrollText />, templates: <PlaySquare />, jobs: <FileText />, schedules: <CalendarClock />, facts: <Info /> };

export function ModuleStatusBadge({ status, t }: { status: ModuleStatus; t: Translate }) {
  return <span className={`module-status-badge ${status.health}`}><i aria-hidden="true" />{t(`module.health.${status.health}`)}</span>;
}

export function translateServiceState(value: string, t: Translate): string {
  const normalized = value.trim().toLowerCase();
  if (["active", "running", "started", "online"].includes(normalized)) return t("module.serviceState.active");
  if (["inactive", "dead", "stopped", "disabled", "exited"].includes(normalized)) return t("module.serviceState.inactive");
  if (["error", "failed", "incompatible", "blocked"].includes(normalized)) return t("module.serviceState.failed");
  if (["not_applicable", "not-installed", "not_installed", "unavailable"].includes(normalized)) return t("module.serviceState.notApplicable");
  return t("module.serviceState.unknown");
}

export function translateModuleOperation(value: string, t: Translate): string {
  const key = `module.operation.${value.trim().toLowerCase()}`;
  const translated = t(key);
  return translated === key ? value.replace(/[_-]+/g, " ") : translated;
}

export function ModuleHeader({ name, status, healthMessage, stateLabel, stateValue, activeJob, t, actions }: { name: string; status: ModuleStatus; healthMessage?: string; stateLabel?: string; stateValue?: React.ReactNode; activeJob?: { operation: string; progress: number } | null; t: Translate; actions?: React.ReactNode }) {
  return <header className="module-header"><div><div className="module-title-line"><h2>{name}</h2><ModuleStatusBadge status={status} t={t} /></div><p>{healthMessage ?? status.health_message}</p><div className="module-header-meta"><span>{t("module.version")}: {status.package_version || "—"}</span><span>{stateLabel || t("module.serviceState")}: {stateValue ?? translateServiceState(status.service_state, t)}</span>{activeJob && <span>{t("module.activeJob")}: {translateModuleOperation(activeJob.operation, t)} · {activeJob.progress}%</span>}</div></div><div className="module-quick-actions">{actions}</div></header>;
}

export function ModuleAppShell({ name, status, healthMessage, activeJob, section, sections, t, actions, onSection, children }: { name: string; status: ModuleStatus; healthMessage?: string; activeJob?: { operation: string; progress: number } | null; section: ModuleSection; sections: ModuleSection[]; t: Translate; actions?: React.ReactNode; onSection: (section: ModuleSection) => void; children: React.ReactNode }) {
  return <section className="module-app"><ModuleHeader name={name} status={status} healthMessage={healthMessage} activeJob={activeJob} t={t} actions={actions} /><div className="module-layout"><nav className="module-navigation" aria-label={t("module.sections")}>{sections.map((item) => <button key={item} type="button" className={section === item ? "active" : ""} aria-current={section === item ? "page" : undefined} onClick={() => onSection(item)}>{icons[item]}<span>{t(`module.section.${item}`)}</span></button>)}</nav><main className="module-content">{children}</main></div></section>;
}

export function ModuleHealthCard({ title, value, detail, tone = "neutral" }: { title: string; value: React.ReactNode; detail?: string; tone?: "neutral" | "success" | "warning" | "danger" }) {
  return <article className={`module-health-card ${tone}`}><span>{title}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}
