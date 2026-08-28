import { Pencil, Trash2 } from "lucide-react";
import { DataTable, PageSection, type DataTableColumn } from "../../../components/ui";
import type { DcstPort } from "../api/types";
import { portRangeLabel } from "../domain/port";

export function PortsPage({ ports, loading, canManage, usage, onCreate, onView, onEdit, onDelete }: {
  ports: DcstPort[]; loading: boolean; canManage: boolean; usage: Map<string, number>; onCreate: () => void; onView: (item: DcstPort) => void; onEdit: (item: DcstPort) => void; onDelete: (item: DcstPort) => void;
}) {
  const columns: DataTableColumn<DcstPort>[] = [
    { key: "name", header: "Name", render: (port) => <button className="dcst-service-name" onClick={() => onView(port)}>{port.name}</button> },
    { key: "protocol", header: "Protocol", render: (port) => <span className="dcst-protocol-badge">{port.protocol.toUpperCase()}</span> },
    { key: "range", header: "Port / Range", render: (port) => <code>{portRangeLabel(port)}</code> },
    { key: "usage", header: "Used by", render: (port) => `${usage.get(port.id) || 0} policies` },
    { key: "description", header: "Description", render: (port) => port.description || "—" },
  ];
  return <PageSection className="module-content dcst-section" title="Port Objects" description="Reusable protocol and port definitions for communication services." actions={canManage ? <button className="button-primary" onClick={onCreate}>+ Create Port Object</button> : null}>
    <DataTable rows={ports} columns={columns} getRowId={(port) => port.id} loading={loading} emptyTitle="No port objects" emptyDescription="Create reusable transport objects such as HTTPS, PostgreSQL or DNS." actions={canManage ? (port) => <div className="dcst-inline-actions"><button aria-label={`Edit ${port.name}`} onClick={() => onEdit(port)}><Pencil /></button><button className="danger" aria-label={`Delete ${port.name}`} onClick={() => onDelete(port)}><Trash2 /></button></div> : undefined} />
  </PageSection>;
}
