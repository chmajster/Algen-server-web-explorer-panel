import { describe, expect, it } from "vitest";

import gitops from "./gitops-config-manager/manifest";
import jobs from "./job-queue-manager/manifest";
import loginHistory from "./login-history/manifest";
import ntp from "./ntp-manager/manifest";
import routing from "./routing-manager/manifest";


describe("infrastructure manager manifests", () => {
  it("registers all manager applications with their RBAC permissions", () => {
    expect([
      [jobs.id, jobs.permission],
      [ntp.id, ntp.permission],
      [routing.id, routing.permission],
      [loginHistory.id, loginHistory.permission],
      [gitops.id, gitops.permission],
    ]).toEqual([
      ["job-queue-manager", "jobs.view"],
      ["ntp-manager", "ntp.view"],
      ["routing-manager", "routing.view"],
      ["login-history", "login_history.view"],
      ["gitops-config-manager", "gitops.view"],
    ]);
  });
});
