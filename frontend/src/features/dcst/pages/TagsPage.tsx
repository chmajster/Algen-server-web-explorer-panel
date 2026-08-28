import { RefreshCw } from "lucide-react";
import { DataTable, PageSection, StatusBadge, type DataTableColumn } from "../../../components/ui";
import type { DcstTag } from "../api/types";

export function TagsPage({ tags, loading, canManage, refreshing, onSynchronize, onView }: {
  tags: DcstTag[]; loading: boolean; canManage: boolean; refreshing: boolean; onSynchronize: () => void; onView: (tag: DcstTag) => void;
}) {
  const columns: DataTableColumn<DcstTag>[] = [
    { key: "tag", header: "Tag", render: (tag) => <span className="dcst-tag-badge">{tag.name}</span> },
    { key: "apmid", header: "APMID", render: (tag) => tag.apmid },
    { key: "environment", header: "Environment", render: (tag) => tag.environment },
    { key: "vms", header: "VMs", render: (tag) => `${tag.vm_count} VMs` },
    { key: "addresses", header: "IP addresses", render: (tag) => <span className="dcst-address-cell">{tag.addresses.slice(0, 2).map((address) => <code key={address}>{address}</code>)}{tag.addresses.length > 2 ? <small>+{tag.addresses.length - 2}</small> : null}</span> },
    { key: "state", header: "Sync state", render: (tag) => <StatusBadge tone={tag.sync_status === "SYNCED" ? "success" : "warning"}>{tag.sync_status || "SYNCED"}</StatusBadge> },
  ];
  return <PageSection className="module-content dcst-section" title="Tags" description="Inventory-backed APMID.ENV security groups discovered from managed virtual machines." actions={canManage ? <button onClick={onSynchronize} disabled={refreshing}><RefreshCw className={refreshing ? "spin" : ""} /> Synchronize inventory</button> : null}>
    <DataTable rows={tags} columns={columns} getRowId={(tag) => tag.id} loading={loading} emptyTitle="No network objects discovered" emptyDescription="Synchronize DCST inventory to import APMID.ENV groups from managed virtual machines." actions={(tag) => <button className="link-button" onClick={() => onView(tag)}>View</button>} />
  </PageSection>;
}
