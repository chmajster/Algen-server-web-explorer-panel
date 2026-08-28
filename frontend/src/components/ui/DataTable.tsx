import type { ReactNode } from "react";
import { EmptyState, LoadingState } from "./feedback";

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string;
}

export interface DataTableProps<T> {
  rows: readonly T[];
  columns: readonly DataTableColumn<T>[];
  getRowId: (row: T) => string;
  loading?: boolean;
  loadingLabel?: string;
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  selected?: ReadonlySet<string>;
  onSelectionChange?: (next: Set<string>) => void;
  actions?: (row: T) => ReactNode;
  actionsLabel?: ReactNode;
  ariaLabel?: string;
  className?: string;
}

export function DataTable<T>({
  rows,
  columns,
  getRowId,
  loading = false,
  loadingLabel = "Loading…",
  emptyTitle = "No data",
  emptyDescription,
  selected,
  onSelectionChange,
  actions,
  actionsLabel = "Actions",
  ariaLabel,
  className = "",
}: DataTableProps<T>) {
  const selectable = Boolean(selected && onSelectionChange);
  const columnCount = columns.length + (selectable ? 1 : 0) + (actions ? 1 : 0);
  const allSelected = selectable && rows.length > 0 && rows.every((row) => selected?.has(getRowId(row)));

  function toggleAll(checked: boolean) {
    if (!selected || !onSelectionChange) return;
    const next = new Set(selected);
    rows.forEach((row) => checked ? next.add(getRowId(row)) : next.delete(getRowId(row)));
    onSelectionChange(next);
  }

  function toggleRow(id: string, checked: boolean) {
    if (!selected || !onSelectionChange) return;
    const next = new Set(selected);
    if (checked) next.add(id); else next.delete(id);
    onSelectionChange(next);
  }

  return <div className={`wn-data-table ${className}`.trim()}>
    <div className="wn-table-scroll">
      <table aria-label={ariaLabel}>
        <thead><tr>
          {selectable ? <th className="wn-selection-cell">
            <input type="checkbox" aria-label="Select all rows" checked={Boolean(allSelected)} onChange={(event) => toggleAll(event.target.checked)} />
          </th> : null}
          {columns.map((column) => <th key={column.key} className={column.className}>{column.header}</th>)}
          {actions ? <th className="wn-actions-cell">{actionsLabel}</th> : null}
        </tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={columnCount}><LoadingState label={loadingLabel} compact /></td></tr> : null}
          {!loading && rows.map((row) => {
            const id = getRowId(row);
            return <tr key={id} data-selected={selected?.has(id) || undefined}>
              {selectable ? <td className="wn-selection-cell"><input type="checkbox" aria-label={`Select row ${id}`} checked={selected?.has(id) || false} onChange={(event) => toggleRow(id, event.target.checked)} /></td> : null}
              {columns.map((column) => <td key={column.key} className={column.className}>{column.render(row)}</td>)}
              {actions ? <td className="wn-actions-cell">{actions(row)}</td> : null}
            </tr>;
          })}
        </tbody>
      </table>
    </div>
    {!loading && rows.length === 0 ? <EmptyState title={emptyTitle} description={emptyDescription} /> : null}
  </div>;
}
