import { Pencil, RefreshCw, Trash2 } from "lucide-react";
import { DataTable, PageSection, StatusBadge, type DataTableColumn } from "../../../components/ui";
import type { DcstIPSet } from "../api/types";

export function IpsetsPage({ ipsets, loading, canManage, canSync, onCreate, onView, onEdit, onDelete, onSynchronize }: {
  ipsets: DcstIPSet[]; loading: boolean; canManage: boolean; canSync: boolean; onCreate: () => void; onView: (item: DcstIPSet) => void; onEdit: (item: DcstIPSet) => void; onDelete: (item: DcstIPSet) => void; onSynchronize: (item: DcstIPSet) => void;
}) {
  const columns: DataTableColumn<DcstIPSet>[] = [
    { key: "name", header: "Name", render: (item) => <><button className="dcst-service-name" onClick={() => onView(item)}>{item.name}</button><small className="dcst-system-label">{item.type.toUpperCase()}</small></> },
    { key: "description", header: "Description", render: (item) => item.description || "—" },
    { key: "entries", header: "Entries", render: (item) => item.entries.length },
    { key: "usage", header: "Used by", render: (item) => `${item.dependencies?.length || 0} policies` },
    { key: "state", header: "State", render: (item) => <StatusBadge tone={item.sync_status === "SYNCED" ? "success" : "warning"}>{item.sync_status || "SYNCED"}</StatusBadge> },
  ];
  return <PageSection className="module-content dcst-section" title="IP Sets" description="Reusable network address objects referenced by communication policies." actions={canManage ? <button className="button-primary" onClick={onCreate}>+ Create IP Set</button> : null}>
    <DataTable rows={ipsets} columns={columns} getRowId={(item) => item.id} loading={loading} emptyTitle="No IP sets" emptyDescription="Create a reusable address object for security policies." actions={(item) => <div className="dcst-inline-actions">
      {canSync ? <button aria-label={`Synchronize ${item.name}`} onClick={() => onSynchronize(item)}><RefreshCw /></button> : null}
      {canManage && item.type === "manual" ? <><button aria-label={`Edit ${item.name}`} onClick={() => onEdit(item)}><Pencil /></button><button className="danger" aria-label={`Delete ${item.name}`} onClick={() => onDelete(item)}><Trash2 /></button></> : null}
    </div>} />
  </PageSection>;
}
