import { describe, expect, it } from "vitest";
import { normalizeFirewallLog } from "./DcstApp";

describe("normalizeFirewallLog", () => {
  it("extracts filterable fields from raw Proxmox firewall log text", () => {
    const row = normalizeFirewallLog({
      node: "pve1",
      t: "TIME=2026-08-28T00:00:00Z DIR=IN SRC=10.0.0.10 DST=10.0.0.20 ACTION=DROP IN=vmbr0 OUT=fwbr100i0",
    });

    expect(row.dcst_time).toBe("2026-08-28T00:00:00Z");
    expect(row.dcst_direction).toBe("IN");
    expect(row.dcst_action).toBe("DROP");
    expect(row.dcst_source).toBe("10.0.0.10");
    expect(row.dcst_destination).toBe("10.0.0.20");
  });

  it("keeps structured fields authoritative when the backend already provides them", () => {
    const row = normalizeFirewallLog({
      direction: "OUT",
      action: "ACCEPT",
      source: "tag:APP.PROD",
      destination: "10.0.20.0/24",
      t: "DIR=IN ACTION=DROP SRC=10.1.1.1 DST=10.2.2.2",
    });

    expect(row.dcst_direction).toBe("OUT");
    expect(row.dcst_action).toBe("ACCEPT");
    expect(row.dcst_source).toBe("tag:APP.PROD");
    expect(row.dcst_destination).toBe("10.0.20.0/24");
  });

  it("parses action from the backend raw-only firewall log shape", () => {
    const row = normalizeFirewallLog({
      node: "pve1",
      t: "policy IN=vmbr0 OUT=fwbr100i0 ACTION=ACCEPT",
    });

    expect(row.dcst_action).toBe("ACCEPT");
    expect(row.dcst_raw).toContain("ACTION=ACCEPT");
  });

  it("does not invent a timestamp when a raw log has none", () => {
    const row = normalizeFirewallLog({ node: "pve1", t: "ACTION=ACCEPT" });
    expect(row.dcst_time).toBe("");
    expect(row.dcst_action).toBe("ACCEPT");
  });
});
