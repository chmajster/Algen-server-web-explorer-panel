import { ArrowDown, RefreshCw, X } from "lucide-react";
import { useEffect } from "react";
import type { DcstIPSet, DcstPort, DcstService, DcstTag } from "../../../modules/dcst/api/client";
import { DcstObjectBadge, DcstStatusBadge } from "./DcstPrimitives";

function portLabel(port: DcstPort) {
  const range = port.port_from ? `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `–${port.port_to}` : ""}` : "";
  return `${port.name} · ${port.protocol.toUpperCase()}${range ? `/${range}` : ""}`;
}

export function DcstServiceDetails({
  service,
  preview,
  ports,
  tags,
  ipsets,
  lastSyncLabel,
  onClose,
}: {
  service: DcstService | null;
  preview: Record<string, unknown> | null;
  ports: DcstPort[];
  tags: DcstTag[];
  ipsets: DcstIPSet[];
  lastSyncLabel: string;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!service) return undefined;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [service, onClose]);

  if (!service) return null;
  const servicePorts = service.port_ids.map((id) => ports.find((port) => port.id === id)).filter((port): port is DcstPort => Boolean(port));
  const effectiveAction = service.blocked ? "DROP" : service.action;

  return <div className="dcst-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="dcst-drawer dcst-details-drawer" role="dialog" aria-modal="true" aria-labelledby="dcst-service-details-title">
      <header className="dcst-drawer-header"><div><h3 id="dcst-service-details-title">{service.name}</h3><p>{service.description || "Communication policy details"}</p></div><button className="icon-button" aria-label="Close service details" onClick={onClose}><X /></button></header>
      <div className="dcst-drawer-body">
        <section className="dcst-details-summary">
          <div><span>Status</span><DcstStatusBadge status={service.state} /></div>
          <div><span>Direction</span><strong>{service.direction}</strong></div>
          <div><span>Action</span><span className={`dcst-action-badge ${effectiveAction.toLowerCase()}`}>{effectiveAction}</span></div>
          <div><span>Synchronization</span><DcstStatusBadge status={service.sync_status || "UNKNOWN"} /></div>
        </section>

        <section className="dcst-form-section">
          <header><span>01</span><div><strong>Communication path</strong><small>Resolved policy endpoints</small></div></header>
          <div className="dcst-details-endpoint"><span>SOURCE</span><DcstObjectBadge type={service.source_type} value={service.source_value} tags={tags} ipsets={ipsets} showMeta /></div>
          <div className="dcst-drawer-flow"><ArrowDown /></div>
          <div className="dcst-details-endpoint"><span>DESTINATION</span><DcstObjectBadge type={service.destination_type} value={service.destination_value} tags={tags} ipsets={ipsets} showMeta /></div>
        </section>

        <section className="dcst-form-section">
          <header><span>02</span><div><strong>Ports</strong><small>Allowed transport objects</small></div></header>
          <div className="dcst-detail-port-list">{servicePorts.length ? servicePorts.map((port) => <span className="dcst-port-chip" key={port.id}>{portLabel(port)}</span>) : <span className="dcst-port-chip">ANY</span>}</div>
        </section>

        <section className="dcst-form-section">
          <header><span>03</span><div><strong>Policy metadata</strong><small>Operational configuration</small></div></header>
          <dl className="dcst-detail-list">
            <div><dt>Enabled</dt><dd>{service.enabled ? "Yes" : "No"}</dd></div>
            <div><dt>Logging</dt><dd>{service.logging ? "Enabled" : "Disabled"}</dd></div>
            <div><dt>Last synchronized</dt><dd>{lastSyncLabel}</dd></div>
            <div><dt>Comment</dt><dd>{service.comment || "—"}</dd></div>
          </dl>
        </section>

        {preview && <details className="dcst-preview-details"><summary><RefreshCw /> Synchronization preview</summary><pre>{JSON.stringify(preview, null, 2)}</pre></details>}
      </div>
    </aside>
  </div>;
}
