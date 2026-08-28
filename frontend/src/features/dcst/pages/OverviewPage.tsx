import type { DcstPort, DcstService, DcstTag } from "../api/types";
import { DcstOverview } from "../components/DcstOverview";

export function OverviewPage({ overview, services, tags, ports, ipsetCount }: {
  overview: Record<string, unknown>;
  services: DcstService[];
  tags: DcstTag[];
  ports: DcstPort[];
  ipsetCount: number;
}) {
  return <DcstOverview overview={overview} services={services} tags={tags} ports={ports} ipsetCount={ipsetCount} />;
}
