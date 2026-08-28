import { Activity, Ban, Boxes, CircleAlert, CircleCheck, Network, Shield, Wrench } from "lucide-react";
import type { DcstPort, DcstService, DcstTag } from "../../../modules/dcst/api/client";
import { DcstStatusBadge } from "./DcstPrimitives";

function formatTimestamp(value: unknown) {
  if (!value) return "—";
  const numeric = Number(value);
  const date = Number.isFinite(numeric) ? new Date(numeric > 10_000_000_000 ? numeric : numeric * 1000) : new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export function DcstOverview({
  overview,
  services,
  tags,
  ports,
  ipsetCount,
}: {
  overview: Record<string, unknown>;
  services: DcstService[];
  tags: DcstTag[];
  ports: DcstPort[];
  ipsetCount: number;
}) {
  const recent = (overview.recent_changes as Array<Record<string, unknown>>) || [];
  const active = services.filter((item) => item.state === "ACTIVE").length;
  const blocked = services.filter((item) => item.blocked || item.state === "BLOCKED").length;
  const pending = services.filter((item) => item.state === "PENDING").length;
  const errors = services.filter((item) => item.state === "ERROR").length;
  const metrics = [
    ["Communication services", overview.services ?? services.length, Shield],
    ["Active", overview.active_services ?? active, CircleCheck],
    ["Blocked", overview.blocked_services ?? blocked, Ban],
    ["Needs attention", pending + errors, CircleAlert],
    ["Tags", overview.tags ?? tags.length, Network],
    ["IPSets", overview.ipsets ?? ipsetCount, Boxes],
    ["Port objects", overview.ports ?? ports.length, Network],
    ["Firewall rules", overview.firewall_rules ?? 0, Wrench],
  ] as const;

  return <div className="module-content dcst-overview">
    <div className="dcst-metric-grid">
      {metrics.map(([label, value, Icon]) => <article className="data-card dcst-metric-card" key={label}>
        <span className="dcst-metric-icon" aria-hidden="true"><Icon /></span>
        <div><small>{label}</small><strong>{String(value ?? 0)}</strong></div>
      </article>)}
    </div>

    <div className="dcst-overview-layout">
      <article className="data-card dcst-panel dcst-posture-card">
        <header><Shield /><div><strong>Policy posture</strong><small>Current desired-state distribution</small></div></header>
        <dl>
          <div><dt>Active</dt><dd><DcstStatusBadge status="ACTIVE" /> <strong>{active}</strong></dd></div>
          <div><dt>Blocked</dt><dd><DcstStatusBadge status="BLOCKED" /> <strong>{blocked}</strong></dd></div>
          <div><dt>Pending</dt><dd><DcstStatusBadge status="PENDING" /> <strong>{pending}</strong></dd></div>
          <div><dt>Errors</dt><dd><DcstStatusBadge status="ERROR" /> <strong>{errors}</strong></dd></div>
        </dl>
      </article>

      <article className="data-card dcst-panel dcst-recent-card">
        <header><Activity /><div><strong>Recent firewall changes</strong><small>Latest policy and synchronization activity</small></div></header>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Timestamp</th><th>User</th><th>Operation</th><th>Object</th><th>Status</th></tr></thead>
            <tbody>{recent.map((row, index) => <tr key={String(row.id || index)}>
              <td>{formatTimestamp(row.timestamp || row.at)}</td>
              <td>{String(row.user || row.actor || "—")}</td>
              <td>{String(row.operation || row.action || "—")}</td>
              <td>{String(row.object_type || "")}{row.object_id ? ` / ${String(row.object_id)}` : ""}</td>
              <td><DcstStatusBadge status={String(row.status || "SYNCED")} /></td>
            </tr>)}</tbody>
          </table>
        </div>
        {!recent.length && <div className="dcst-inline-empty">No firewall changes recorded yet.</div>}
      </article>
    </div>
  </div>;
}
