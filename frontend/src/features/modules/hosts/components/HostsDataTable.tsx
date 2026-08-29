import { ChevronDown, ChevronUp } from "lucide-react";
import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";

export type HostsDataColumn<T> = {
  id: string;
  label: string;
  cell: (item: T) => ReactNode;
  sortValue?: (item: T) => string | number;
  align?: "start" | "center" | "end";
};

export function HostsDataTable<T>({
  items,
  columns,
  rowKey,
  loading = false,
  empty,
  selectedKey,
  onSelect,
}: {
  items: T[];
  columns: HostsDataColumn<T>[];
  rowKey: (item: T) => string;
  loading?: boolean;
  empty: ReactNode;
  selectedKey?: string;
  onSelect?: (item: T) => void;
}) {
  const [sort, setSort] = useState<{ id: string; direction: "ascending" | "descending" } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return items;
    const column = columns.find((item) => item.id === sort.id);
    if (!column?.sortValue) return items;
    const direction = sort.direction === "ascending" ? 1 : -1;
    return [...items].sort((left, right) =>
      String(column.sortValue?.(left) ?? "").localeCompare(String(column.sortValue?.(right) ?? ""), undefined, { numeric: true }) * direction
    );
  }, [columns, items, sort]);
  const showLoading = loading && sorted.length === 0;

  function changeSort(column: HostsDataColumn<T>) {
    if (!column.sortValue) return;
    setSort((current) => current?.id === column.id
      ? { id: column.id, direction: current.direction === "ascending" ? "descending" : "ascending" }
      : { id: column.id, direction: "ascending" });
  }
  function keyboard(event: KeyboardEvent<HTMLTableRowElement>, item: T) {
    if (!onSelect || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    onSelect(item);
  }
  return <div className="hosts-data-table" role="region" tabIndex={0} aria-busy={loading}>
    <table>
      <thead><tr>{columns.map((column) =>
        <th key={column.id} className={`align-${column.align || "start"}`} aria-sort={sort?.id === column.id ? sort.direction : column.sortValue ? "none" : undefined}>
          {column.sortValue
            ? <button type="button" onClick={() => changeSort(column)}>{column.label}{sort?.id === column.id && (sort.direction === "ascending" ? <ChevronUp /> : <ChevronDown />)}</button>
            : column.label}
        </th>
      )}</tr></thead>
      <tbody>
        {sorted.map((item) => {
          const key = rowKey(item);
          return <tr key={key} className={selectedKey === key ? "selected" : ""} tabIndex={onSelect ? 0 : undefined} aria-selected={onSelect ? selectedKey === key : undefined} onClick={() => onSelect?.(item)} onKeyDown={(event) => keyboard(event, item)}>
            {columns.map((column) => <td key={column.id} className={`align-${column.align || "start"}`}>{column.cell(item)}</td>)}
          </tr>;
        })}
      </tbody>
    </table>
    {showLoading && <div className="hosts-table-state" aria-live="polite">…</div>}
    {!loading && !sorted.length && <div className="hosts-table-state">{empty}</div>}
  </div>;
}
