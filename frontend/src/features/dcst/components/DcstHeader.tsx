import { Play, RefreshCw, Shield } from "lucide-react";

export function DcstHeader({
  managedObjectCount,
  lastSyncLabel,
  inventorySynchronized,
  refreshing,
  synchronizing,
  canSync,
  onRefresh,
  onSynchronize,
}: {
  managedObjectCount: number;
  lastSyncLabel: string;
  inventorySynchronized: boolean;
  refreshing: boolean;
  synchronizing: boolean;
  canSync: boolean;
  onRefresh: () => void;
  onSynchronize: () => void;
}) {
  return <header className="feature-header dcst-header">
    <div className="dcst-header-identity">
      <span className="dcst-title-icon" aria-hidden="true"><Shield /></span>
      <div>
        <h2>DATA Communication &amp; Segmentation Tool</h2>
        <strong className="dcst-control-plane-label">Network Security Control Plane</strong>
        <p>Define, review and synchronize communication policies with Proxmox Firewall.</p>
      </div>
    </div>
    <div className="dcst-header-side">
      <div className="dcst-runtime-status" aria-live="polite">
        <span className={`dcst-status-dot ${refreshing || synchronizing ? "busy" : "ready"}`} aria-hidden="true" />
        <div>
          <strong>{synchronizing ? "Synchronizing firewall policies" : inventorySynchronized ? "Inventory synchronized" : "Inventory not synchronized"}</strong>
          <small>{managedObjectCount} managed objects · Last sync: {lastSyncLabel}</small>
        </div>
      </div>
      <div className="header-actions">
        <button onClick={onRefresh} disabled={refreshing || synchronizing} aria-label="Refresh DCST inventory">
          <RefreshCw className={refreshing ? "spin" : ""} /> Refresh
        </button>
        {canSync && <button className="button-primary" onClick={onSynchronize} disabled={synchronizing || refreshing}>
          {synchronizing ? <RefreshCw className="spin" /> : <Play />}{synchronizing ? "Synchronizing..." : "Synchronize"}
        </button>}
      </div>
    </div>
  </header>;
}
