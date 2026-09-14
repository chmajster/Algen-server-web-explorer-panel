import { describe, expect, it } from "vitest";
import type { NtpDiagnostics } from "./api/client";
import { syncPresentation } from "./presentation";

const base: NtpDiagnostics = {
  backend: "chrony",
  available: true,
  role: "client_server",
  synchronized: true,
  timezone: "Europe/Warsaw",
  system_time: 1,
  source: "time.example.org",
  offset: "0 ms",
  stratum: 2,
  reachability: "377",
  jitter: "0.01 ms",
  service: "chrony",
  service_state: "active",
  enabled: true,
  health: "healthy",
  metrics: {},
  sources: [],
  summary: { source_count: 0, selected_count: 0, reachable_count: 0, client_count: 0 },
  warnings: [],
  collected_at: 1,
};

describe("syncPresentation", () => {
  it("does not report missing upstream synchronization in server-only mode", () => {
    const result = syncPresentation({ ...base, role: "server", synchronized: false, source: "", stratum: null });
    expect(result.title).toBe("Serwer NTP aktywny");
    expect(result.tone).toBe("success");
    expect(result.target).toBe("clients");
  });

  it("keeps degraded server-only mode visible without suggesting upstream sources", () => {
    const result = syncPresentation({ ...base, role: "server", synchronized: false, health: "degraded" });
    expect(result.title).toBe("Serwer NTP aktywny");
    expect(result.tone).toBe("warning");
    expect(result.target).not.toBe("sources");
  });
});
