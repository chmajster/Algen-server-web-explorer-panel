import { ArrowRight, Ban, Copy, Eye, Lock, MoreVertical, Pencil, RefreshCw, Trash2, Unlock } from "lucide-react";
import type { DcstIPSet, DcstPort, DcstService, DcstTag } from "../../../modules/dcst/api/client";
import { DcstEmptyState, DcstObjectBadge, DcstSkeletonRows, DcstStatusBadge } from "./DcstPrimitives";

function portLabel(port: DcstPort) {
  const range = port.port_from ? `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `–${port.port_to}` : ""}` : "";
  return `${port.name} · ${port.protocol.toUpperCase()}${range ? `/${range}` : ""}`;
}

export function DcstServiceTable({
  services,
  ports,
  tags,
  ipsets,
  selected,
  loading,
  inventoryReady,
  hasAnyServices,
  canManage,
  canBlock,
  canSync,
  canInventorySync,
  onToggle,
  onToggleAll,
  onView,
  onEdit,
  onDuplicate,
  onAction,
  onSynchronize,
  onDelete,
  onCreate,
  onSynchronizeInventory,
}: {
  services: DcstService[];
  ports: DcstPort[];
  tags: DcstTag[];
  ipsets: DcstIPSet[];
  selected: Set<string>;
  loading: boolean;
  inventoryReady: boolean;
  hasAnyServices: boolean;
  canManage: boolean;
  canBlock: boolean;
  canSync: boolean;
  canInventorySync: boolean;
  onToggle: (id: string, checked: boolean) => void;
  onToggleAll: (checked: boolean) => void;
  onView: (item: DcstService) => void;
  onEdit: (item: DcstService) => void;
  onDuplicate: (item: DcstService) => void;
  onAction: (item: DcstService, operation: "block" | "unblock" | "enable" | "disable") => void;
  onSynchronize: (item: DcstService) => void;
  onDelete: (item: DcstService) => void;
  onCreate: () => void;
  onSynchronizeInventory: () => void;
}) {
  const allSelected = services.length > 0 && services.every((item) => selected.has(item.id));

  if (!loading && !services.length) {
    if (hasAnyServices) {
      return <DcstEmptyState title="No services match filters" description="Change the search text or policy filters to show communication services." />;
    }
    return <DcstEmptyState
      title={inventoryReady ? "No communication services" : "No network objects discovered"}
      description={inventoryReady
        ? "Create your first communication policy between APMID.ENV groups, IP sets or network addresses."
        : "Synchronize DCST inventory to import APMID.ENV groups from managed virtual machines."}
      actionLabel={inventoryReady ? (canManage ? "+ Create Service" : undefined) : (canInventorySync ? "Synchronize inventory" : undefined)}
      onAction={inventoryReady ? (canManage ? onCreate : undefined) : (canInventorySync ? onSynchronizeInventory : undefined)}
    />;
  }

  return <div className="table-scroll dcst-service-table">
    <table>
      <thead>
        <tr>
          <th className="dcst-select-cell"><input type="checkbox" aria-label="Select all communication services" checked={allSelected} onChange={(event) => onToggleAll(event.target.checked)} /></th>
          <th>Name</th>
          <th>Source</th>
          <th className="dcst-flow-column" aria-label="Traffic flow" />
          <th>Destination</th>
          <th>Service / Ports</th>
          <th>Direction</th>
          <th>Action</th>
          <th>State</th>
          <th className="dcst-actions-column">Actions</th>
        </tr>
      </thead>
      <tbody>
        {loading && <DcstSkeletonRows columns={10} />}
        {!loading && services.map((item) => {
          const servicePorts = item.port_ids.map((id) => ports.find((port) => port.id === id)).filter((port): port is DcstPort => Boolean(port));
          const effectiveAction = item.blocked ? "DROP" : item.action;
          return <tr key={item.id}>
            <td className="dcst-select-cell"><input type="checkbox" aria-label={`Select ${item.name}`} checked={selected.has(item.id)} onChange={(event) => onToggle(item.id, event.target.checked)} /></td>
            <td>
              <button className="dcst-service-name" onClick={() => onView(item)}>{item.name}</button>
              {item.system_service && <small className="dcst-system-label">SYSTEM</small>}
            </td>
            <td><DcstObjectBadge type={item.source_type} value={item.source_value} tags={tags} ipsets={ipsets} showMeta /></td>
            <td className="dcst-flow-column"><ArrowRight aria-hidden="true" /></td>
            <td><DcstObjectBadge type={item.destination_type} value={item.destination_value} tags={tags} ipsets={ipsets} showMeta /></td>
            <td>
              <div className="dcst-port-cell">
                {!servicePorts.length && <span className="dcst-port-chip">ANY</span>}
                {servicePorts.slice(0, 2).map((port) => <span className="dcst-port-chip" key={port.id}>{portLabel(port)}</span>)}
                {servicePorts.length > 2 && <span className="dcst-port-chip muted">+{servicePorts.length - 2}</span>}
              </div>
            </td>
            <td><span className="dcst-direction-badge">{item.direction}</span></td>
            <td><span className={`dcst-action-badge ${effectiveAction.toLowerCase()}`}>{effectiveAction}</span></td>
            <td><DcstStatusBadge status={item.state} /></td>
            <td className="dcst-actions-column">
              <details className="dcst-row-menu">
                <summary aria-label={`Actions for ${item.name}`}><MoreVertical /></summary>
                <div className="dcst-row-menu-popover">
                  <button onClick={() => onView(item)}><Eye /> View details</button>
                  {canManage && !item.system_service && <button onClick={() => onEdit(item)}><Pencil /> Edit</button>}
                  {canManage && !item.system_service && <button onClick={() => onDuplicate(item)}><Copy /> Duplicate</button>}
                  {canManage && <button onClick={() => onAction(item, item.enabled ? "disable" : "enable")}>
                    {item.enabled ? <Lock /> : <Unlock />}{item.enabled ? "Disable" : "Enable"}
                  </button>}
                  {canBlock && <button onClick={() => onAction(item, item.blocked ? "unblock" : "block")}>
                    {item.blocked ? <Unlock /> : <Ban />}{item.blocked ? "Unblock" : "Block"}
                  </button>}
                  {canSync && <button onClick={() => onSynchronize(item)}><RefreshCw /> Synchronize</button>}
                  {canManage && !item.system_service && <>
                    <span className="dcst-menu-separator" />
                    <button className="danger" onClick={() => onDelete(item)}><Trash2 /> Delete</button>
                  </>}
                </div>
              </details>
            </td>
          </tr>;
        })}
      </tbody>
    </table>
  </div>;
}
