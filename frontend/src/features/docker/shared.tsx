import { CircleAlert, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import type { Translate } from "../../app/types";

export function LoadState({
  loading,
  error,
  t,
  retry,
  children,
}: {
  loading: boolean;
  error: string;
  t: Translate;
  retry: () => void;
  children: ReactNode;
}) {
  if (loading)
    return (
      <div className="loading-state" role="status">
        {t("status.loading")}
      </div>
    );
  if (error)
    return (
      <div className="error-state" role="alert">
        <CircleAlert />
        <strong>{t("docker.loadFailed")}</strong>
        <span>{error}</span>
        <button onClick={retry}>
          <RefreshCw />
          {t("action.retry")}
        </button>
      </div>
    );
  return <>{children}</>;
}

type DockerColumn = {
  key: string;
  label: string;
  render?: (value: unknown, row: Record<string, unknown>) => ReactNode;
};

export function DockerTable({
  items,
  columns,
  empty,
  actions,
  actionsLabel = "",
  onRowClick,
}: {
  items?: Array<Record<string, unknown>> | null;
  columns?: DockerColumn[] | null;
  empty: string;
  actions?: (row: Record<string, unknown>) => ReactNode;
  actionsLabel?: string;
  onRowClick?: (row: Record<string, unknown>) => void;
}) {
  const safeItems: Array<Record<string, unknown>> = Array.isArray(items) ? items : [];
  const safeColumns: DockerColumn[] = Array.isArray(columns) ? columns : [];

  if (!safeItems.length)
    return (
      <div className="empty-state">
        <strong>{empty}</strong>
      </div>
    );
  return (
    <div className="docker-table-wrap">
      <table className="docker-table">
        <thead>
          <tr>
            {safeColumns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
            {actions && (
              <th>
                <span className="visually-hidden">{actionsLabel}</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {safeItems.map((item, index) => (
            <tr
              key={String(
                item.ID ||
                  item.Id ||
                  item.id ||
                  item.Name ||
                  item.name ||
                  index,
              )}
              className={onRowClick ? "docker-clickable-row" : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(item) : undefined}
              onKeyDown={onRowClick ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onRowClick(item);
                }
              } : undefined}
            >
              {safeColumns.map((column) => (
                <td key={column.key}>
                  {column.render
                    ? column.render(item[column.key], item)
                    : format(item[column.key])}
                </td>
              ))}
              {actions && (
                <td>
                  <div className="docker-row-actions" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>{actions(item)}</div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function format(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ") || "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function errorMessage(error: unknown, t: Translate): string {
  return error instanceof Error ? error.message : t("error.generic");
}

export function StatusPill({ value, t }: { value?: string | null; t: Translate }) {
  const normalized = typeof value === "string" && value.trim()
    ? value.toLowerCase()
    : "unknown";
  return (
    <span className={`docker-status docker-status-${normalized}`}>
      {t(`docker.state.${normalized}`)}
    </span>
  );
}
