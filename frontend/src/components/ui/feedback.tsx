import type { ReactNode } from "react";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

function classes(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function StatusBadge({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: StatusTone; className?: string }) {
  return <span className={classes("wn-status-badge", `tone-${tone}`, className)}>{children}</span>;
}

export function HealthBadge({ status }: { status: "healthy" | "degraded" | "down" | "unknown" }) {
  const tone: StatusTone = status === "healthy" ? "success" : status === "degraded" ? "warning" : status === "down" ? "danger" : "neutral";
  return <StatusBadge tone={tone}>{status}</StatusBadge>;
}

export function ProgressBar({ value, label = "Progress" }: { value: number; label?: string }) {
  const normalized = Math.min(100, Math.max(0, value));
  return <div className="wn-progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={normalized}>
    <span style={{ width: `${normalized}%` }} />
  </div>;
}

export function EmptyState({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return <div className="wn-state wn-empty-state">
    <strong>{title}</strong>
    {description ? <p>{description}</p> : null}
    {action ? <div>{action}</div> : null}
  </div>;
}

export function LoadingState({ label = "Loading…", compact = false }: { label?: ReactNode; compact?: boolean }) {
  return <div className={classes("wn-state", "wn-loading-state", compact && "is-compact")} role="status" aria-live="polite">
    <span className="wn-spinner" aria-hidden="true" />
    <span>{label}</span>
  </div>;
}

export function ErrorState({ title = "Something went wrong", description, action }: { title?: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return <div className="wn-state wn-error-state" role="alert">
    <strong>{title}</strong>
    {description ? <p>{description}</p> : null}
    {action ? <div>{action}</div> : null}
  </div>;
}

export function InlineAlert({ children, tone = "info" }: { children: ReactNode; tone?: Exclude<StatusTone, "neutral"> }) {
  return <div className={`wn-inline-alert tone-${tone}`} role={tone === "danger" ? "alert" : "status"}>{children}</div>;
}

export function Tooltip({ content, children }: { content: string; children: ReactNode }) {
  return <span className="wn-tooltip" title={content}>{children}</span>;
}
