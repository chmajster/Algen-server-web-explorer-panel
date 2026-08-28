import { describe, expect, it } from "vitest";

import { buildEndpoint, splitEndpoint } from "./ProxmoxManagerApp";


describe("Proxmox endpoint input", () => {
  it("builds a scheme-less endpoint for backend protocol detection", () => {
    expect(buildEndpoint("10.0.0.10", "8006")).toBe("10.0.0.10:8006");
    expect(buildEndpoint("pve.example", "9000")).toBe("pve.example:9000");
  });

  it("keeps an explicitly supplied protocol", () => {
    expect(buildEndpoint("https://pve.example", "8006")).toBe("https://pve.example:8006");
    expect(buildEndpoint("http://10.0.0.10", "8006")).toBe("http://10.0.0.10:8006");
  });

  it("edits a saved canonical endpoint without forcing the protocol into the address field", () => {
    expect(splitEndpoint("https://10.0.0.10:8006")).toEqual({ address: "10.0.0.10", port: "8006" });
    expect(splitEndpoint("http://pve.example:8080")).toEqual({ address: "pve.example", port: "8080" });
  });

  it("uses the Proxmox default port for a bare host", () => {
    expect(splitEndpoint("10.0.0.10")).toEqual({ address: "10.0.0.10", port: "8006" });
  });
});
