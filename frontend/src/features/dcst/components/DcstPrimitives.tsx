import { Boxes, Globe, Network, Shield } from "lucide-react";
import type { DcstIPSet, DcstService, DcstTag } from "../../../modules/dcst/api/client";

export type DcstStatus = DcstService["state"] | "SYNCED" | "OUT OF SYNC" | "UNKNOWN" | string;

export function DcstStatusBadge({ status }: { status: DcstStatus }) {
  const normalized = String(status || "UNKNOWN").trim().toUpperCase().replace(/_/g, " ");
  const tone = normalized.toLowerCase().replace(/ /g, "-");
  return <span className={`dcst-status-badge ${tone}`}><span aria-hidden="true" />{normalized}</span>;
}

export function DcstObjectBadge({
  type,
  value,
  tags,
  ipsets,
  showMeta = false,
}: {
  type: DcstService["source_type"];
  value: string;
  tags: DcstTag[];
  ipsets: DcstIPSet[];
  showMeta?: boolean;
}) {
  const tag = type === "tag" ? tags.find((item) => item.name === value) : undefined;
  const ipset = type === "ipset" ? ipsets.find((item) => item.id === value || item.name === value) : undefined;
  const label = type === "any" ? "ANY" : type === "ipset" ? `IPSET: ${ipset?.name || value}` : value || "ANY";
  const icon = type === "tag" || type === "apmid" ? <Network /> : type === "ipset" ? <Boxes /> : type === "ip" || type === "cidr" ? <Globe /> : <Shield />;
  const meta = tag ? `${tag.vm_count} VM${tag.vm_count === 1 ? "" : "s"}` : ipset ? `${ipset.entries.length} entr${ipset.entries.length === 1 ? "y" : "ies"}` : "";

  return <span className={`dcst-object-wrap ${type}`}>
    <span className="dcst-object-badge">{icon}<span>{label}</span></span>
    {showMeta && meta && <small>{meta}</small>}
  </span>;
}

export function DcstSkeletonRows({ columns, rows = 5 }: { columns: number; rows?: number }) {
  return <>{Array.from({ length: rows }, (_, row) => <tr key={row} className="dcst-skeleton-row">{Array.from({ length: columns }, (_, column) => <td key={column}><span /></td>)}</tr>)}</>;
}

export function DcstEmptyState({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return <div className="dcst-empty-state">
    <span className="dcst-empty-icon"><Shield /></span>
    <strong>{title}</strong>
    <p>{description}</p>
    {actionLabel && onAction && <button className="button-primary" onClick={onAction}>{actionLabel}</button>}
  </div>;
}
