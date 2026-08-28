import type { DcstPort } from "../api/types";

export type PortDraft = Omit<DcstPort, "id" | "dependencies">;

export const emptyPortDraft: PortDraft = {
  name: "",
  protocol: "tcp",
  port_from: 443,
  port_to: 443,
  description: "",
};

export function portRangeLabel(port: Pick<DcstPort, "port_from" | "port_to">): string {
  if (!port.port_from) return "—";
  return `${port.port_from}${port.port_to && port.port_to !== port.port_from ? `–${port.port_to}` : ""}`;
}
