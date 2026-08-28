import { describe, expect, it } from "vitest";

import type { SystemdService } from "../../../core/api/contracts";
import { filterUnavailableManagedWebnasUnits, isMissingManagedWebnasUnit } from "./client";

function service(overrides: Partial<SystemdService>): SystemdService {
  return {
    name: "webnas.service",
    status: "inactive",
    sub_state: "dead",
    enabled: "",
    uptime_seconds: null,
    last_error: "",
    managed_by_webnas: true,
    ...overrides,
  };
}

describe("WebNAS systemd service visibility", () => {
  it("detects a missing legacy WebNAS unit", () => {
    expect(isMissingManagedWebnasUnit(service({ name: "webnas.service", enabled: "" }))).toBe(true);
    expect(isMissingManagedWebnasUnit(service({ name: "webnas.service", enabled: "not-found" }))).toBe(true);
  });

  it("keeps installed blue-green units even when they are stopped", () => {
    expect(isMissingManagedWebnasUnit(service({ name: "webnas-backend-blue.service", enabled: "disabled" }))).toBe(false);
    expect(isMissingManagedWebnasUnit(service({ name: "webnas-backend-green.service", status: "active", enabled: "" }))).toBe(false);
  });

  it("does not filter unrelated allowlisted services", () => {
    expect(isMissingManagedWebnasUnit(service({ name: "docker.service", enabled: "unknown", managed_by_webnas: false }))).toBe(false);
  });

  it("removes only unavailable managed WebNAS units from the services response", () => {
    const services = [
      service({ name: "webnas.service", enabled: "" }),
      service({ name: "webnas-backend-blue.service", enabled: "disabled" }),
      service({ name: "webnas-backend-green.service", status: "active", enabled: "enabled" }),
      service({ name: "docker.service", enabled: "enabled", managed_by_webnas: false }),
    ];

    expect(filterUnavailableManagedWebnasUnits(services).map((item) => item.name)).toEqual([
      "webnas-backend-blue.service",
      "webnas-backend-green.service",
      "docker.service",
    ]);
  });
});
