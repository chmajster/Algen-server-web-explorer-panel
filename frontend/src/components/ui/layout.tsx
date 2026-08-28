import type { HTMLAttributes, ReactNode } from "react";

function classes(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function PageHeader({ title, description, eyebrow, actions, className = "" }: {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return <header className={classes("wn-page-header", className)}>
    <div className="wn-page-header-copy">
      {eyebrow ? <span className="wn-page-eyebrow">{eyebrow}</span> : null}
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
    </div>
    {actions ? <div className="wn-page-header-actions">{actions}</div> : null}
  </header>;
}

export function PageSection({ title, description, actions, children, className = "", ...props }: HTMLAttributes<HTMLElement> & {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return <section className={classes("wn-page-section", className)} {...props}>
    {title || description || actions ? <header className="wn-section-header">
      <div>
        {title ? <h3>{title}</h3> : null}
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="wn-section-actions">{actions}</div> : null}
    </header> : null}
    {children}
  </section>;
}

export function Toolbar({ children, className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={classes("wn-toolbar", className)} role={props.role || "toolbar"} {...props}>{children}</div>;
}

export function FilterBar({ children, className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={classes("wn-filter-bar", className)} {...props}>{children}</div>;
}

export function Card({ children, className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <article className={classes("wn-card", className)} {...props}>{children}</article>;
}

export function StatCard({ label, value, detail, className = "" }: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  className?: string;
}) {
  return <Card className={classes("wn-stat-card", className)}>
    <span>{label}</span>
    <strong>{value}</strong>
    {detail ? <small>{detail}</small> : null}
  </Card>;
}

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  count?: number;
  disabled?: boolean;
}

export function Tabs<T extends string>({ items, active, onChange, ariaLabel = "Sections", className = "" }: {
  items: readonly TabItem<T>[];
  active: T;
  onChange: (id: T) => void;
  ariaLabel?: string;
  className?: string;
}) {
  return <div className={classes("wn-tabs", className)} role="tablist" aria-label={ariaLabel}>
    {items.map((item) => <button
      key={item.id}
      type="button"
      role="tab"
      aria-selected={item.id === active}
      className={item.id === active ? "active" : ""}
      disabled={item.disabled}
      onClick={() => onChange(item.id)}
    >
      <span>{item.label}</span>
      {typeof item.count === "number" ? <b>{item.count}</b> : null}
    </button>)}
  </div>;
}
