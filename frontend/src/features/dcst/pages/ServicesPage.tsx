import { RefreshCw } from "lucide-react";
import { FilterBar, PageSection, SearchInput, Select, Toolbar } from "../../../components/ui";
import type { DcstIPSet, DcstPort, DcstService, DcstTag } from "../api/types";
import { DcstServiceTable } from "../components/DcstServiceTable";
import type { ServiceFilters } from "../domain/service";

export function ServicesPage({ services, visible, ports, tags, ipsets, selected, loading, inventoryReady, filters, canManage, canBlock, canSync, canInventorySync, onFilter, onSelectionChange, onCreate, onView, onEdit, onDuplicate, onAction, onSynchronize, onDelete, onInventorySync, onBulk, onBulkBlock }: {
  services: DcstService[];
  visible: DcstService[];
  ports: DcstPort[];
  tags: DcstTag[];
  ipsets: DcstIPSet[];
  selected: Set<string>;
  loading: boolean;
  inventoryReady: boolean;
  filters: ServiceFilters;
  canManage: boolean;
  canBlock: boolean;
  canSync: boolean;
  canInventorySync: boolean;
  onFilter: <K extends keyof ServiceFilters>(key: K, value: ServiceFilters[K]) => void;
  onSelectionChange: (next: Set<string>) => void;
  onCreate: () => void;
  onView: (item: DcstService) => void;
  onEdit: (item: DcstService) => void;
  onDuplicate: (item: DcstService) => void;
  onAction: (item: DcstService, operation: "block" | "unblock" | "enable" | "disable") => void;
  onSynchronize: (item: DcstService) => void;
  onDelete: (item: DcstService) => void;
  onInventorySync: () => void;
  onBulk: (operation: "block" | "unblock" | "enable" | "disable" | "sync") => void;
  onBulkBlock: () => void;
}) {
  return <PageSection className="module-content dcst-section" title="Communication Services" description="Control communication between security objects." actions={canManage ? <button className="button-primary" onClick={onCreate}>+ New Service</button> : null}>
    <FilterBar className="dcst-policy-toolbar">
      <SearchInput value={filters.search} onChange={(event) => onFilter("search", event.target.value)} placeholder="Search services..." aria-label="Search communication services" />
      <Select label="Direction" value={filters.direction} onChange={(event) => onFilter("direction", event.target.value)}><option value="">All</option><option value="IN">IN</option><option value="OUT">OUT</option></Select>
      <Select label="Action" value={filters.action} onChange={(event) => onFilter("action", event.target.value)}><option value="">All</option><option value="ACCEPT">ACCEPT</option><option value="DROP">DROP</option><option value="REJECT">REJECT</option></Select>
      <Select label="State" value={filters.state} onChange={(event) => onFilter("state", event.target.value)}><option value="">All</option><option value="ACTIVE">ACTIVE</option><option value="BLOCKED">BLOCKED</option><option value="DISABLED">DISABLED</option><option value="PENDING">PENDING</option><option value="ERROR">ERROR</option></Select>
    </FilterBar>
    {selected.size ? <Toolbar className="dcst-bulk-toolbar" aria-label="Bulk service actions">
      <strong>{selected.size} service{selected.size === 1 ? "" : "s"} selected</strong>
      <div>
        {canManage ? <><button onClick={() => onBulk("enable")}>Enable</button><button onClick={() => onBulk("disable")}>Disable</button></> : null}
        {canBlock ? <><button onClick={onBulkBlock}>Block</button><button onClick={() => onBulk("unblock")}>Unblock</button></> : null}
        {canSync ? <button onClick={() => onBulk("sync")}><RefreshCw /> Synchronize</button> : null}
        <button onClick={() => onSelectionChange(new Set())}>Clear selection</button>
      </div>
    </Toolbar> : null}
    <DcstServiceTable
      services={visible} ports={ports} tags={tags} ipsets={ipsets} selected={selected} loading={loading}
      inventoryReady={inventoryReady} hasAnyServices={services.length > 0} canManage={canManage} canBlock={canBlock}
      canSync={canSync} canInventorySync={canInventorySync}
      onToggle={(id, checked) => { const next = new Set(selected); if (checked) next.add(id); else next.delete(id); onSelectionChange(next); }}
      onToggleAll={(checked) => onSelectionChange(checked ? new Set(visible.map((item) => item.id)) : new Set())}
      onView={onView} onEdit={onEdit} onDuplicate={onDuplicate} onAction={onAction} onSynchronize={onSynchronize}
      onDelete={onDelete} onCreate={onCreate} onSynchronizeInventory={onInventorySync}
    />
  </PageSection>;
}
